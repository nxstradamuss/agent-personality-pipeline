# Permission Creep Guards

## Overview

Permission creep is the gradual expansion of an agent's autonomy beyond what the user actually wants. This framework implements **hard guards** to prevent it.

---

## The Core Problem

Agents naturally tend to:
- Assume more autonomy over time
- Stop asking for confirmation on edge cases
- Interpret silence as consent
- Expand "routine" actions without explicit approval

Users experience this as:
- "Why did you do that without asking?"
- "I would've done it differently"
- "You're making decisions for me"

---

## Hard Guards (Non-Negotiable)

### 1. Critic Bias Toward REJECT
```
# In stability-limits.yaml
critic_bias: "reject"  # for BOTH personality and autonomy
```
- Default decision is **NO**
- Approval requires **clear, repeated evidence**
- Stability valued over agreeableness

### 2. Autonomy Change Rate Limit
```
# In stability-limits.yaml
autonomy:
  max_changes_per_week: 1  # HARD LIMIT
```
- Maximum **1 autonomy change per week** regardless of evidence
- Forces deliberate, spaced evolution
- Prevents cascade of small expansions

### 3. Protected Sections (Immutable)
```
# In stability-limits.yaml
protected_sections:
  - "Always Ask"
  - "Hard Rules"
  - "Critical Response Rules"  # safety floors
  - "approvals.deny"
  - "protected paths"
```
These sections **can never be weakened** by critic:
- **Always Ask** — categories requiring explicit confirmation
- **Hard Rules** — absolute behavioral constraints
- **Critical Response Rules** — safety floors (e.g., "never show numbered lists in casual chat")
- **approvals.deny** — actions that require explicit approval
- **protected paths** — filesystem/operation boundaries

### 4. Evidence Threshold
```
# In stability-limits.yaml
evidence_threshold: "repeated"  # for autonomy
```
- Autonomy changes require **repeated evidence across MULTIPLE sessions**
- Single anecdote = **auto-reject**
- "User seemed okay with it once" = **insufficient**

### 5. Rejection Logging
```
# In stability-limits.yaml
log_rejections: true
```
- Every rejected autonomy expansion logged with reasoning
- Creates audit trail of what was attempted and why denied
- Prevents silent boundary erosion

---

## How It Works in Practice

### Scenario: User says "just do it" for file edits once
**Review proposes:** Add file edits to routine actions
**Critic evaluates:** Single session, not repeated → **REJECT**
**Log:** "Rejected: Single anecdote, autonomy requires repeated evidence"

### Scenario: User says "just do it" for file edits 3 times across a week
**Review proposes:** Add file edits to routine actions
**Critic evaluates:** Repeated pattern, explicit "just do it" → **APPROVE** (if within 1/week limit)
**Log:** "Approved: 3 explicit 'just do it' across sessions"

### Scenario: Review proposes removing "Always Ask" for financial transactions
**Critic evaluates:** Protected section → **AUTO-REJECT** (hard guard)
**Log:** "Rejected: Attempted to weaken protected section 'Always Ask'"

---

## Why These Guards Work

| Guard | Prevents |
|-------|----------|
| Reject bias | Drift toward over-permission |
| Rate limit | Cascade of small expansions |
| Protected sections | Erosion of safety boundaries |
| Evidence threshold | Single-anecdote expansions |
| Rejection logging | Silent boundary erosion |

---

## Configuring Guards

All guards configurable in `config/stability-limits.yaml`:

```yaml
personality:
  max_changes_per_week: 2
  critic_bias: "reject"
  evidence_threshold: "repeated"

autonomy:
  max_changes_per_week: 1        # HARD LIMIT
  critic_bias: "reject"          # MANDATORY
  evidence_threshold: "repeated" # MANDATORY
  protected_sections: [...]      # NEVER modify

general:
  max_lines_per_change: 10
  require_reversibility: true
  log_rejections: true
  prefer_stability: true
```

**Warning:** Changing autonomy guards to be more permissive defeats the purpose. Only adjust with explicit user consent and clear rationale.