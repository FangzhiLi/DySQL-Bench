#!/usr/bin/env bash
# scripts/taskgen_pilot.sh <db_key> [n_trees] [votes] -- run every pipeline step for one database and print the stats.
# Verifier must be up on :8003 (scripts/serve_verifier.sh); GLM key in ../.env.
set -euo pipefail
DB="${1:?usage: taskgen_pilot.sh <source:db> [n_trees] [votes]}"; N="${2:-100}"; VOTES="${3:-${TASKGEN_VERIFY_VOTES:-5}}"
GEN_WORKERS="${GEN_WORKERS:-5}"; VERIFY_WORKERS="${VERIFY_WORKERS:-3}"   # GLM plan allows 5 concurrent requests; Ollama Pro allows 3
P=~/miniconda3/envs/dysql/bin/python
cd "$(dirname "$0")/.."
START=$(date +%s)
$P scripts/taskgen.py trees    --db "$DB" --n "$N" --seed 0
$P scripts/taskgen.py describe --db "$DB"
$P scripts/taskgen.py generate --db "$DB" --workers "$GEN_WORKERS" --retry-errors
$P scripts/taskgen.py check    --db "$DB"
T0=$(date +%s)
$P scripts/taskgen.py verify   --db "$DB" --votes "$VOTES" --workers "$VERIFY_WORKERS"
echo "verify_wall_s $(( $(date +%s) - T0 ))"
$P scripts/taskgen.py dedup    --db "$DB"
$P scripts/taskgen.py convert  --db "$DB"
$P scripts/taskgen.py stats    --db "$DB"
echo "pilot_wall_s $(( $(date +%s) - START ))"
