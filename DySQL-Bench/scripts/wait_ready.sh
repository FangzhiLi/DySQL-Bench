#!/usr/bin/env bash
# scripts/wait_ready.sh -- block until both servers answer /v1/models (timeout 30 min)
set -u
for i in $(seq 1 180); do
  a=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/v1/models || true)
  u=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8001/v1/models || true)
  if [ "$a" = "200" ] && [ "$u" = "200" ]; then echo "both ready"; exit 0; fi
  sleep 10
done
echo "timeout"; exit 1
