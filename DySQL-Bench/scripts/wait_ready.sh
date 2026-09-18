#!/usr/bin/env bash
# scripts/wait_ready.sh [port ...] -- block until every listed vLLM server answers /v1/models with 200 (default: 8000 8001). 30 min timeout.
set -u
PORTS=("$@"); [ ${#PORTS[@]} -eq 0 ] && PORTS=(8000 8001)
for i in $(seq 1 180); do
  ok=1
  for p in "${PORTS[@]}"; do
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$p/v1/models" || true)
    [ "$code" = "200" ] || ok=0
  done
  if [ "$ok" = "1" ]; then echo "ready: ${PORTS[*]}"; exit 0; fi
  sleep 10
done
echo "timeout waiting for ${PORTS[*]}"; exit 1
