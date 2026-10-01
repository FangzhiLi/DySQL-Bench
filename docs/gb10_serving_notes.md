# GB10 serving notes (2026-09-16)

Hardware: single NVIDIA GB10, 121 GB unified memory, driver 580 / CUDA 13.0.
Image: `vllm/vllm-openai:cu130-nightly` (image id ffa30d66ff5c, vLLM v0.19.2rc1.dev134). Do not `docker pull` to update.

## What worked

| service | model | quant | gpu-mem-util | max-model-len | KV cache | max concurrency at full ctx |
|---|---|---|---|---|---|---|
| agent :8000 | Qwen/Qwen3-32B-AWQ | awq_marlin (MarlinLinearKernel) | 0.28 | 40960 | 67,008 tokens (16.36 GiB) | 1.64x |
| user sim :8001 | Qwen/Qwen2.5-72B-Instruct-AWQ | awq_marlin | 0.42 | 16384 | 39,264 tokens | 2.40x |

- AWQ Marlin kernels load and run on sm_121 with no flags beyond `--quantization awq_marlin`. FlashAttention 2 backend selected automatically.
- Weight load: 32B took ~107 s (4 shards), 72B ~4.5 min (11 shards). torch.compile + CUDA graph capture adds ~2 min each.
- After both are up and idle: `free -g` shows 95 GB used, 25 GB available. Container RSS is small (1.8 / 2.5 GiB); the model memory is in the unified pool, not attributed to the container.

## Pitfall: start the two containers sequentially

Starting the user sim while the agent was still in memory profiling made the agent's EngineCore fail with
`Available KV cache memory: -30.18 GiB` / `No available memory for the cache blocks`. Docker's `--restart unless-stopped`
brought it back and the second attempt succeeded (16.36 GiB). On unified memory vLLM's profiler measures the whole pool,
so a concurrently loading second model shifts the baseline under it. **Start one container, wait for `/v1/models` = 200, then start the other.**

## API shape differences in this vLLM build

- With `--reasoning-parser qwen3`, thinking comes back under `message.reasoning` (not `reasoning_content`). The agent accepts both.
- Content after a closed think block starts with `\n\n`; `parse_response` strips it.
- `usage` has `prompt_tokens`, `completion_tokens`, `total_tokens`. `finish_reason` is `stop` or `length`.

## Smoke test

```
agent  : "What is 2+2? Answer in one word." -> content 'four', reasoning 152 tok, finish stop
user   : "Say hi in one line."              -> 'Hi there!', 4 completion tokens
```

## 2026-09-18: three-server layout for the 1.7B / 4B parallel baselines

| service | model | quant | gpu-mem-util | max-num-seqs | weights | KV cache |
|---|---|---|---|---|---|---|
| user sim :8001 | Qwen/Qwen2.5-72B-Instruct-AWQ | awq_marlin | **0.50** | 32 | 38.77 GiB | 16.35 GiB = 53,584 tokens |
| agent :8000 | Qwen/Qwen3-1.7B | none (bf16) | 0.10 | 32 | 3.22 GiB | 6.16 GiB = 57,680 tokens |
| agent :8002 | Qwen/Qwen3-4B | none (bf16) | 0.15 | 32 | 7.56 GiB | 9.51 GiB = 69,264 tokens |

Idle after all three up: `free -g` used 95, available 26.

**Pitfall: 0.38 is not enough for the 72B user sim.** The budget is util × 113.3 GiB (121.7 GB); at 0.38 that is 43 GiB and the
weights alone are 38.8 GiB. The first two starts died with `Available KV cache memory: 1.87 / 4.91 GiB` (< 5.0 GiB needed for one
16k request); the third got 5.24 GiB = 17k tokens. It only ever worked at 0.38 before because the profiler baseline happened to
fall right. Use ≥ 0.46 for this model; 0.50 gives 53k tokens.


## Verifier (task generation, 2026-09-29)

- Model `nvidia/Qwen3.8-27B-NVFP4` (21 GB on disk, includes the vision tower), served as `qwen3.8-27b-nvfp4` on :8003 by `taskgen/v1/scripts/serve_verifier.sh`.
- **Needs a newer vLLM than the eval image.** `cu130-nightly` (vLLM 0.19.2rc1, built 2026-04-23) fails with `no module or parameter named 'lm_head.input_scale'`: NVIDIA quantized `lm_head` to NVFP4 and that vLLM cannot load it. The script uses `vllm/vllm-openai:v0.30.0-aarch64` (torch 2.13+cu130, runs on driver 580 / CUDA 13.0). Do not use `v0.30.0-aarch64-cu129`: its torch 2.14 and torchvision 0.28+cu129 do not match, and startup dies with `operator torchvision::nms does not exist`.
- vLLM 0.30 returns thinking under `message.reasoning`, not `reasoning_content` (GLM still uses `reasoning_content`); `taskgen/v1/taskgen_v1/llm.py` reads both.
- GPU_UTIL 0.30 = 36.5 GiB: weights + non-torch 19.4 GiB, activations 2.6 GiB, KV cache 14.5 GiB. Startup about 2.5 minutes.
- Had to stop `dysql-agent-1.7b` first (free memory was about 30 GiB with the 4B agent and the 72B user simulator running). With all three up, host free memory drops to 1–2 GiB; do not start anything else.
- Single request: about 11 tokens/s decode.
- Fallback that also loads on the old image: `Inferact/Qwen3.8-27B-NVFP4` (lm_head left in BF16), already downloaded.
