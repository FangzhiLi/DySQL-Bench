#!/usr/bin/env bash
# scripts/run_full.sh <tag> [num_trials] [concurrency]  -- all 13 envs, resumable; run under nohup
# Env knobs: MODEL (served model name, default qwen3-32b-awq), AGENT_PORT (default 8000),
#            ENV_ORDER=forward|reverse (default forward; use reverse for a second concurrent run so eu_soccer is not shared)
# Script-level log: results/full_<tag>/run.log (so two concurrent runs never share a log file).
# Re-running the same command resumes: each env's existing results json is passed via --resume.
set -uo pipefail
TAG="${1:?usage: run_full.sh <tag> [num_trials] [concurrency]}"; TRIALS="${2:-1}"; CONC="${3:-16}"
MODEL="${MODEL:-qwen3-32b-awq}"; AGENT_PORT="${AGENT_PORT:-8000}"; ENV_ORDER="${ENV_ORDER:-forward}"
cd "$(dirname "$0")/.."
OUT="results/full_${TAG}"; mkdir -p "$OUT"
exec >> "$OUT/run.log" 2>&1
# largest DBs first so the long tail lands on small envs; eu_soccer (299 MB) gets lower concurrency
# because reward calculation loads the whole DB into memory per thread
ENVS="eu_soccer retail entertainment bowling pagila law_episode cookbook chinook human_resources retail_world ice_hockey car music"
if [ "$ENV_ORDER" = "reverse" ]; then ENVS=$(echo "$ENVS" | tr ' ' '\n' | tac | tr '\n' ' '); fi
declare -A CONC_OVERRIDE=( [eu_soccer]=8 )
echo "[$(date)] full run tag=$TAG model=$MODEL agent_port=$AGENT_PORT trials=$TRIALS conc=$CONC order=$ENV_ORDER"
for ENV in $ENVS; do
  C="${CONC_OVERRIDE[$ENV]:-$CONC}"
  EXISTING=$(ls "$OUT"/${ENV}-*[0-9].json 2>/dev/null | grep -v '\.config\.json$' | head -1 || true)
  RESUME=""; [ -n "$EXISTING" ] && RESUME="--resume $EXISTING"
  echo "[$(date)] start $ENV conc=$C $RESUME"
  conda run -n dysql --no-capture-output python run.py --env "$ENV" --num-trials "$TRIALS" \
    --model "$MODEL" --model-api "http://127.0.0.1:$AGENT_PORT" \
    --user-model qwen2.5-72b-awq --user-model-api http://127.0.0.1:8001 \
    --user-strategy llm --max-concurrency "$C" --log-dir "$OUT" $RESUME >> "$OUT/${ENV}.log" 2>&1
  echo "[$(date)] done $ENV rc=$?"
done
conda run -n dysql python scripts/summarize.py "$OUT/*.json" > "$OUT/summary.md" 2>/dev/null
echo "[$(date)] ALL DONE"
