#!/bin/bash
# 2 extra seeds of c2c4 (both tiers) to confirm the large-tier 42%.
# c=2 to avoid the task2068 docker-run saturation seen at c=4. Resumable.
# Usage: source azure_env.sh && bash seeds_c2c4.sh
set -u
cd "$(dirname "$0")"
REDIS="redis://localhost:6398"
export MSWEA_GLOBAL_COST_LIMIT=20

run() {
  echo "=== $(date '+%m-%d %H:%M') START $1 ==="
  .venv/bin/cooperbench run -n "$1" -a mini_swe_agent_v2 -m "$2" \
    -s flash_amd64 --backend docker -c 2 --eval-concurrency 2 --redis "$REDIS" --setting c2c4
  echo "=== $(date '+%m-%d %H:%M') DONE $1 (exit $?) ==="
}

for s in s2 s3; do
  run "F-mini-c2c4-$s"  azure/gpt-5.4-mini
  run "F-large-c2c4-$s" azure/gpt-5.4
done
echo "=== c2c4 SEEDS COMPLETE ==="
