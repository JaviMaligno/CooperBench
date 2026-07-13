#!/bin/bash
# Stage 0 pilot gate (~$7 Azure / $0 Modal, 1-2 h): 6 features ×
# {iterate, restart-fresh} × strong tier × K=4, then the gate verdict.
set -u
cd "$(dirname "$0")"
export MSWEA_GLOBAL_COST_LIMIT=60
run() {
  echo "=== $(date '+%m-%d %H:%M') START $1 (policy=$2) ==="
  .venv/bin/python restart_run.py --run-name "$1" --model azure/gpt-5.4 \
    --policy "$2" --rounds 4 --limit 6 --concurrency 2
  echo "=== $(date '+%m-%d %H:%M') DONE $1 ==="
}
run R-large-iterate-pilot iterate
run R-large-restart-fresh-pilot restart-fresh
.venv/bin/python restart_metrics.py \
  --runs R-large-iterate-pilot,R-large-restart-fresh-pilot --gate
