# Troubleshooting

## Common Issues & Fixes

---

### 1. Model Drift Error
**Error:** `global inference config drifted` or model not found

**Cause:** Cron job not pinned to explicit model+provider; global Hermes config changed.

**Fix:**
```bash
# Pin model on all 4 jobs
./scripts/pin-model.sh "your-model" "your-provider"

# Verify
hermes cron list --json | jq -r '.[] | select(.name | test("Personality|Autonomy")) | "\(.name): \(.model.model) via \(.model.provider)"'
```

**Prevention:** Always pin model+provider on cron creation (deploy script does this).

---

### 2. "Skill Not Found" Warnings
**Warning:** `skill 'xyz' not found` in cron job logs

**Cause:** `skills` array not empty — cron jobs try to load skills that don't exist.

**Fix:** Ensure all 4 jobs have `skills: []` (empty array).

```bash
# Verify
hermes cron list --json | jq -r '.[] | select(.name | test("Personality|Autonomy")) | select(.skills | length > 0) | .name'
```

**Prevention:** Deploy script sets `skills='[]'` automatically.

---

### 3. Silent Failures (No Output, No Error)
**Symptom:** Cron job runs but nothing happens — no proposals, no critic output.

**Causes:**
- Prompt template not rendering (placeholder not replaced)
- Toolset missing (`session_search` required for session search)
- Deliver setting wrong (`local` vs `origin`)

**Debug:**
```bash
# Check job config
hermes cron list --json | jq '.[] | select(.name | test("Personality|Autonomy")) | {name, prompt, deliver, enabled_toolsets}'

# Test-run a job manually
hermes cron run <JOB_ID>
```

**Fix:** Run `./scripts/verify-deployment.sh` — it validates all settings.

---

### 4. Reviews Not Writing Proposals
**Symptom:** Review runs but `personality-proposals.md` / `autonomy-proposals.md` unchanged.

**Causes:**
- Prompt not parameterized correctly (placeholders not replaced)
- File path wrong in prompt
- Agent returned `[SILENT]` but didn't write file

**Debug:**
```bash
# Check proposal file
cat .hermes/memories/personality-proposals.md
cat .hermes/memories/autonomy-proposals.md

# Check recent cron output
hermes cron list --json | jq -r '.[] | select(.name | test("Review")) | .id' | xargs -I {} hermes cron run {} 2>&1 | head -50
```

**Fix:** Ensure prompt has correct file paths and `[SILENT]` is the LAST response.

---

### 5. Critics Not Notifying on Change
**Symptom:** SOUL.md changed but no notification received.

**Causes:**
- Critic `deliver` not set to `origin`
- Critic didn't detect change (prompt logic issue)
- Critic output format wrong (must be short msg, not process details)

**Fix:**
```bash
# Verify critic deliver=origin
hermes cron list --json | jq -r '.[] | select(.name | test("Critic")) | "\(.name): deliver=\(.deliver)"'

# Should output: "Personality Change Critic: deliver=origin"
```

---

### 6. Proposal Files Not Appending
**Symptom:** Proposals overwrite instead of append.

**Cause:** Prompt says "overwrite" or agent truncates file.

**Fix:** Ensure prompt explicitly says "append, don't overwrite" and agent uses append mode.

---

### 7. Cron Job Schedule Drift
**Symptom:** Jobs running at wrong times.

**Cause:** Using `every N days` instead of cron expression for weekly jobs.

**Fix:** Use explicit cron expressions:
```yaml
# Weekly: "0 6 * * 0" (not "every 7 days")
# Every 3 days: "0 21 */3 * *" (works correctly)
```

---

### 8. Permission Denied / File Access Errors
**Symptom:** "Permission denied" writing to `.hermes/memories/`

**Cause:** Cron job running as different user, or file permissions.

**Fix:**
```bash
# Ensure files writable
chmod 644 .hermes/memories/*.md
# Or ensure cron runs as correct user
```

---

### 9. Prompt Too Long / Truncated
**Symptom:** Agent cuts off mid-prompt.

**Cause:** Prompt exceeds context window after parameterization.

**Fix:** 
- Shorten prompts
- Move static context to reference files
- Use `session_search` tool instead of embedding session data

---

### 10. Deployment Script Fails
**Error:** `cronjob: command not found` or auth errors.

**Cause:** Hermes CLI not in PATH, or not authenticated.

**Fix:**
```bash
# Ensure hermes in PATH
export PATH="$PATH:$HOME/.hermes/bin"

# Authenticate
hermes login

# Verify
hermes cron list
```

---

## Debug Commands Reference

```bash
# List all personality/autonomy jobs
hermes cron list | grep -E "(Personality|Autonomy)"

# Full JSON output
hermes cron list --json | jq '.[] | select(.name | test("Personality|Autonomy"))'

# Run job manually (test)
hermes cron run <JOB_ID>

# Check proposal files
cat .hermes/memories/personality-proposals.md
cat .hermes/memories/autonomy-proposals.md

# Check critic logs
cat .hermes/memories/personality-critic-log.md
cat .hermes/memories/autonomy-critic-log.md

# Check MEMORY.md insights
grep -A 5 "Personality Insights\|Autonomy Insights" .hermes/memories/MEMORY.md

# Verify deployment
./scripts/verify-deployment.sh

# Pin model
./scripts/pin-model.sh "model" "provider"
```

---

## Getting Help

If issue persists:
1. Run `./scripts/verify-deployment.sh` — fixes 90% of issues
2. Check Hermes logs: `journalctl -u hermes -f`
3. Test single job manually: `hermes cron run <JOB_ID>`
4. Review prompt parameterization in `scripts/deploy-cron.sh`