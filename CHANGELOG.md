# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-11-22

### Added
- `scripts/scheduled-message-guard.py` — a mechanical gate for outbound
  scheduled messages. The review → critic cycle shapes what the agent thinks;
  it cannot stop a cron sender from reusing an opener or firing too soon,
  because the sender never reads the prompt. The guard checks the candidate
  against five rules before the send: minimum interval since the last message,
  a seven-day repeat window on openers, pause after two consecutive unanswered
  messages, bare-openers rejection, and a forbidden-term list. Exit `0` allows,
  `1` blocks, `2` means malformed input; `--json` emits the verdict for a
  wrapper to log.
- `docs/SCHEDULED_MESSAGE_GUARD.md` — rule rationale, history format, and the
  cron-wrapper pattern that appends to history only after a successful send.
- `config/scheduled-message-guard.json.example` — cadence and vocabulary
  defaults, overridable per deployment.
- `tests/` — 16 unittest cases covering every rule, the boundary conditions
  (exactly at the interval, exactly at the repeat-window edge), and the history
  parser. Run with `python3 -m unittest discover -s tests`.

### Fixed
- The bare-opener rule originally inspected only the opening clause, so a
  message like "pagi nov, semoga mudah kuliahnya" was rejected even though it
  says something. It now checks whether any word outside the greeting
  vocabulary survives, which is the distinction that actually matters.

## [0.1.1] — 2026-11-21

### Fixed
- Removed `config/cron-schedules.yaml`, `config/model-pinning.yaml` and
  `config/stability-limits.yaml` from version control. All three were byte-identical
  copies of their `.example` templates and are meant to be created by the operator
  (`cp config/<name>.yaml.example config/<name>.yaml`), so shipping them invited
  silent drift between a stale tracked copy and the file the scripts actually read.
- Added `.gitignore` covering those three local config paths plus common OS/editor noise,
  so a customized local config can no longer be committed by accident.

## [0.1.0] — 2026-11-20

### Added
- Initial release.
- Two independent tracks: **personality** (tone, style, identity) and
  **autonomy** (boundaries, escalation, permission scope).
- Four cron entry points: `personality-review`, `personality-critic`,
  `autonomy-review`, `autonomy-critic`.
- Prompt templates for each stage under `prompts/`.
- Artifact templates under `artifacts/`: `soul`, `user`, `memory`, `proposals`
  and `critic-log`.
- `docs/`: architecture, customization, evidence standards,
  permission-creep guards, troubleshooting.
- `scripts/`: `deploy-cron.sh`, `pin-model.sh`, `verify-deployment.sh`.
- Worked examples under `examples/`: `generic-agent` and `lucy-config`.
- MIT license.

[0.1.1]: https://github.com/nxstradamuss/agent-personality-pipeline/releases/tag/v0.1.1
[0.1.0]: https://github.com/nxstradamuss/agent-personality-pipeline/releases/tag/v0.1.0
