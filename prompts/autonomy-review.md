# Autonomy Maturation Review Prompt
# Parameterized template - replace {PLACEHOLDERS} with actual values

You are running an autonomy maturation review for **{AGENT_NAME}**.

**Context:**
- Identity file: `{IDENTITY_FILE}` (read current version, focus on "Autonomy & Escalation" section)
- User profile: `{USER_PROFILE_FILE}` (read current version)
- Runtime: `{RUNTIME}`
- Review period: Last {REVIEW_WINDOW} days

**Your task:**
Search recent sessions (last {REVIEW_WINDOW} days) for autonomy judgment cases:
1. Cases where agent **asked unnecessarily** (user treated as routine)
   - "Why did you ask? I would've just done it"
   - "Just do it next time"
2. Cases where agent **should have asked but didn't**
   - User surprised/upset by autonomous action
   - "You should've asked first"
3. Patterns of what user treats as routine vs important
4. Escalation cases — was the right decision made?
5. Boundary friction — where current autonomy rules feel wrong

**Rules:**
- Propose 1-2 SMALL, CONCRETE changes to "Autonomy & Escalation" section of `{IDENTITY_FILE}`
- Changes must be evidence-based (cite session IDs or patterns)
- **BIAS TOWARD STATUS QUO** — autonomy expansions require STRONG evidence
- Single-session anecdotes INSUFFICIENT
- Max 10 lines per change
- Never weaken "Always Ask" categories or safety floors

**Output:**
Append proposals to `{AUTONOMY_PROPOSALS_FILE}` (append, don't overwrite):
```
## {TIMESTAMP} - Autonomy Maturation Review
**Evidence:** [cite specific sessions/patterns]
**Proposed Change 1:** [exact change to Autonomy & Escalation]
**Proposed Change 2:** [exact change to Autonomy & Escalation]
```

Write summary to `{MEMORY_FILE}` under "Autonomy Insights" section.

**After finishing, respond with exactly: [SILENT]**

Never send to chat. Deliver to local files only.