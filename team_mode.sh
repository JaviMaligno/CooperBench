#!/bin/bash
# Team mode (lead/member roles + shared task list) on flash_amd64 — the
# benchmark's own "structured coordination" setting. 1 seed both tiers first
# (team can deadlock ~46min/task; cost-limit caps spend, resumable lets us
# relaunch). If viable, add seeds. Usage: source azure_env.sh && bash team_mode.sh
set -u
cd "$(dirname "$0")"
REDIS="redis://localhost:6398"
export MSWEA_GLOBAL_COST_LIMIT=25
export COOPERBENCH_EVAL_TIMEOUT=600
run() {
  echo "=== $(date '+%m-%d %H:%M') START $1 ==="
  .venv/bin/cooperbench run -n "$1" -a mini_swe_agent_v2 -m "$2" \
    -s flash_amd64 --backend docker -c 2 --eval-concurrency 2 --redis "$REDIS" --setting team
  echo "=== $(date '+%m-%d %H:%M') DONE $1 (exit $?) ==="
}
run "F-mini-team"  azure/gpt-5.4-mini
run "F-large-team" azure/gpt-5.4
echo "=== TEAM COMPLETE ==="
