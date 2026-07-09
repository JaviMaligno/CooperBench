#!/bin/bash
# 2 extra seeds of C2 (enforced file ownership), both tiers, to answer
# "why single-run?" for the one enforced condition with signal.
# c=2 (task2068 docker saturation). Resumable. Usage: source azure_env.sh && bash seeds_c2.sh
set -u
cd "$(dirname "$0")"
REDIS="redis://localhost:6398"
export MSWEA_GLOBAL_COST_LIMIT=25
run() {
  echo "=== $(date '+%m-%d %H:%M') START $1 ==="
  .venv/bin/cooperbench run -n "$1" -a mini_swe_agent_v2 -m "$2" \
    -s flash_amd64 --backend docker -c 2 --eval-concurrency 2 --redis "$REDIS" \
    --setting coop --enforce-territory --territory-mode file
  echo "=== $(date '+%m-%d %H:%M') DONE $1 (exit $?) ==="
}
for s in s2 s3; do
  run "F-mini-C2-$s"  azure/gpt-5.4-mini
  run "F-large-C2-$s" azure/gpt-5.4
done
echo "=== C2 SEEDS COMPLETE ==="
