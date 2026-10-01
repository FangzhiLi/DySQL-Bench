#!/usr/bin/env bash
# scripts/taskgen_generate_all.sh [n_trees] -- trees + describe + generate + check for every database that has a
# person_named anchor; verify/dedup/convert run later (scripts/taskgen.py verify --all-dbs). Resumable: rerun as is.
# Log per database in results/<db>/generate_all.log (run from anywhere; paths are relative to taskgen/v1/).
# Needs the GLM key in the repo-root .env.
set -uo pipefail
N="${1:-200}"; GEN_WORKERS="${GEN_WORKERS:-5}"
P=~/miniconda3/envs/dysql/bin/python
cd "$(dirname "$0")/.."
DBS=$($P -c "
import json; d=json.load(open('../common/data/candidate_anchors.json'))
print(' '.join(k for k,v in d.items() if any(a['kind']=='person_named' for a in v['anchors'])))")
START=$(date +%s)
for DB in $DBS; do
  name=${DB#*:}; out=results/$name; mkdir -p "$out"; log=$out/generate_all.log
  echo "== $DB $(date -Is)" | tee -a "$log"
  T0=$(date +%s)
  $P scripts/taskgen.py trees    --db "$DB" --n "$N" --seed 0 >> "$log" 2>&1 || { echo "trees FAILED $DB" | tee -a "$log"; continue; }
  $P scripts/taskgen.py describe --db "$DB" > /dev/null 2>> "$log" || { echo "describe FAILED $DB" | tee -a "$log"; continue; }
  $P scripts/taskgen.py generate --db "$DB" --workers "$GEN_WORKERS" --retry-errors >> "$log" 2>&1 || echo "generate FAILED $DB" | tee -a "$log"
  $P scripts/taskgen.py generate --db "$DB" --workers "$GEN_WORKERS" --retry-errors >> "$log" 2>&1   # second pass for 429 leftovers
  $P scripts/taskgen.py check    --db "$DB" >> "$log" 2>&1 || echo "check FAILED $DB" | tee -a "$log"
  echo "db_wall_s $(( $(date +%s) - T0 ))" | tee -a "$log"
done
echo "all_wall_s $(( $(date +%s) - START ))"
