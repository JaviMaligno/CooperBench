#!/bin/bash
# Seeds stage: 2 extra seeds of the headline cells (iterate, restart-fresh,
# agent-decides × both tiers). Resumable; c=2; cap 60. 
# Usage: source azure_env.sh && bash restart_seeds.sh
set -u
cd "$(dirname "$0")"
export MSWEA_GLOBAL_COST_LIMIT=60
run() {
  echo "=== $(date '+%m-%d %H:%M') START $1 ==="
  .venv/bin/python restart_run.py --run-name "$1" --model "$2" \
    --policy "$3" --rounds 4 --concurrency 2
  echo "=== $(date '+%m-%d %H:%M') DONE $1 (exit $?) ==="
}
for s in s2 s3; do
  for tier_model in "mini azure/gpt-5.4-mini" "large azure/gpt-5.4"; do
    set -- $tier_model
    for policy in iterate restart-fresh agent-decides; do
      run "R-$1-$policy-$s" "$2" "$policy"
    done
  done
done
echo "=== SEEDS COMPLETE ==="
