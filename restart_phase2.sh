#!/bin/bash
# Stage 2 (~$15-20 Azure / $0 Modal, 4-6 h): agent-decides × 2 tiers.
set -u
cd "$(dirname "$0")"
export MSWEA_GLOBAL_COST_LIMIT=25
for tier_model in "mini azure/gpt-5.4-mini" "large azure/gpt-5.4"; do
  set -- $tier_model
  echo "=== $(date '+%m-%d %H:%M') START R-$1-agent-decides ==="
  .venv/bin/python restart_run.py --run-name "R-$1-agent-decides" --model "$2" \
    --policy agent-decides --rounds 4 --concurrency 2
  echo "=== $(date '+%m-%d %H:%M') DONE R-$1-agent-decides ==="
done
echo "=== PHASE 2 COMPLETE ==="
