#!/bin/bash
# QA-b (C2b v2 per-hunk) + QA-d (2 extra seeds of headline cells).
# Two lanes (mini / large) run in parallel; runs inside a lane are sequential.
# Resumable: re-running skips completed pairs (no --force).
# Usage: source azure_env.sh && bash qa_batch.sh <mini|large>

set -u
cd "$(dirname "$0")"
TIER="$1"
REDIS="redis://localhost:6398"
export MSWEA_GLOBAL_COST_LIMIT=15

if [ "$TIER" = "mini" ]; then MODEL="azure/gpt-5.4-mini"; else MODEL="azure/gpt-5.4"; fi

run() {
  local name="$1"; shift
  echo "=== $(date '+%H:%M') START $name ==="
  .venv/bin/cooperbench run -n "$name" -a mini_swe_agent_v2 -m "$MODEL" \
    -s flash_amd64 --backend docker -c 4 --eval-concurrency 3 \
    --redis "$REDIS" "$@"
  echo "=== $(date '+%H:%M') DONE $name (exit $?) ==="
}

# QA-b: C2b v2 (per-hunk revert)
run "F-$TIER-C2bv2" --setting coop --enforce-territory --territory-mode line

# QA-d: seeds 2 and 3 of the headline cells
for s in s2 s3; do
  run "F-$TIER-solo-$s" --setting solo
  run "F-$TIER-coop-$s" --setting coop
  run "F-$TIER-seq-$s"  --setting seq
  run "F-$TIER-c4-$s"   --setting c4
done

echo "=== LANE $TIER COMPLETE ==="
