AI-2 keeps a curated catalog of local models it knows how to run well. Everything is managed with the `ai-2 model` commands, see [[Commands]].

## The catalog

| Model | Parameters | Download | Peak RAM in use | License |
|---|---|---|---|---|
| Gemma 3 270M Instruct | 0.27B | 242 MB | ~650 MB | Gemma Terms of Use |
| Qwen2.5 0.5B Instruct | 0.5B | 380 MB | ~900 MB | Apache 2.0 |
| Qwen3.5 0.8B (MTP) | 0.8B | 525 MB | ~1.2 GB | Apache 2.0 |
| Gemma 3 1B Instruct | 1.0B | 770 MB | ~1.5 GB | Gemma Terms of Use |
| Qwen3 1.7B | 1.7B | 1.06 GB | ~2 GB | Apache 2.0 |
| SmolLM3 3B | 3.0B | 1.83 GB | ~3.3 GB | Apache 2.0 |
| Qwen2.5 7B Instruct | 7.0B | 4.47 GB | ~6.8 GB | Apache 2.0 |

All models are Q4_K_M GGUF quantizations, downloadable anonymously (no Hugging Face account, no gated license click). The live catalog with checksums is [`ai2/data/models.yml`](https://github.com/ProWoos-Devs/ai-2/blob/main/ai2/data/models.yml); it updates with the `ai-2` package through `sudo pacman -Syu`.

## Embedding models (for your documents, not for chat)

`ai-2 doc` indexes your documents with a text embedding model, a different kind of catalog entry that is never offered for chat. Chosen 2026-09-14 on a Spanish test document (the Constitution, 37 parts, 12 questions, was the right part among the top 3):

| Model | Parameters | Download | Peak RAM while indexing | Spanish test | Used on |
|---|---|---|---|---|---|
| Nomic Embed Text v2 MoE (multilingual) | 0.475B (0.305B active) | 345 MB | ~1.1 GB | 12/12 | Standard and up |
| Nomic Embed Text v1.5 (English) | 0.137B | 85 MB | ~300 MB | 11/12 | Tiny and Light |

Both Apache 2.0, first-party repositories, anonymous downloads. all-MiniLM-L6-v2 (the embedder the tier files used to name) found 4 of 12 and was not cataloged. Speed is the cost: on the 2016 reference laptop (2 cores, SSE4.2 build) either nomic model embeds about 9 tokens a second, so indexing is a "start it and come back" job there; see [[Commands]].

## Downloads you can trust

`ai-2 model pull` resumes interrupted downloads instead of restarting, verifies every file against the catalog's SHA-256 before accepting it, and refuses to start on a full disk. `ai-2 model verify` re-checks everything on disk any time.

## How the recommendation works

`ai-2 recommend` combines two facts about your machine:

1. **What fits.** Models whose measured peak RAM (loading spike and KV cache included, not just file size) fits your RAM with headroom left for the system.
2. **What runs.** Each fitting model's speed is estimated from your measured [[benchmark|AI Score and Benchmarks]], and the recommendation is the largest model that still runs at a usable speed.

If a larger model fits in RAM but would be too slow, or nothing clears the speed floor, AI-2 recommends remote inference for the heavy work instead of pretending, and says why. Local where possible, remote by explicit choice.

The recommendation never blocks you: if you decline its download, `ai-2 chat` and `ai-2 serve` simply use the best model already on disk.

## The starter model

The ISO bundles Gemma 3 270M, so a fresh install chats with no network. AI-2 is plain about what it is, sub-1B models are fluent and fast but unreliable on facts and arithmetic. Once online, the wizard offers a model that genuinely fits your machine.

One measured caveat from the catalog: Qwen3.5 0.8B carries a multi-token-prediction head, but speculative decoding halves its speed on a compute-bound old CPU, so AI-2 does not enable it there.
