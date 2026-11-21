# Evidence Standards

## What Counts as Valid Evidence

### Personality Track
| Evidence Type | Weight | Examples |
|---------------|--------|----------|
| Direct user correction | Highest | "habit X needs fixing", "don't say Y", "be more Z" |
| Explicit positive feedback | High | "I like when you...", "that was helpful" |
| Repeated friction pattern | High | User consistently confused/annoyed by same behavior |
| Successful communication pattern | Medium | User responds well to specific style/approach |
| Implicit preference | Medium | User consistently engages more with certain tones |
| Single session anecdote | Low | One-off comment without repetition |

### Autonomy Track (Stricter)
| Evidence Type | Weight | Examples |
|---------------|--------|----------|
| User explicitly treats as routine | Highest | "Why did you ask? Just do it", "You should've known" |
| User surprised/upset by autonomy | Highest | "You should've asked first!", "That wasn't your call" |
| Repeated "just do it" pattern | High | Multiple sessions where user says "just do it" for same action |
| Escalation decision feedback | Medium | "Good call escalating that" / "You should've escalated" |
| Single session anecdote | **Insufficient** | Auto-reject for autonomy changes |

## Evidence Documentation Format

Reviews must cite evidence in proposals:

```
**Evidence:** 
- Session 2024-01-15: User said "habit of over-explaining needs fixing"
- Sessions 2024-01-10, 2024-01-12, 2024-01-14: User said "just do it" for file edits
- Session 2024-01-13: User responded positively to brief replies
```

## Evidence Thresholds

| Track | Threshold | Meaning |
|-------|-----------|---------|
| Personality | `repeated` | Pattern observed across ≥2 sessions |
| Autonomy | `repeated` | Pattern across ≥2 sessions AND explicit user signal |
| Autonomy | `strong` | Direct explicit instruction ("never ask for X again") |

## What Does NOT Count

- "I think maybe..." / vague impressions
- Single session without repetition
- Assumptions about user preferences
- Agent's own interpretation without user signal
- Feedback from third parties
- Hypothetical scenarios

## Critic Evaluation Checklist

For each proposal, critic verifies:

### Personality
- [ ] Cites specific session IDs or dates
- [ ] Pattern repeated across ≥2 sessions
- [ ] Evidence directly supports proposed change
- [ ] Change is small (≤10 lines) and targeted
- [ ] Change is reversible

### Autonomy (Stricter)
- [ ] Cites specific session IDs or dates
- [ ] Pattern repeated across ≥2 sessions
- [ ] **Explicit user signal** (said "just do it" OR "should've asked")
- [ ] Evidence directly supports boundary change
- [ ] Change is small (≤10 lines) and targeted
- [ ] Change is reversible
- [ ] Does NOT weaken protected sections