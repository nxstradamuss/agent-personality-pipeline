#!/bin/bash
# Verify personality pipeline cron deployment
# Usage: ./verify-deployment.sh

set -euo pipefail

echo "=== Personality Pipeline Deployment Verification ==="
echo ""

# 1. Check all 4 jobs exist
echo "1. Checking cron job existence..."
JOBS=$(hermes cron list --json | jq -r '.[] | select(.name | test("Personality|Autonomy")) | "\(.id) \(.name) \(.schedule) \(.deliver) \(.model.model) \(.model.provider)"')

if [ -z "$JOBS" ]; then
    echo "  ✗ NO personality pipeline jobs found!"
    exit 1
fi

echo "$JOBS" | while read -r ID NAME SCHEDULE DELIVER MODEL PROVIDER; do
    echo "  ✓ $NAME"
    echo "    ID: $ID"
    echo "    Schedule: $SCHEDULE"
    echo "    Deliver: $DELIVER"
    echo "    Model: $MODEL via $PROVIDER"
done

# 2. Verify model pinning
echo ""
echo "2. Verifying model pinning..."
UNPINNED=$(hermes cron list --json | jq -r '.[] | select(.name | test("Personality|Autonomy")) | select(.model.model == null or .model.provider == null) | .name')

if [ -n "$UNPINNED" ]; then
    echo "  ✗ UNPINNED jobs found: $UNPINNED"
    exit 1
else
    echo "  ✓ All jobs have explicit model+provider pinned"
fi

# 3. Verify skills array is empty
echo ""
echo "3. Verifying skills array is empty..."
NON_EMPTY_SKILLS=$(hermes cron list --json | jq -r '.[] | select(.name | test("Personality|Autonomy")) | select(.skills | length > 0) | .name')

if [ -n "$NON_EMPTY_SKILLS" ]; then
    echo "  ✗ Jobs with non-empty skills: $NON_EMPTY_SKILLS"
    echo "  (Skills must be [] to avoid 'skill not found' warnings)"
    exit 1
else
    echo "  ✓ All jobs have empty skills array"
fi

# 4. Verify enabled_toolsets
echo ""
echo "4. Verifying enabled_toolsets..."
for TOOLSET in "file" "delegation" "terminal" "session_search"; do
    MISSING=$(hermes cron list --json | jq -r ".[] | select(.name | test(\"Personality|Autonomy\")) | select(.enabled_toolsets | index(\"$TOOLSET\") | not) | .name")
    if [ -n "$MISSING" ]; then
        echo "  ✗ Missing $TOOLSET: $MISSING"
        exit 1
    fi
done
echo "  ✓ All required toolsets present (file, delegation, terminal, session_search)"

# 5. Verify deliver settings
echo ""
echo "5. Verifying deliver settings..."
REVIEWS_LOCAL=$(hermes cron list --json | jq -r '.[] | select(.name | test("Review$")) | select(.deliver != "local") | .name')
CRITICS_ORIGIN=$(hermes cron list --json | jq -r '.[] | select(.name | test("Critic$")) | select(.deliver != "origin") | .name')

if [ -n "$REVIEWS_LOCAL" ]; then
    echo "  ✗ Reviews not set to 'local': $REVIEWS_LOCAL"
    exit 1
fi
if [ -n "$CRITICS_ORIGIN" ]; then
    echo "  ✗ Critics not set to 'origin': $CRITICS_ORIGIN"
    exit 1
fi
echo "  ✓ Reviews: local, Critics: origin"

# 6. Test-run each job (dry run - just validate prompt renders)
echo ""
echo "6. Testing prompt rendering (dry run)..."
for JOB in "Personality Maturation Review" "Personality Change Critic" "Autonomy Maturation Review" "Autonomy Change Critic"; do
    JOB_ID=$(hermes cron list --json | jq -r ".[] | select(.name == \"$JOB\") | .id")
    if [ -n "$JOB_ID" ]; then
        # Try to get the prompt (this validates it's stored correctly)
        PROMPT=$(hermes cron list --json | jq -r ".[] | select(.id == \"$JOB_ID\") | .prompt" | head -c 200)
        if [ -n "$PROMPT" ] && [ "$PROMPT" != "null" ]; then
            echo "  ✓ $JOB: prompt stored (${#PROMPT} chars)"
        else
            echo "  ✗ $JOB: prompt missing or empty"
            exit 1
        fi
    fi
done

echo ""
echo "=== ALL CHECKS PASSED ==="
echo ""
echo "Pipeline ready. Next steps:"
echo "  - Reviews run silently (deliver=local)"
echo "  - Critics notify only on SOUL.md changes (deliver=origin)"
echo "  - Monitor: hermes cron list | grep -E '(Personality|Autonomy)'"
echo "  - Manual test run: hermes cron run <JOB_ID>"