# 9. LLM choice on a 6 GB laptop GPU

Date: 2026-10-26
Status: Accepted

## Context

With section expansion (ADR 0008) the context contains 94% of the expected key
phrases, so answer quality is now limited by the model. Hardware: RTX 4050 Laptop
(6 GB VRAM), 16 GB RAM, Ollama with a 4,096-token context.

## Results (golden set v1, prompt m2-v3, section expansion, mean of 3 runs)

| Model | VRAM placement | keyword_recall | keyword_correctness | citation_section_accuracy | p50 | p95 |
|---|---|---|---|---|---|---|
| qwen2.5:3b (q4) | 100% GPU | 0.616 | 0.375 | 0.905 | 3.8 s | 12.6 s |
| qwen2.5:7b (q4) | 18% CPU / 82% GPU | 0.756 | 0.5 | 0.857 | 12.6 s | 49.6 s |
| qwen2.5:7b-instruct-q3_K_M | 100% GPU | 0.594 | 0.25 | 0.875 | 5.3 s | 7-24 s* |

*Run 1 included loading the freshly downloaded model (57 s); later runs ~7 s.

- 7B q4 fixed q001 and q002 (right rule chosen from the right text), but does not fit
  in 6 GB VRAM; the CPU share makes it 3-4x slower.
- 7B q3 fits fully on the GPU, but 3-bit quantization lost the quality gain.

## Decision

- Default `LLM_MODEL=qwen2.5:3b`: best quality per second on this hardware.
- `qwen2.5:7b` (q4) is the quality option where latency does not matter (batch jobs).
- The ceiling is hardware. A GPU with 8 GB+ VRAM or a hosted OpenAI-compatible API
  (already supported via LLM_BASE_URL) would allow 7B+ at full precision.

## Consequences

- q005 fails with all three models (all four key phrases missing), so its cause is
  likely the question or its golden answer, not model size: investigate next.
- Re-run this comparison whenever the hardware, the context budget or the prompt changes.
