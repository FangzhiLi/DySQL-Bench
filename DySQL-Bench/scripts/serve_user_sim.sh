#!/usr/bin/env bash
# scripts/serve_user_sim.sh  -- Qwen2.5-72B-Instruct-AWQ on :8001
set -euo pipefail
docker rm -f dysql-user 2>/dev/null || true
docker run -d --name dysql-user --restart unless-stopped \
  --gpus all --ipc host --shm-size 64gb \
  -p 8001:8001 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai:cu130-nightly \
  Qwen/Qwen2.5-72B-Instruct-AWQ \
  --served-model-name qwen2.5-72b-awq \
  --host 0.0.0.0 --port 8001 \
  --quantization awq_marlin \
  --max-model-len 16384 \
  --max-num-seqs 8 \
  --gpu-memory-utilization 0.42 \
  --enable-prefix-caching
echo "user sim starting; logs: docker logs -f dysql-user"
