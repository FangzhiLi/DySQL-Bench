#!/usr/bin/env bash
# scripts/serve_verifier.sh -- vLLM server for the task-verification model (spec §3). Same image and flags as DySQL-Bench/scripts/serve_agent.sh.
#   MODEL        default nvidia/Qwen3.8-27B-NVFP4      SERVED_NAME default qwen3.8-27b-nvfp4 (must match .env TASKGEN_VERIFY_MODEL)
#   PORT         default 8003                          CONTAINER   default dysql-verifier
#   MAX_LEN      default 32768                         MAX_SEQS    default 32
#   GPU_UTIL     default 0.30 (NVFP4 weights ~15 GB; raise if the profiler refuses)
#   IMAGE        default vllm/vllm-openai:v0.30.0-aarch64 (cu130 build; the eval image cu130-nightly, vLLM 0.19, cannot load
#                NVIDIA's NVFP4 checkpoint: its quantized lm_head needs a newer vLLM)
#   DRY_RUN=1    print the docker command and exit
set -euo pipefail
MODEL="${MODEL:-nvidia/Qwen3.8-27B-NVFP4}"; SERVED_NAME="${SERVED_NAME:-qwen3.8-27b-nvfp4}"
PORT="${PORT:-8003}"; CONTAINER="${CONTAINER:-dysql-verifier}"
IMAGE="${IMAGE:-vllm/vllm-openai:v0.30.0-aarch64}"; MAX_LEN="${MAX_LEN:-32768}"; MAX_SEQS="${MAX_SEQS:-32}"; GPU_UTIL="${GPU_UTIL:-0.30}"
CMD=(docker run -d --name "$CONTAINER" --restart unless-stopped
  --gpus all --ipc host --shm-size 64gb -p "$PORT:$PORT"
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface"
  "$IMAGE" "$MODEL" --served-model-name "$SERVED_NAME"
  --host 0.0.0.0 --port "$PORT" --max-model-len "$MAX_LEN" --max-num-seqs "$MAX_SEQS"
  --gpu-memory-utilization "$GPU_UTIL" --enable-prefix-caching --reasoning-parser qwen3
  --default-chat-template-kwargs '{"enable_thinking": true}')
if [ "${DRY_RUN:-0}" = "1" ]; then printf '%q ' "${CMD[@]}"; echo; exit 0; fi
docker rm -f "$CONTAINER" 2>/dev/null || true
"${CMD[@]}"
echo "$CONTAINER ($SERVED_NAME) starting on :$PORT; wait with: DySQL-Bench/scripts/wait_ready.sh $PORT; logs: docker logs -f $CONTAINER"
