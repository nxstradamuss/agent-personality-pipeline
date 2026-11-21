#!/bin/bash
# Deploy all 4 cron jobs for the personality pipeline
# Usage: ./deploy-cron.sh [AGENT_NAME] [IDENTITY_FILE] [USER_PROFILE_FILE] [RUNTIME]

set -euo pipefail

AGENT_NAME="${1:-YourAgent}"
IDENTITY_FILE="${2:-.hermes/memories/SOUL.md}"
USER_PROFILE_FILE="${3:-.hermes/memories/USER.md}"
RUNTIME="${4:-Hermes}"
MEMORY_FILE=".hermes/memories/MEMORY.md"
PERSONALITY_PROPOSALS_FILE=".hermes/memories/personality-proposals.md"
AUTONOMY_PROPOSALS_FILE=".hermes/memories/autonomy-proposals.md"
PERSONALITY_CRITIC_LOG_FILE=".hermes/memories/personality-critic-log.md"
AUTONOMY_CRITIC_LOG_FILE=".hermes/memories/autonomy-critic-log.json"

MODEL="nvidia/nemotron-3-ultra-550b-a55b:free"
PROVIDER="openrouter"

# Read config
CRON_CONFIG="config/cron-schedules.yaml"
MODEL_PINNING="config/model-pinning.yaml"
STABILITY_LIMITS="config/stability-limits.yaml"

echo "Deploying personality pipeline for: $AGENT_NAME"
echo "Identity file: $IDENTITY_FILE"
echo "User profile: $USER_PROFILE_FILE"
echo "Runtime: $RUNTIME"

# Function to deploy a cron job
deploy_cron() {
    local name="$1"
    local schedule="$2"
    local prompt_file="$3"
    local deliver="$4"
    local extra_sed="$5"
    
    echo "Deploying: $name ($schedule)"
    
    # Read prompt and parameterize
    local prompt=$(cat "$prompt_file" | \
        sed "s/{AGENT_NAME}/$AGENT_NAME/g" | \
        sed "s|{IDENTITY_FILE}|$IDENTITY_FILE|g" | \
        sed "s|{USER_PROFILE_FILE}|$USER_PROFILE_FILE|g" | \
        sed "s/{RUNTIME}/$RUNTIME/g" | \
        sed "s|{MEMORY_FILE}|$MEMORY_FILE|g" | \
        sed "s|{PERSONALITY_PROPOSALS_FILE}|$PERSONALITY_PROPOSALS_FILE|g" | \
        sed "s|{AUTONOMY_PROPOSALS_FILE}|$AUTONOMY_PROPOSALS_FILE|g" | \
        sed "s|{PERSONALITY_CRITIC_LOG_FILE}|$PERSONALITY_CRITIC_LOG_FILE|g" | \
        sed "s|{AUTONOMY_CRITIC_LOG_FILE}|$AUTONOMY_CRITIC_LOG_FILE|g" | \
        sed "s/{REVIEW_WINDOW}/7/g" | \
        $extra_sed)
    
    # Escape for JSON
    local prompt_json=$(echo "$prompt" | jq -Rs .)
    local model_json=$(jq -n --arg model "$MODEL" --arg provider "$PROVIDER" '{model: $model, provider: $provider}')
    
    # Create cron job
    cronjob action=create \
        schedule="$schedule" \
        prompt="$prompt_json" \
        name="$name" \
        skills='[]' \
        enabled_toolsets='["file","delegation","terminal","session_search"]' \
        deliver="$deliver" \
        model="$model_json"
    
    if [ $? -eq 0 ]; then
        echo "  ✓ Deployed: $name"
    else
        echo "  ✗ Failed: $name"
        return 1
    fi
}

# Deploy Personality Review (Weekly Sun 06:00)
deploy_cron \
    "Personality Maturation Review" \
    "0 6 * * 0" \
    "prompts/personality-review.md" \
    "local" \
    "sed \"s|{PERSONALITY_PROPOSALS_FILE}|$PERSONALITY_PROPOSALS_FILE|g\""

# Deploy Personality Critic (Weekly Sun 07:00)
deploy_cron \
    "Personality Change Critic" \
    "0 7 * * 0" \
    "prompts/personality-critic.md" \
    "origin" \
    "sed \"s|{PERSONALITY_PROPOSALS_FILE}|$PERSONALITY_PROPOSALS_FILE|g\" | sed \"s|{PERSONALITY_CRITIC_LOG_FILE}|$PERSONALITY_CRITIC_LOG_FILE|g\" | sed \"s/{MAX_CHANGES_PER_WEEK}/2/g\" | sed \"s/{CRITIC_BIAS}/reject/g\" | sed \"s/{EVIDENCE_THRESHOLD}/repeated/g\" | sed \"s/{PROTECTED_SECTIONS_LIST}/- Hard Rules\\n- Autonomy \\& Escalation/g\" | sed \"s/{EDITABLE_SECTIONS_LIST}/- Core Personality\\n- Language Style\\n- How You Talk\\n- Grounded Warmth\\n- Critical Response Rules\\n- Tone Detection \\& Adaptation\\n- Inner State\\n- Self-Reflection/g\""

# Deploy Autonomy Review (Every 3 days 21:00)
deploy_cron \
    "Autonomy Maturation Review" \
    "0 21 */3 * *" \
    "prompts/autonomy-review.md" \
    "local" \
    "sed \"s|{AUTONOMY_PROPOSALS_FILE}|$AUTONOMY_PROPOSALS_FILE|g\""

# Deploy Autonomy Critic (Every 3 days 22:00)
deploy_cron \
    "Autonomy Change Critic" \
    "0 22 */3 * *" \
    "prompts/autonomy-critic.md" \
    "origin" \
    "sed \"s|{AUTONOMY_PROPOSALS_FILE}|$AUTONOMY_PROPOSALS_FILE|g\" | sed \"s|{AUTONOMY_CRITIC_LOG_FILE}|$AUTONOMY_CRITIC_LOG_FILE|g\" | sed \"s/{MAX_CHANGES_PER_WEEK}/1/g\" | sed \"s/{CRITIC_BIAS}/reject/g\" | sed \"s/{EVIDENCE_THRESHOLD}/repeated/g\" | sed \"s/{PROTECTED_SECTIONS_LIST}/- Always Ask\\n- Hard Rules\\n- Critical Response Rules (safety floors)\\n- approvals.deny\\n- protected paths/g\""

echo ""
echo "All 4 cron jobs deployed!"
echo ""
echo "Next steps:"
echo "  1. Verify: ./scripts/verify-deployment.sh"
echo "  2. Model already pinned to: $MODEL via $PROVIDER"
echo "  3. Check logs: hermes cron list | grep -E '(Personality|Autonomy)'"