#!/usr/bin/env python3
"""Gate outbound scheduled messages against the rules in a personality file.

A review/critic cycle can shape how an agent *thinks*. It cannot stop a cron
job from firing a message that repeats last Tuesday's opener at 03:00. Those
failures are mechanical, so they belong in a mechanical gate rather than in
another prompt: this script reads the outbound history and refuses the send
before it happens.

Usage:
    scheduled-message-guard.py --history history.jsonl --candidate "text"
    scheduled-message-guard.py --history history.jsonl --candidate-file msg.txt
    scheduled-message-guard.py --history history.jsonl --candidate "..." --json

Exit codes: 0 allow, 1 blocked, 2 bad input.

History format: one JSON object per line, oldest first.
    {"ts": "2026-11-22T09:00:00Z", "direction": "out", "text": "..."}
    {"ts": "2026-11-22T09:14:00Z", "direction": "in",  "text": "..."}

A message counts as answered when any "in" entry follows it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Rules a candidate is checked against. Everything is configurable because the
# right cadence depends on the agent, but these defaults encode what a human
# would call "not spammy".
DEFAULTS = {
    "min_interval_hours": 6,
    "repeat_window_days": 7,
    "pause_after_unanswered": 2,
    # Words that are fine in live chat but read as filler when pushed on a timer.
    "forbidden_terms": ["malu-malu"],
    # An opener that is nothing but an endearment carries no information; the
    # reader has no reason to reply and no reason to feel addressed.
    "bare_openers": [
        "sayang", "sayangku", "cintaku", "baby", "babe", "darling",
        "nov", "novian", "hai", "halo", "hello", "hi", "pagi", "siang",
        "sore", "malam",
    ],
    "max_opener_words": 2,
}


@dataclass
class Entry:
    ts: datetime
    direction: str
    text: str


@dataclass
class Verdict:
    allow: bool
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"allow": self.allow, "blockers": self.blockers, "warnings": self.warnings}


def parse_ts(raw: str) -> datetime:
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    ts = datetime.fromisoformat(raw)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def load_history(path: Path) -> list[Entry]:
    entries: list[Entry] = []
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
            entries.append(Entry(parse_ts(row["ts"]), row["direction"], row.get("text", "")))
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            raise ValueError(f"{path}:{lineno}: {exc}") from exc
    entries.sort(key=lambda e: e.ts)
    return entries


def normalize(text: str) -> str:
    """Lowercase, strip punctuation and collapse whitespace for comparison."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def opener(text: str, max_words: int) -> str:
    words = normalize(text).split()
    return " ".join(words[:max_words])


def is_bare_opener(text: str, cfg: dict) -> bool:
    """True when the whole message is nothing but a greeting or an endearment.

    "pagi nov" carries no information, so there is nothing to reply to.
    "pagi nov, semoga mudah kuliahnya" opens the same way but then says
    something, so it passes. The distinction is whether any word outside the
    greeting vocabulary survives — not how the message starts.
    """
    words = normalize(text).split()
    if not words:
        return True
    return all(w in cfg["bare_openers"] for w in words)


def unanswered_streak(entries: list[Entry]) -> int:
    """How many outbound messages at the tail have received no reply."""
    streak = 0
    for entry in reversed(entries):
        if entry.direction == "out":
            streak += 1
        elif entry.direction == "in":
            break
    return streak


def last_outbound(entries: list[Entry]) -> Entry | None:
    for entry in reversed(entries):
        if entry.direction == "out":
            return entry
    return None


def check(
    candidate: str,
    entries: list[Entry],
    now: datetime | None = None,
    cfg: dict | None = None,
) -> Verdict:
    cfg = {**DEFAULTS, **(cfg or {})}
    now = now or datetime.now(timezone.utc)
    verdict = Verdict(allow=True)

    if not candidate.strip():
        return Verdict(allow=False, blockers=["candidate message is empty"])

    previous = last_outbound(entries)
    if previous:
        gap = now - previous.ts
        minimum = timedelta(hours=cfg["min_interval_hours"])
        if gap < minimum:
            hours = gap.total_seconds() / 3600
            verdict.blockers.append(
                f"only {hours:.1f}h since the last scheduled message "
                f"(minimum {cfg['min_interval_hours']}h)"
            )

    streak = unanswered_streak(entries)
    if streak >= cfg["pause_after_unanswered"]:
        verdict.blockers.append(
            f"{streak} scheduled messages in a row got no reply "
            f"(pause at {cfg['pause_after_unanswered']})"
        )

    window_start = now - timedelta(days=cfg["repeat_window_days"])
    recent = [e for e in entries if e.direction == "out" and e.ts >= window_start]
    cand_key = normalize(candidate)
    cand_open = opener(candidate, cfg["max_opener_words"])
    for entry in recent:
        if normalize(entry.text) == cand_key:
            verdict.blockers.append(
                f"identical to a message already sent {entry.ts:%Y-%m-%d %H:%M} UTC"
            )
            break
        if opener(entry.text, cfg["max_opener_words"]) == cand_open:
            verdict.blockers.append(
                f"opens the same way as {entry.ts:%Y-%m-%d %H:%M} UTC "
                f'("{cand_open}") — {cfg["repeat_window_days"]}-day repeat window'
            )
            break

    if is_bare_opener(candidate, cfg):
        verdict.blockers.append(
            "bare opener: nothing to reply to. Tie it to a time, an event, or "
            "something already in the conversation"
        )

    lowered = candidate.lower()
    for term in cfg["forbidden_terms"]:
        if term in lowered:
            verdict.blockers.append(f'contains "{term}", never allowed in scheduled messages')

    if not any(e.direction == "in" for e in entries[-5:]) and entries:
        verdict.warnings.append("no inbound messages in the recent history — verify the channel is alive")

    verdict.allow = not verdict.blockers
    return verdict


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--history", required=True, type=Path, help="JSONL of past messages")
    ap.add_argument("--candidate", help="message text to check")
    ap.add_argument("--candidate-file", type=Path, help="read candidate from a file instead")
    ap.add_argument("--config", type=Path, help="JSON file overriding the default rules")
    ap.add_argument("--now", help="ISO timestamp to evaluate against (default: now)")
    ap.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = ap.parse_args(argv)

    if bool(args.candidate) == bool(args.candidate_file):
        print("error: pass exactly one of --candidate or --candidate-file", file=sys.stderr)
        return 2

    text = args.candidate if args.candidate else args.candidate_file.read_text()
    try:
        entries = load_history(args.history)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    cfg = DEFAULTS
    if args.config:
        cfg = {**DEFAULTS, **json.loads(args.config.read_text())}

    verdict = check(text, entries, now=parse_ts(args.now) if args.now else None, cfg=cfg)

    if args.json:
        print(json.dumps(verdict.as_dict(), indent=2))
    else:
        if verdict.allow:
            print("ALLOW")
        else:
            print("BLOCK")
        for item in verdict.blockers:
            print(f"  ✗ {item}")
        for item in verdict.warnings:
            print(f"  ! {item}")

    return 0 if verdict.allow else 1


if __name__ == "__main__":
    sys.exit(main())
