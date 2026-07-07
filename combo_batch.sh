#!/bin/bash
# Phase combos: run one combo across both tiers on flash_amd64 (19 pairs).
# Resumable (no --force). Redis on 6398 for the coop-based combo (c1c2).
# Usage: source azure_env.sh && bash combo_batch.sh <c3c4|c2c4|c1c2>

set -u
cd "$(dirname "$0")"
COMBO="$1"
REDIS="redis://localhost:6398"
export MSWEA_GLOBAL_COST_LIMIT=20

run() {
  local name="$1"; shift
  echo "=== $(date '+%m-%d %H:%M') START $name ==="
  .venv/bin/cooperbench run -n "$name" -a mini_swe_agent_v2 -m "$1" \
    -s flash_amd64 --backend docker -c 4 --eval-concurrency 3 --redis "$REDIS" "${@:2}"
  echo "=== $(date '+%m-%d %H:%M') DONE $name (exit $?) ==="
}

case "$COMBO" in
  c3c4)
    run "F-mini-c3c4"  azure/gpt-5.4-mini --setting c3c4
    run "F-large-c3c4" azure/gpt-5.4      --setting c3c4
    ;;
  c2c4)
    run "F-mini-c2c4"  azure/gpt-5.4-mini --setting c2c4
    run "F-large-c2c4" azure/gpt-5.4      --setting c2c4
    ;;
  c1c2)
    run "F-mini-c1c2"  azure/gpt-5.4-mini --setting coop --require-handshake --enforce-territory --territory-mode file
    run "F-large-c1c2" azure/gpt-5.4      --setting coop --require-handshake --enforce-territory --territory-mode file
    ;;
  *) echo "unknown combo: $COMBO"; exit 1 ;;
esac
echo "=== COMBO $COMBO COMPLETE ==="
