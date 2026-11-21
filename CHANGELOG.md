# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
