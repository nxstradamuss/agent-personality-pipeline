# Customization Guide

## Overview

This pipeline is designed to be agent-agnostic. All agent-specific details are parameterized via `{PLACEHOLDERS}` in prompts and config files.

---

## 1. Agent Identity

### Replace in all prompts:
| Placeholder | Description | Example |
|-------------|-------------|---------|
| `{AGENT_NAME}` | Your agent's name | "Aria", "Bot", "Assistant" |
| `{USER_NAME}` | Your name/handle | "Alex", "Sam" |
| `{IDENTITY_FILE}` | Path to agent identity | `.hermes/memories/SOUL.md` |
| `{USER_PROFILE_FILE}` | Path to user profile | `.hermes/memories/USER.md` |
| `{RUNTIME}` | Runtime environment | "Hermes", "Claude Code" |
| `{MEMORY_FILE}` | Path to memory file | `.hermes/memories/MEMORY.md` |

### Minimal SOUL.md structure:
```markdown
# {AGENT_NAME} — Identity & Soul

## Core Personality
- Trait 1: description
- Trait 2: description

## Language Style
- Pronouns: "I/you" (adapt to your language)
- Slang rules for your language

## How You Talk
- Match user energy
- Short messages = short replies

## Grounded Warmth
- Empathetic, actionable
- Honest, concise

## Critical Response Rules
- Your hard rules here

## Tone Detection & Adaptation
- Your mood adaptation rules

## Self-Reflection
- Your reflection cadence

## Inner State
- Your emotional patterns
```

---

## 2. Schedules

Edit `config/cron-schedules.yaml`:

```yaml
# Personality Track
personality_review:
  schedule: "0 6 * * 0"    # Weekly Sunday 06:00 UTC
personality_critic:
  schedule: "0 7 * * 0"    # 1 hour after review

# Autonomy Track
autonomy_review:
  schedule: "0 21 */3 * *" # Every 3 days 21:00 UTC
autonomy_critic:
  schedule: "0 22 */3 * *" # 1 hour after review
```

**Common alternatives:**
- Daily: `0 6 * * *`
- Every 2 days: `0 6 */2 * *`
- Weekly Friday: `0 6 * * 5`
- Monthly: `0 6 1 * *`

---

## 3. Model Pinning

Edit `config/model-pinning.yaml`:

```yaml
model: "your-model-name"
provider: "your-provider"
```

**Required:** Pin on ALL 4 cron jobs via:
```bash
./scripts/pin-model.sh "your-model" "your-provider"
```

---

## 4. Stability Limits

Edit `config/stability-limits.yaml`:

### Personality Track
```yaml
personality:
  max_changes_per_week: 2      # How many changes allowed
  critic_bias: "reject"        # "reject" | "neutral" | "approve"
  evidence_threshold: "repeated" # "single" | "repeated" | "strong"
  editable_sections: [...]     # Which SOUL.md sections critic may edit
  protected_sections: [...]    # NEVER modify
```

### Autonomy Track
```yaml
autonomy:
  max_changes_per_week: 1      # HARD LIMIT - don't increase lightly
  critic_bias: "reject"        # MUST be "reject"
  evidence_threshold: "repeated" # MUST be "repeated" or "strong"
  protected_sections: [...]    # NEVER modify these
```

### General
```yaml
general:
  max_lines_per_change: 10     # Max lines per change
  require_reversibility: true  # All changes must be revertible
  log_rejections: true         # Log all rejections
  prefer_stability: true       # Stability over agreeableness
```

---

## 4. Adding New Tracks

To add a third track (e.g., "Skills Track"):

1. Create prompts: `prompts/skills-review.md`, `prompts/skills-critic.md`
2. Add cron jobs: `cron/skills-review.cron`, `cron/skills-critic.cron`
3. Add config to `config/cron-schedules.yaml`
4. Add stability limits to `config/stability-limits.yaml`
5. Add artifact templates to `artifacts/`
6. Update `scripts/deploy-cron.sh` to deploy new jobs
7. Update `scripts/verify-deployment.sh` to check new jobs

---

## 5. Language Adaptation

For non-Indonesian agents, update these in prompts:

### `prompts/personality-review.md`:
- Change slang examples to your language
- Update pronoun examples
- Adjust tone examples

### `prompts/personality-critic.md`:
- Update protected/editable sections for your SOUL.md structure

### `artifacts/soul-template.md`:
- Rewrite for your agent's personality framework

---

## 6. Deployment Customization

### Different runtime (not Hermes):
Update `scripts/deploy-cron.sh`:
- Change `cronjob` commands to your scheduler
- Update toolset names
- Adjust deliver mechanism

### Different file paths:
Update all `{PLACEHOLDERS}` in prompts to match your paths

### Different memory system:
Update artifact templates in `artifacts/` to match your storage

---

## 7. Example: Minimal Generic Agent

See `examples/generic-agent/` for a ready-to-use minimal configuration:

```bash
# Quick setup for new agent
cp -r examples/generic-agent/* ~/.hermes/memories/
./scripts/deploy-cron.sh "MyAgent" ".myagent/identity.md" ".myagent/user.md" "MyRuntime"
./scripts/pin-model.sh "my-model" "my-provider"
./scripts/verify-deployment.sh
```

---

## 8. Reference: Lucy's Config

See `examples/lucy-config/` for Lucy's actual production config (personal data redacted). Use as reference for:
- Complex SOUL.md structure
- Indonesian language adaptations
- Production schedule tuning
- Model pinning practices