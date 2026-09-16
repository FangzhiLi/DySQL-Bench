#!/usr/bin/env bash
# scripts/handover_restart.sh <tag> [conc] -- wait for the running env process to exit, restart both vLLM
# servers sequentially with the new memory split, then resume the full run. No tasks are lost.
set -uo pipefail
TAG="${1:?usage: handover_restart.sh <tag> [conc]}"; CONC="${2:-16}"
cd "$(dirname "$0")/.."
ready() { [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$1/v1/models")" = "200" ]; }
echo "[$(date)] waiting for 'python run.py' to exit"
while pgrep -f "python run.py --env" >/dev/null; do sleep 20; done
echo "[$(date)] env process gone; restarting agent"
docker rm -f dysql-user >/dev/null 2>&1
bash scripts/serve_agent.sh
until ready 8000; do sleep 10; done
echo "[$(date)] agent ready: $(docker logs dysql-agent 2>&1 | grep -oE 'GPU KV cache size: [0-9,]+ tokens' | tail -1)"
bash scripts/serve_user_sim.sh
until ready 8001; do sleep 10; done
echo "[$(date)] user sim ready: $(docker logs dysql-user 2>&1 | grep -oE 'GPU KV cache size: [0-9,]+ tokens' | tail -1)"
free -g | sed -n 2p
echo "[$(date)] resuming full run conc=$CONC"
exec bash scripts/run_full.sh "$TAG" 1 "$CONC"
