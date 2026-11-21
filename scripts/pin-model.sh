#!/bin/bash
# Pin model + provider on all 4 personality pipeline cron jobs
# Usage: ./pin-model.sh "model-name" "provider-name"

set -euo pipefail

MODEL="${1:-nvidia/nemotron-3-ultra-550b-a55b:free}"
PROVIDER="${2:-openrouter}"

echo "Pinning model: $MODEL via $PROVIDER on all 4 personality pipeline cron jobs..."

# Get job IDs for the 4 personality pipeline jobs
JOB_IDS=$(hermes cron list --json | jq -r '.[] | select(.name | test("Personality|Autonomy")) | .id')

if [ -z "$JOB_IDS" ]; then
    echo "No personality pipeline cron jobs found!"
    exit 1
fi

for JOB_ID in $JOB_IDS; do
    JOB_NAME=$(hermes cron list --json | jq -r ".[] | select(.id == \"$JOB_ID\") | .name")
    echo "Pinning $JOB_NAME ($JOB_ID)..."
    
    cronjob action=update \
        job_id="$JOB_ID" \
        model="{\"model\": \"$MODEL\", \"provider\": \"$PROVIDER\"}"
    
    if [ $? -eq 0 ]; then
        echo "  ✓ $JOB_NAME pinned"
    else
        echo "  ✗ Failed to pin $JOB_NAME"
    fi
done

echo ""
echo "Verification:"
hermes cron list --json | jq -r '.[] | select(.name | test("Personality|Autonomy")) | "\(.name): model=\(.model.model) provider=\(.model.provider)"'