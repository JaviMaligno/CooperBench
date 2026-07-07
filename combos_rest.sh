#!/bin/bash
# Run the remaining two combos in sequence, after c3c4 finishes.
# Resumable. Usage: source azure_env.sh && bash combos_rest.sh
set -u
cd "$(dirname "$0")"
bash combo_batch.sh c2c4
bash combo_batch.sh c1c2
echo "=== ALL COMBOS COMPLETE ==="
