#!/usr/bin/env bash
# scripts/run_pilot.sh <tag> [concurrency] [n_short] [n_long] -- pagila, 1 trial
set -euo pipefail
TAG="${1:?usage: run_pilot.sh <tag> [concurrency]}"
CONC="${2:-5}"
NSHORT="${3:-3}"
NLONG="${4:-2}"
cd "$(dirname "$0")/.."
OUT="results/pilot_${TAG}"; mkdir -p "$OUT"
IDS=$(conda run -n dysql python scripts/pick_pilot_tasks.py --env pagila --short "$NSHORT" --long "$NLONG" | tail -1)
echo "pilot task ids: $IDS" | tee "$OUT/task_ids.txt"
START=$(date +%s)
conda run -n dysql --no-capture-output python run.py --env pagila --task-ids $IDS --num-trials 1 \
  --model qwen3-32b-awq --model-api http://127.0.0.1:8000 \
  --user-model qwen2.5-72b-awq --user-model-api http://127.0.0.1:8001 \
  --user-strategy llm --max-concurrency "$CONC" --log-dir "$OUT" 2>&1 | tee "$OUT/pagila.log"
echo "pilot_wall_s $(( $(date +%s) - START ))" | tee "$OUT/wall.txt"
conda run -n dysql python scripts/summarize.py "$OUT/*.json" | tee "$OUT/summary.md"
conda run -n dysql python scripts/estimate_full.py "$OUT" "$CONC" | tee "$OUT/estimate.md"
