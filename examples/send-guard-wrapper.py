#!/usr/bin/env python3
"""Example: gate a template-pool sender through the guard.

Copy next to your sender and adjust the four paths. This is the piece that
actually stops drift -- the guard on its own is just a script nobody calls.

Design notes worth keeping when you adapt this:

1. **Fail-open on infrastructure error, fail-closed on a verdict.**
   If the guard is missing or crashes, allow the send and log loudly. A bug in
   the safety filter must not become permanent silence -- that is
   indistinguishable from the agent being broken. But when the guard returns
   an explicit block (exit 1), respect it: that verdict came from working rules.

2. **Rebuild history when a send lands.**
   Cache the JSONL for a few minutes to avoid re-querying SQLite on every
   candidate, but invalidate on `chat_history` mtime change. A stale cache
   makes the interval and repeat checks evaluate data from before the last
   message, so they pass when they should block.

3. **Record blocked candidates separately.**
   Append to history only AFTER a successful send. Logging a blocked candidate
   as if it were sent pollutes both the interval and the repeat window.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- adjust these four ------------------------------------------------------
GUARD = Path(__file__).resolve().parent / "scheduled-message-guard.py"
ADAPTER = Path(__file__).resolve().parent / "history-adapter.py"
CHAT_HISTORY = Path.home() / ".agent" / "chat_history.json"
STATE_DB = Path.home() / ".agent" / "state.db"
CACHE = Path.home() / ".agent" / "guard_history.jsonl"
DECISION_LOG = Path.home() / ".agent" / "guard-decisions.log"
CACHE_MAX_AGE_SECONDS = 300
# ----------------------------------------------------------------------------


def log(message: str) -> None:
    try:
        DECISION_LOG.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with DECISION_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {message}\n")
    except OSError:
        pass


def _cache_is_fresh() -> bool:
    if not CACHE.exists():
        return False
    try:
        age = datetime.now(timezone.utc).timestamp() - CACHE.stat().st_mtime
        if age > CACHE_MAX_AGE_SECONDS:
            return False
        return CHAT_HISTORY.stat().st_mtime <= CACHE.stat().st_mtime
    except OSError:
        return False


def build_history(force: bool = False) -> Path | None:
    if not force and _cache_is_fresh():
        return CACHE
    cmd = [sys.executable, str(ADAPTER), "--chat-history", str(CHAT_HISTORY),
           "--out", str(CACHE)]
    if STATE_DB.exists():
        cmd += ["--state-db", str(STATE_DB)]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"adapter-error {exc}")
        return CACHE if CACHE.exists() else None
    if res.returncode != 0:
        log(f"adapter-fail rc={res.returncode} {res.stderr.strip()[:200]}")
        return CACHE if CACHE.exists() else None
    return CACHE


def allow_send(text: str) -> tuple[bool, str]:
    if not GUARD.exists():
        log("guard-missing -> allowing")
        return True, "guard-missing"
    history = build_history()
    if history is None:
        log("history-unavailable -> allowing")
        return True, "history-unavailable"
    try:
        res = subprocess.run(
            [sys.executable, str(GUARD), "--history", str(history),
             "--candidate", text, "--json"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"guard-error {exc} -> allowing")
        return True, "guard-error"

    if res.returncode == 1:
        try:
            reason = "; ".join(json.loads(res.stdout).get("blockers", [])) or "blocked"
        except (json.JSONDecodeError, AttributeError):
            reason = "blocked"
        log(f"BLOCK {reason} | text={text[:80]!r}")
        return False, reason
    if res.returncode == 0:
        log(f"ALLOW | text={text[:80]!r}")
        return True, "ok"
    log(f"guard-unexpected rc={res.returncode} -> allowing")
    return True, f"guard-rc-{res.returncode}"


if __name__ == "__main__":
    candidate = " ".join(sys.argv[1:])
    if not candidate:
        print("usage: send-guard-wrapper.py <candidate text>", file=sys.stderr)
        raise SystemExit(2)
    allowed, reason = allow_send(candidate)
    print(json.dumps({"allow": allowed, "reason": reason}, ensure_ascii=False))
    raise SystemExit(0 if allowed else 1)
