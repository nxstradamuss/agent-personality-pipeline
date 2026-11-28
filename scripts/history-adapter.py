#!/usr/bin/env python3
"""Adapt Lucy's real message stores into the guard's history contract.

`scheduled-message-guard.py` expects a flat JSONL stream:

    {"ts": "2026-11-22T09:00:00Z", "direction": "out", "text": "..."}
    {"ts": "2026-11-22T09:14:00Z", "direction": "in",  "text": "..."}

Lucy's data lives in two places, in two formats, and neither matches:

  1. ``~/.hermes/chat_history.json`` -- an array of *outbound scheduled*
     messages only, stamped ``"2026-11-24 09:34 WIB"`` (no direction, no zone
     offset, WIB wall-clock).
  2. ``~/.hermes/state.db`` -- SQLite ``messages`` table with unix-epoch
     ``timestamp`` floats. This is the only place *inbound* messages exist.

The consequence matters more than the format gap. Rule 3 of the guard --
"pause after N unanswered sends" -- is the one that stops an agent from
pushing into silence. It needs ``direction: "in"`` entries. `chat_history.json`
records nothing but outbound, so a guard fed from that file alone is blind to
every reply Novian ever sent and would block the first send after silence
forever. Both sources have to be merged, which is what this script does.

Usage:
    history-adapter.py --chat-history ~/.hermes/chat_history.json \\
                       --state-db ~/.hermes/state.db \\
                       --out /tmp/history.jsonl

    # outbound only (no state.db available, e.g. on a fresh host)
    history-adapter.py --chat-history ~/.hermes/chat_history.json --out out.jsonl

Exit codes: 0 ok, 2 bad input (missing/unparseable source).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

# Indonesia has no DST, so a fixed offset is correct rather than a tz database
# lookup. WIB is UTC+7 everywhere and always.
WIB = timezone(timedelta(hours=7))

# Telegram replies arrive as a quoted blob. The guard's repeat-window rule
# compares openers; leaving the quote in makes every reply look unique and
# defeats the check. Truncate to the first line for opener purposes.
MAX_INBOUND_CHARS = 400


def parse_wib(stamp: str) -> datetime | None:
    """Parse ``"2026-11-24 09:34 WIB"`` into an aware UTC datetime.

    Returns None instead of raising: one malformed row in a 50-entry history
    should not cost the whole file.
    """
    if not isinstance(stamp, str):
        return None
    cleaned = stamp.strip().replace("WIB", "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            naive = datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
        return naive.replace(tzinfo=WIB).astimezone(timezone.utc)
    return None


def from_epoch(value: Any) -> datetime | None:
    """Convert a unix-epoch float/int to an aware UTC datetime."""
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def load_outbound(path: Path) -> list[dict[str, Any]]:
    """Read chat_history.json -> outbound entries."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a JSON array, got {type(raw).__name__}")

    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        ts = parse_wib(row.get("sent_at", ""))
        text = row.get("text")
        if ts is None or not isinstance(text, str) or not text.strip():
            continue
        out.append(
            {
                "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "direction": "out",
                "text": text.strip(),
                "source": "scheduled",
            }
        )
    return out


def load_inbound(path: Path) -> list[dict[str, Any]]:
    """Read state.db messages table -> inbound (user) entries.

    Opened read-only via URI so a running agent that holds the DB write lock
    is not disturbed, and so an accidental write is impossible.
    """
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    try:
        rows = conn.execute(
            "SELECT timestamp, content FROM messages "
            "WHERE role = 'user' AND content IS NOT NULL "
            "ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    for stamp, content in rows:
        ts = from_epoch(stamp)
        if ts is None or not isinstance(content, str):
            continue
        text = content.strip().split("\n", 1)[0][:MAX_INBOUND_CHARS]
        if not text:
            continue
        out.append(
            {
                "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "direction": "in",
                "text": text,
                "source": "telegram",
            }
        )
    return out


DEFAULT_DEDUPE_WINDOW = 120
"""Seconds within which two outbound copies of the same text are one send.

The guard's minimum interval is hours, so two identical scheduled sends two
minutes apart can only be a retry, never two deliberate messages. A retry
that re-stamps `sent_at` a few seconds later used to survive as two entries,
and two copies of one message satisfy the guard's "N unanswered in a row"
counter on their own -- pausing a healthy sender.
"""


def _instant(ts: str) -> datetime | None:
    """Parse an adapter-emitted timestamp, tolerating anything unexpected.

    A timestamp that will not parse simply opts out of the retry window rather
    than crashing the merge; the exact-key dedupe above has already run.
    """
    try:
        return _parse_iso(ts)
    except (TypeError, ValueError):
        return None


def _parse_iso(ts: str) -> datetime:
    raw = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def merge(
    *groups: Iterable[dict[str, Any]],
    dedupe_window_seconds: int = DEFAULT_DEDUPE_WINDOW,
) -> list[dict[str, Any]]:
    """Concatenate and sort chronologically, dropping duplicates.

    Two kinds of duplicate are dropped:

    * **Exact** — same `(ts, direction, text)` in any direction. A literal
      double-write of one row.
    * **Retried send** — same direction (`out` only), same text, timestamps
      within `dedupe_window_seconds`. A retried cron send re-stamps `sent_at`,
      so the exact key does not catch it. The earliest copy is the one kept:
      at an hours-scale interval the choice barely matters, but picking a
      fixed end keeps the output deterministic.

    The window deliberately does not apply to inbound. A person can send "ok"
    twice in five seconds; collapsing those would invent a conversation that
    did not happen and can hide a real reply.
    """
    seen: set[tuple[str, str, str]] = set()
    merged: list[dict[str, Any]] = []
    for group in groups:
        for entry in group:
            key = (entry["ts"], entry["direction"], entry["text"])
            if key in seen:
                continue
            seen.add(key)
            merged.append(entry)
    merged.sort(key=lambda e: e["ts"])

    if dedupe_window_seconds <= 0:
        return merged

    kept: list[dict[str, Any]] = []
    last_outbound: dict[str, datetime] = {}
    for entry in merged:
        if entry["direction"] == "out":
            previous = last_outbound.get(entry["text"])
            current = _instant(entry["ts"])
            if previous is not None and current is not None:
                if abs((current - previous).total_seconds()) <= dedupe_window_seconds:
                    continue  # a retry of the copy already kept
            if current is not None:
                last_outbound[entry["text"]] = current
        kept.append(entry)
    return kept


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Merge Lucy's outbound history and inbound messages into "
        "the JSONL contract consumed by scheduled-message-guard.py."
    )
    ap.add_argument(
        "--chat-history",
        required=True,
        type=Path,
        help="path to chat_history.json (outbound scheduled messages)",
    )
    ap.add_argument(
        "--state-db",
        type=Path,
        help="path to Hermes state.db (inbound user messages); optional",
    )
    ap.add_argument("--out", required=True, type=Path, help="output .jsonl path")
    ap.add_argument(
        "--dedupe-window",
        type=int,
        default=DEFAULT_DEDUPE_WINDOW,
        metavar="SECONDS",
        help="collapse outbound copies of the same text sent within this many "
        f"seconds (default: {DEFAULT_DEDUPE_WINDOW}; 0 disables)",
    )
    args = ap.parse_args(argv)

    if not args.chat_history.exists():
        print(f"error: {args.chat_history} not found", file=sys.stderr)
        return 2

    try:
        groups = [load_outbound(args.chat_history)]
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"error: {args.chat_history}: {exc}", file=sys.stderr)
        return 2

    if args.state_db is not None:
        if not args.state_db.exists():
            print(f"warning: {args.state_db} not found, outbound only", file=sys.stderr)
        else:
            try:
                groups.append(load_inbound(args.state_db))
            except sqlite3.Error as exc:
                print(f"warning: {args.state_db}: {exc}, outbound only", file=sys.stderr)

    entries = merge(*groups, dedupe_window_seconds=args.dedupe_window)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    outs = sum(1 for e in entries if e["direction"] == "out")
    ins = len(entries) - outs
    print(f"{args.out}: {len(entries)} entries ({outs} out, {ins} in)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
