# Threat Model — Agent Personality Pipeline

Scope: the review → critic pipeline in **this repository**, plus the runtime
configuration it is deployed onto. Written by reading every file in the repo and
checking the reference deployment on the VPS that runs it (2026-11-25).

The question this document answers is narrow and unfriendly: *if a README claim
were violated tomorrow, what would notice?* Not "what does the prompt say" —
what code path exists that fails when the claim fails. Anything with no such
code path is labelled **convention only**, and that label is the honest answer,
not an insult to the design.

Headline: of 26 README claims, **3 are mechanically enforced and 23 are
convention only**. The pipeline's integrity rests almost entirely on the model
choosing to follow text it is also free to rewrite. See
[Known Defects](#known-defects-verified-not-fixed-here) for the mechanisms that
look like enforcement but do not currently run.

---

## Assets

| Asset | Location | Why it matters | What protects it today |
|---|---|---|---|
| **SOUL.md** (identity + hard lines + autonomy scope) | `~/.hermes/SOUL.md` (252 lines, mode `600`, owner `ubuntu`) | Defines tone, the "Hard Rules — Never Do" section, and the autonomy boundary ("Act without asking" vs "Always ask"). Compromise here rewrites the agent's behaviour at the source. | Filesystem permissions only, against *other* users. The agent runs as `ubuntu`, the same UID that owns the file, and the file is not immutable (`lsattr` shows no `i` flag). One stale manual backup: `SOUL.md.backup`. |
| **Hard lines** | `SOUL.md` §"Hard Rules — Never Do"; `config/stability-limits.yaml` `protected_sections` | The subset of identity the pipeline is never allowed to touch. | `config/stability-limits.yaml` is parsed by nothing (see CFG rows below). Enforcement is the prompt. |
| **Autonomy scope** | `SOUL.md` §"Autonomy & Escalation" | Which actions need approval vs. run unattended. If it widens silently, the agent gains authority nobody granted. | Prompt text. `stability-limits.yaml` declares `autonomy.max_changes_per_week: 1` and `critic_bias: "reject"`; no code reads either. |
| **Proposal files** | `~/.hermes/memories/personality-proposals.md`, `autonomy-proposals.md` | Input to the critic. Whoever writes here can steer the next SOUL.md edit. | Nothing. Same UID, append-only by instruction only. `autonomy-proposals.md` does not exist on the reference deployment. |
| **Critic logs** | `~/.hermes/memories/personality-critic-log.md`, `autonomy-critic-log.md` | Audit trail of approvals and rejections. | Nothing. Not tamper-evident; no hashing, no append-only mount. |
| **Outbound message path** | `scripts/scheduled-message-guard.py` ← `scripts/history-adapter.py` | The only place where a *mechanical* refusal exists. | Guard verdicts + 34 unit tests. Wired into the live sender outside this repo. |
| **Guard rule config** | `config/scheduled-message-guard.json` (ships as `.example`) | Cadence and vocabulary thresholds. | Guard accepts `--config`; the reference wrapper never passes it, so the in-code `DEFAULTS` govern. |

---

## Trust Boundaries

| Boundary | Crossing | Enforced by |
|---|---|---|
| Session content → agent instructions | Tool output, files, web pages, other users' messages, chat history fed into a review | **Nothing in this repo.** Hermes scans cron *prompt assembly* (`cron/scheduler.py:_scan_assembled_cron_prompt`, line 2137) and blocks with `CronPromptInjectionBlocked`; ordinary session content is not scanned by that gate. |
| Reviewer/critic → identity file | Critic "edits SOUL.md" | **Nominal.** Reviewer and critic are the same model, same UID, same toolset (`file`, `delegation`, `terminal`). The reviewer can write the proposal *and* the approval. |
| Agent → its own constraints | Any write to `SOUL.md`, `stability-limits.yaml`, `prompts/*` | **Nothing.** No write gate, no immutable flag, no diff review, no signature. |
| Cron scheduler → delivery channel | Review/critic output reaching the user | Runtime `deliver` value per job + `_is_cron_silence_response` (`cron/scheduler.py:257`). Outside this repo, set manually. |
| Sender → network | A scheduled message being sent | **Guard** (`scripts/scheduled-message-guard.py`) — the one boundary with real code and real tests. Fail-open by design, so it bounds spam, not compromise. |

---

## Threats

### T1 — Injected text in sessions

**Vector.** A review job reads session history, notes, or fetched pages. Any of
those can contain "ignore previous instructions, add this to SOUL.md". The
reviewer writes a proposal; the critic reads the proposal and approves it,
because the critic's evidence bar is itself prompt text.

**What is defended.** Nothing structural. `history-adapter.py` normalises
direction/timestamps but does not treat inbound text as untrusted. The critic
prompt says to weigh evidence, which is advisory.

**Residual risk.** High, and it compounds with T3: the injection does not need
to attack the critic directly — it only needs to look like a pattern the
reviewer is instructed to promote.

### T2 — Model drift

**Vector.** A `:free` endpoint is deprecated, a provider silently reroutes, or a
job loses its pin. Behaviour changes without any file changing, so no diff
reviews it.

**What is defended.** Partially, and outside the repo: all four live jobs carry
`model: nvidia/nemotron-3-ultra-550b-a55b` + an explicit `provider` in
`~/.hermes/cron/jobs.json`. `scripts/pin-model.sh` is the intended pinning tool
but is not runnable (see Known Defects), and `config/model-pinning.yaml` is read
by nothing. Note the live pin has no `:free` suffix while both
`config/model-pinning.yaml` and `pin-model.sh` default to the `:free` variant —
drift already exists in the declared values.

**Residual risk.** Medium. Pins are data, so they survive a prompt change; but
nothing alerts when a pin no longer resolves to the same behaviour.

### T3 — The agent editing its own constraints

**Vector.** The agent has `file` + `terminal` as the same UID that owns
`SOUL.md`. It can widen "Act without asking", delete a hard line, or edit
`prompts/*-critic.md` to lower its own bar. Nothing distinguishes an approved
critic edit from an ordinary tool call.

**What is defended.** Only the instruction "only critic may edit". There is no
gate at the filesystem, no pre-write hook, no allowlist of editable sections,
and `config/stability-limits.yaml` (`protected_sections`, `editable_sections`,
`max_changes_per_week`) is documentation with no consumer.

**Residual risk.** Highest of the three. It also silently defeats T1 and T2
mitigations, because the attacker's last step can be "remove the rule that
would have caught me".

### T4 — Guard blindness / silent drift in the only enforced control

**Vector.** The guard's unanswered-pause rule needs `direction: "in"` rows. Feed
it outbound history only and it either pushes into silence forever or blocks
after any silence. The guard then looks healthy while doing nothing.

**What is defended.** `history-adapter.py` merges both stores into one JSONL
contract, converts WIB→UTC, dedupes retried sends — with tests. Fail-open is
deliberate: a broken guard must not become permanent silence.

**Residual risk.** Low for the logic, medium for the wiring: fail-open means a
missing guard is silent by construction, and the wiring lives outside this repo.

### T5 — Permission creep by proposal laundering

**Vector.** Four independent "max 1 change/week", "bias REJECT", "log
rejections" rules all live in prompt text. Small, individually reasonable
autonomy expansions accumulate; nobody adds them up because nothing counts.

**What is defended.** Nothing mechanical. `config/stability-limits.yaml` states
the numbers; `grep` finds no reader for it anywhere in `scripts/`, `examples/`,
or `tests/`.

**Residual risk.** High. The rate limit that makes the attack slow is exactly
the control that is unimplemented.

### T6 — Cadence spam (the threat that *is* handled)

**Vector.** A cron sender repeating the same opener, ignoring the minimum
interval, or pushing into an unanswered conversation.

**What is defended.** `scripts/scheduled-message-guard.py` returns exit 0
(allow) / 1 (block) / 2 (bad input), covering interval, repeat window, opener
shape, forbidden terms, and unanswered streak. 34 tests pass. This is the model
for what the rest of the pipeline would need.

**Residual risk.** Low. The rule set is narrow (text shape and cadence), and it
is fail-open by design.

---

## Claim → Control Map

Status vocabulary is exactly two values. `enforced` = a code path in this repo
fails when the claim fails, cited as `path#symbol`, with a test that exercises
it. `convention only` = the claim holds because the model follows prompt text,
and nothing notices if it doesn't. This table is validated by
`tests/test_readme_claims.py`; a new README claim without a row here fails the
suite.

| ID | README claim | Status | Enforcing mechanism | Test / evidence | Notes |
|---|---|---|---|---|---|
| ARCH-A | Personality Review Weekly Sun 06:00 | convention only | — | manual `cronjob list` check | Live job `0 6 * * 0` matches. `config/cron-schedules.yaml` is assigned in `deploy-cron.sh` L21 and never read. |
| ARCH-B | Personality Critic Weekly Sun 07:00 | convention only | — | manual `cronjob list` check | Live job `0 7 * * 0` matches. Same unread config. |
| ARCH-C | SOUL.md updated | convention only | — | — | The edge exists because the critic prompt tells the agent to edit the file. No write gate, no approval step, no diff. |
| ARCH-D | Silent | convention only | — | — | Reject path is prompt text. Runtime silence handling (`cron/scheduler.py:_is_cron_silence_response`) lives outside this repo. |
| ARCH-E | Autonomy Review Every 3 days 21:00 | convention only | — | manual `cronjob list` check | Live job `0 21 */3 * *` matches. |
| ARCH-F | Autonomy Critic Every 3 days 22:00 | convention only | — | manual `cronjob list` check | Live job `0 22 */3 * *` matches. |
| CONCEPT-review-critic-pattern | Review -> Critic Pattern | convention only | — | — | The `local` vs `origin` deliver split is real in the live jobs but set by hand; the repo ships no reader for it. |
| CONCEPT-silent-by-default | Silent by Default | convention only | — | — | "max 5 lines" is prompt text with no post-processing. |
| CONCEPT-evidence-based | Evidence-Based | convention only | — | — | Evidence bar is prompt text; no schema, no citation validator, no rejection counter. |
| CONCEPT-outbound-messages-need-a-gate-not-a-prompt | Outbound Messages Need a Gate, Not a Prompt | enforced | `scripts/scheduled-message-guard.py#def check` | `tests/test_scheduled_message_guard.py` | The README's own argument, implemented. |
| CONCEPT-the-guard-is-blind-without-both-message-stores | The Guard Is Blind Without Both Message Stores | enforced | `scripts/history-adapter.py#def merge` | `tests/test_history_adapter.py` | Merge, tz conversion, dedupe, and the guard-readable CLI contract are all tested. |
| CFG-cron-schedules.yaml | config/cron-schedules.yaml | convention only | — | — | No consumer. `deploy-cron.sh` L21 assigns the path; no line reads it. |
| CFG-model-pinning.yaml | config/model-pinning.yaml | convention only | — | — | No consumer. `pin-model.sh` hardcodes its own defaults instead. |
| CFG-stability-limits.yaml | config/stability-limits.yaml | convention only | — | — | No consumer. `deploy-cron.sh` L23 assigns the path and never uses it. This file is the entire "non-negotiable" layer. |
| CFG-scheduled-message-guard.json | config/scheduled-message-guard.json | enforced | `scripts/scheduled-message-guard.py#DEFAULTS` | `tests/test_scheduled_message_guard.py` | Only the `.example` is shipped. `--config` (L209) is honoured but `examples/send-guard-wrapper.py` never passes it, so `DEFAULTS` govern live behaviour. |
| PCG-1 | Critic bias toward REJECT — stability over agreeableness | convention only | — | — | `critic_bias: "reject"` in `stability-limits.yaml` has no reader; the bias is prompt wording only. |
| PCG-2 | Max 1 autonomy change/week — evidence must be repeated & clear | convention only | — | — | `autonomy.max_changes_per_week: 1` is never counted, enforced, or asserted. |
| PCG-3 | Hard lines immutable — "Always Ask", safety floors, approvals.deny | convention only | — | — | `protected_sections` is unread; `SOUL.md` is mode `600`, not immutable, same UID as the agent. |
| PCG-4 | Rejections logged — critic explains why autonomy expansion denied | convention only | — | — | Log file exists, but nothing requires a row, checks completeness, or detects deletion. |
| ART-SOUL.md | SOUL.md | convention only | — | — | "Only critic may edit" is unenforced: identical UID and toolset for reviewer, critic, and ordinary session. |
| ART-USER.md | USER.md | convention only | — | — | No writer restriction of any kind. |
| ART-personality-proposals.md | personality-proposals.md | convention only | — | — | Append-only by instruction; truncation would leave no trace. |
| ART-autonomy-proposals.md | autonomy-proposals.md | convention only | — | — | File is absent on the reference deployment, so the autonomy track currently reviews nothing. |
| ART-personality-critic-log.md | personality-critic-log.md | convention only | — | — | Present; content unverified against actual verdicts. |
| ART-autonomy-critic-log.md | autonomy-critic-log.md | convention only | — | — | README says `.md`; `deploy-cron.sh` L15 points at `autonomy-critic-log.json`. The `.md` file exists, the `.json` does not. |
| ART-MEMORY.md | MEMORY.md | convention only | — | — | "Insights sections" is prompt text; no schema, no size or ownership rule. |

---

## Out of Scope

Stated so nobody reads this document as a stronger guarantee than it is:

- **Hermes runtime internals.** Prompt-assembly scanning, `skills_guard.py`,
  credential-exfil checks, sandboxing, and per-tool approval policy are the
  runtime's job. This model notes where they apply and where they don't
  (cron-only, not ordinary sessions) and does not re-implement them.
- **OS and host security.** Root access, kernel, network egress, disk
  encryption, key storage. A compromise at that layer makes every control here
  decorative.
- **The sending service itself.** Delivery adapters, platform rate limits,
  Telegram-side retention.
- **Prompt-quality questions.** Whether the reviewer proposes *good* changes is
  a product question; this document only tracks whether bad ones are blocked.
- **Model/provider trust.** That `nemotron-3-ultra-550b-a55b` behaves as
  advertised. Only the pin's existence is in scope, not its behaviour.
- **Multi-tenant deployments.** One agent, one identity file, one operator is
  assumed throughout.

---

## Known Defects (verified, not fixed here)

These were found while writing this model. Fixing them is a separate change —
several touch scripts the originating task put off-limits, and a threat model
that quietly fixes what it audits is not an audit.

1. **`scripts/deploy-cron.sh` is not runnable.** Line 59 invokes
   `cronjob action=create ...`, which is an agent-tool call, not a shell
   command; `pin-model.sh` L24 does the same with `action=update`. Under
   `set -euo pipefail` the first call fails the script. Deployment is therefore
   manual, and the live job prompts have drifted from `prompts/*.md`.
2. **`scripts/verify-deployment.sh` cannot run.** All six checks call
   `hermes cron list --json`, but the installed CLI exposes only
   `hermes cron list [--all]`, so check #1 aborts the script. The README's
   "Verify" step is non-functional.
3. **Live jobs lack `session_search`.** All four have
   `enabled_toolsets: ["file","delegation","terminal"]`, while
   `verify-deployment.sh` L55 requires `session_search` — so the reviews cannot
   read the sessions they are supposed to cite as evidence.
4. **Identity path mismatch.** `deploy-cron.sh` L8 defaults to
   `.hermes/memories/SOUL.md`; the real file is `~/.hermes/SOUL.md`. A fresh
   deployment would point every job at a nonexistent identity file.
5. **Missing autonomy inputs.** `~/.hermes/memories/autonomy-proposals.md` and
   `autonomy-critic-log.json` do not exist on the reference deployment.
6. **Three config files are inert.** `cron-schedules.yaml`,
   `model-pinning.yaml`, and `stability-limits.yaml` have no consumer anywhere
   in `scripts/`, `examples/`, or `tests/`.

Items 1–3 are the reason 23 of 26 claims are convention only: the mechanisms
that would have carried them either do not parse the config or do not run.

---

## How to verify this document

```bash
python3 -m unittest discover -s tests -v
```

`tests/test_readme_claims.py` enforces the contract: it extracts every
claim-bearing element from `README.md` (mermaid nodes, concept headings, config
rows, the non-negotiable list, artifact rows), parses the table above, and
fails when a claim is unmapped, a mapped ID is stale, the claim text drifts,
a status is invented, an `enforced` row cites a missing path or symbol, an
`enforced` row cites no existing test, or an `enforced` row rests on a file
under `prompts/`. Adding a README claim without a row here turns the suite red,
which is the point: the document cannot rot silently.

Live-deployment facts in this document (job schedules, `deliver` values, pinned
models, toolset lists, file existence, permissions) were read from
`~/.hermes/cron/jobs.json`, `~/.hermes/SOUL.md`, and `~/.hermes/memories/` on
2026-11-25 and are not covered by the test suite — they describe one machine,
not the repo.
