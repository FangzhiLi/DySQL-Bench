#!/usr/bin/env bash
# scripts/serve_agent.sh -- Qwen3-32B-AWQ on :8000. THINKING=on|off (default on), MAX_SEQS (default 32)
set -euo pipefail
THINKING="${THINKING:-on}"
MAX_SEQS="${MAX_SEQS:-32}"
if [ "$THINKING" = "on" ]; then KW='{"enable_thinking": true}'; else KW='{"enable_thinking": false}'; fi
docker rm -f dysql-agent 2>/dev/null || true
docker run -d --name dysql-agent --restart unless-stopped \
  --gpus all --ipc host --shm-size 64gb \
  -p 8000:8000 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai:cu130-nightly \
  Qwen/Qwen3-32B-AWQ \
  --served-model-name qwen3-32b-awq \
  --host 0.0.0.0 --port 8000 \
  --quantization awq_marlin \
  --max-model-len 40960 \
  --max-num-seqs "$MAX_SEQS" \
  --gpu-memory-utilization 0.28 \
  --enable-prefix-caching \
  --reasoning-parser qwen3 \
  --default-chat-template-kwargs "$KW"
echo "agent starting with thinking=$THINKING max-num-seqs=$MAX_SEQS; logs: docker logs -f dysql-agent"
