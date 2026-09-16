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
