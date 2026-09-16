#!/usr/bin/env bash
# scripts/run_full.sh <tag> [num_trials] [concurrency]  -- all 13 envs, resumable; run under nohup
# Re-running the same command resumes: each env's existing results json is passed via --resume.
set -uo pipefail
TAG="${1:?usage: run_full.sh <tag> [num_trials] [concurrency]}"; TRIALS="${2:-1}"; CONC="${3:-12}"
cd "$(dirname "$0")/.."
OUT="results/full_${TAG}"; mkdir -p "$OUT"
# largest DBs first so the long tail lands on small envs; eu_soccer (299 MB) gets lower concurrency
# because reward calculation loads the whole DB into memory per thread
ENVS="eu_soccer retail entertainment bowling pagila law_episode cookbook chinook human_resources retail_world ice_hockey car music"
declare -A CONC_OVERRIDE=( [eu_soccer]=8 )
echo "[$(date)] full run tag=$TAG trials=$TRIALS conc=$CONC"
for ENV in $ENVS; do
  C="${CONC_OVERRIDE[$ENV]:-$CONC}"
  EXISTING=$(ls "$OUT"/${ENV}-*[0-9].json 2>/dev/null | grep -v '\.config\.json$' | head -1 || true)
  RESUME=""; [ -n "$EXISTING" ] && RESUME="--resume $EXISTING"
  echo "[$(date)] start $ENV conc=$C $RESUME"
  conda run -n dysql --no-capture-output python run.py --env "$ENV" --num-trials "$TRIALS" \
    --model qwen3-32b-awq --model-api http://127.0.0.1:8000 \
    --user-model qwen2.5-72b-awq --user-model-api http://127.0.0.1:8001 \
    --user-strategy llm --max-concurrency "$C" --log-dir "$OUT" $RESUME >> "$OUT/${ENV}.log" 2>&1
  echo "[$(date)] done $ENV rc=$?"
done
conda run -n dysql python scripts/summarize.py "$OUT/*.json" > "$OUT/summary.md" 2>/dev/null
echo "[$(date)] ALL DONE"
