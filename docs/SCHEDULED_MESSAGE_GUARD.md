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

## Wiring it into a cron sender

The guard is a filter, not a daemon. Put it in front of the send:

```bash
#!/bin/bash
# scheduled-send.sh — refuse to send unless the guard allows it
set -uo pipefail

HISTORY="$HOME/.agent/history.jsonl"
CANDIDATE=$(python3 render_message.py)   # whatever picks the template

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

Append to the history only *after* a successful send. Recording a blocked
candidate pollutes the interval and repeat checks.

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

Sixteen cases covering each rule, the boundary conditions (exactly at the
interval, exactly at the repeat-window edge), and the history parser. The
parser names the offending line number on bad input rather than failing
silently.
