# Scheduled Message Guard

The review → critic cycle shapes what an agent *thinks*. It does not stop a cron
job from firing last Tuesday's opener at 03:00. Those failures are mechanical:
the same template, too soon, into a conversation nobody answered. No amount of
prompting reliably fixes them, because the sender never reads the prompt.

`scheduled-message-guard.py` closes that gap. It reads the outbound history,
checks the candidate against a small set of rules, and refuses the send before
it happens.

```bash
python3 scripts/scheduled-message-guard.py \
  --history ~/.agent/history.jsonl \
  --candidate "snapshot 22 Nov udah ke-push, disk 83%"
```

Exit `0` allows the send, `1` blocks it, `2` means the input was malformed.
`--json` emits the verdict as an object for a cron wrapper to consume.

## What it checks

| Rule | Default | Why |
| --- | --- | --- |
| Minimum interval | 6 hours | A scheduled message every hour is a notification, not a companion. |
| Repeat window | 7 days | Reusing an opener is the fastest way to feel automated. |
| Pause after unanswered | 2 messages | If two pushes got no reply, a third is noise. Stop and wait to be asked. |
| Bare opener | greeting-only | A message with nothing to reply to has no reason to exist. |
| Forbidden terms | `malu-malu` | Vocabulary that reads as filler once it is pushed on a timer. |

Each rule is a separate blocker in the verdict, so a caller can log exactly why
a send was refused instead of guessing.

## History format

One JSON object per line, oldest first:

```json
{"ts": "2026-11-22T01:00:00Z", "direction": "out", "text": "disk udah 83%, aku rapikan backup ya"}
{"ts": "2026-11-22T02:30:00Z", "direction": "in",  "text": "oke"}
{"ts": "2026-11-22T03:00:00Z", "direction": "out", "text": "pagi nov, kuliahnya jam berapa?"}
```

An `out` message counts as answered when any `in` entry follows it. Only the
tail matters for the pause rule: the streak resets on the first reply.

That `in` line is the whole difficulty. An agent typically records scheduled
sends in one place and conversation turns in another, and neither file holds
both directions. `scripts/history-adapter.py` merges them:

```bash
python3 scripts/history-adapter.py \
  --chat-history ~/.agent/chat_history.json \
  --state-db ~/.agent/state.db \
  --out ~/.agent/guard_history.jsonl
```

Without the inbound half the pause rule can never fire, so the agent pushes
into silence indefinitely. With the outbound half missing it inverts: the first
send after any quiet period looks like a first-ever send, and the interval
check has nothing to measure against.

## Wiring it into a cron sender

The guard is a filter, not a daemon. Put it in front of the send, in the
sender's own language, before the network call:

```python
from send_guard import allow_send

text = pick_template()
ok, reason = allow_send(text)
if not ok:
    log(f"blocked: {reason}")
    return              # a blocked send is not an error
send_message(text)
append_history(text)    # only after a successful send
```

`examples/send-guard-wrapper.py` is the complete reference. Two properties
carry more weight than the code:

- **Fail open on infrastructure error, fail closed on a verdict.** Missing
  guard, unreadable history, or a crash means allow-and-log. A bug in the
  safety filter must never turn into permanent silence — that failure looks
  exactly like the agent being dead. An explicit block (exit `1`) is honoured,
  because that verdict came from working rules.
- **Invalidate cached history when a send lands.** Caching the merged JSONL for
  a few minutes is fine; not invalidating on `chat_history` mtime change is not.
  A stale cache makes the interval and repeat checks evaluate pre-send data and
  pass when they should block.

Append to the history only *after* a successful send. Recording a blocked
candidate pollutes the interval and repeat checks — and two copies of one
retried send will satisfy the unanswered-pause counter all by themselves.

A shell sender works the same way:

```bash
#!/bin/bash
set -uo pipefail
HISTORY="$HOME/.agent/history.jsonl"
CANDIDATE=$(python3 render_message.py)

if ! python3 scripts/scheduled-message-guard.py \
       --history "$HISTORY" --candidate "$CANDIDATE"; then
    echo "blocked by guard; not sending" >&2
    exit 0            # a blocked send is not an error
fi

send_message "$CANDIDATE"
printf '{"ts":"%s","direction":"out","text":%s}\n' \
    "$(date -u +%FT%TZ)" "$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$CANDIDATE")" \
    >> "$HISTORY"
```

## Tuning

Copy `config/scheduled-message-guard.json.example` to
`config/scheduled-message-guard.json` and pass `--config`. Only the keys you
set override the defaults; the rest stay as they are.

Raise `min_interval_hours` for a quieter agent, lower `pause_after_unanswered`
to 1 for an agent whose user rarely replies to pushes, and extend
`bare_openers` with whatever the agent tends to open with.

## Tests

```bash
python3 -m unittest discover -s tests
```

One hundred cases across five files.

Sixteen cover each guard rule and its boundary conditions (exactly at the
interval, exactly at the repeat-window edge). Eighteen cover the history
adapter — the midnight-wrap timezone case, epoch conversion, quoted-reply
truncation, read-only enforcement on the session DB, and dedupe.

Eleven cover the wrapper itself (`tests/test_send_guard_wrapper.py`), which is
where the fail-open/fail-closed split actually lives: missing guard,
unbuildable history, an unexecutable guard, a crashing guard, an unexpected
exit code, and a corrupt-history exit `2` all allow the send; only an explicit
`allow: false` verdict refuses it. That distinction needs a test because a
crash exits `1` too — the exit code alone cannot carry it, so the wrapper reads
the payload.

Forty-four more live in `tests/test_history_adapter_edge_cases.py` and cover
the seam between the two scripts, which is where a wrong verdict is easiest to
produce: non-UTC offsets, date-only WIB stamps, malformed JSONL records, an
empty history, and a retried send that re-stamps `sent_at` by a few seconds.
The retry window is `--dedupe-window`, default 120s, and applies to outbound
only — a person can send "ok" twice in five seconds.

The remaining eleven (`tests/test_readme_claims.py`) check that every claim in
the README maps to a control in the code and a test in `tests/`.

The guard's history parser validates each record's shape and names the
offending line number rather than failing silently, and anything it does not
anticipate is caught at the top of `main` and turned into exit `2`. That
matters because exit `1` means "blocked", so an uncaught traceback would be
indistinguishable from a verdict — and the wrapper fails open on a crash, so a
corrupt line would quietly disable the gate. The adapter, on the other side of
the seam, skips individual malformed rows instead of discarding a whole file
over one bad timestamp.
