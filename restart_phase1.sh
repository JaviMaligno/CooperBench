#!/bin/bash
# Stage 1 (~$35-45 Azure / $0 Modal, 8-12 h): full pool × 3 policies × 2 tiers.
# Resumable; relaunch after interruptions. Usage: source azure_env.sh && bash restart_phase1.sh
set -u
cd "$(dirname "$0")"
export MSWEA_GLOBAL_COST_LIMIT=60
for tier_model in "mini azure/gpt-5.4-mini" "large azure/gpt-5.4"; do
  set -- $tier_model
  for policy in iterate restart-fresh restart-informed; do
    echo "=== $(date '+%m-%d %H:%M') START R-$1-$policy ==="
    .venv/bin/python restart_run.py --run-name "R-$1-$policy" --model "$2" \
      --policy "$policy" --rounds 4 --concurrency 2
    echo "=== $(date '+%m-%d %H:%M') DONE R-$1-$policy ==="
  done
done
echo "=== PHASE 1 COMPLETE ==="
