#!/usr/bin/env bash
# scripts/serve_agent.sh -- start a vLLM agent server. All knobs are env vars; defaults reproduce the Qwen3-32B-AWQ setup.
#   MODEL        HF id                      default Qwen/Qwen3-32B-AWQ
#   SERVED_NAME  --served-model-name        default qwen3-32b-awq   (this string ends up in result file names via run.py --model)
#   PORT         host and container port    default 8000
#   CONTAINER    docker container name      default dysql-agent
#   QUANT        --quantization value       default awq_marlin; QUANT=none for bf16 checkpoints (Qwen3-1.7B / 4B)
#   MAX_LEN      --max-model-len            default 40960
#   MAX_SEQS     --max-num-seqs             default 32
#   GPU_UTIL     --gpu-memory-utilization   default 0.36
#   THINKING     on|off                     default on
#   DRY_RUN=1    print the docker command and exit without touching containers
set -euo pipefail
MODEL="${MODEL:-Qwen/Qwen3-32B-AWQ}"
SERVED_NAME="${SERVED_NAME:-qwen3-32b-awq}"
PORT="${PORT:-8000}"
CONTAINER="${CONTAINER:-dysql-agent}"
QUANT="${QUANT:-awq_marlin}"
MAX_LEN="${MAX_LEN:-40960}"
MAX_SEQS="${MAX_SEQS:-32}"
GPU_UTIL="${GPU_UTIL:-0.36}"
THINKING="${THINKING:-on}"
if [ "$THINKING" = "on" ]; then KW='{"enable_thinking": true}'; else KW='{"enable_thinking": false}'; fi
QARGS=()
if [ "$QUANT" != "none" ]; then QARGS=(--quantization "$QUANT"); fi
CMD=(docker run -d --name "$CONTAINER" --restart unless-stopped
  --gpus all --ipc host --shm-size 64gb
  -p "$PORT:$PORT"
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface"
  vllm/vllm-openai:cu130-nightly
  "$MODEL"
  --served-model-name "$SERVED_NAME"
  --host 0.0.0.0 --port "$PORT"
  "${QARGS[@]}"
  --max-model-len "$MAX_LEN"
  --max-num-seqs "$MAX_SEQS"
  --gpu-memory-utilization "$GPU_UTIL"
  --enable-prefix-caching
  --reasoning-parser qwen3
  --default-chat-template-kwargs "$KW")
if [ "${DRY_RUN:-0}" = "1" ]; then printf '%q ' "${CMD[@]}"; echo; exit 0; fi
docker rm -f "$CONTAINER" 2>/dev/null || true
"${CMD[@]}"
echo "$CONTAINER ($SERVED_NAME) starting on :$PORT thinking=$THINKING max-num-seqs=$MAX_SEQS gpu-util=$GPU_UTIL; logs: docker logs -f $CONTAINER"
