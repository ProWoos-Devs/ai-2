`ai-2 benchmark` measures what your machine can really do and turns it into the AI Score, a number from 0 to 100 that is comparable across machines. The score, not your RAM, gates which model `ai-2 recommend` steers you to.

## How it is measured

* The benchmark always runs the same fixed workload, the Qwen2.5 0.5B Instruct model (Q4_K_M) under llama.cpp's `llama-bench`, on the engine build matched to your CPU. Scores from different models would not be comparable, so AI-2 refuses to benchmark on a substitute.
* Two repetitions are run and the spread reported. The run is time-boxed per CPU class (150 to 300 seconds), so an old machine is not stuck in a 10-minute benchmark.
* The score records the runtime build, CPU, kernel and date alongside the number, and is persisted per user, so `recommend`, `model pull`, `serve` and `chat` work without sudo afterwards.

## What the number means

The measured generation speed (tokens per second) is mapped to 0-100 on a saturating curve, calibrated so that roughly:

| tok/s | AI Score | Feels like |
|---|---|---|
| 2 | ~30 | usable but slow, patience mode |
| 5 | ~48 | |
| 10 | ~65 | comfortable for chat |
| 20 | ~82 | |
| 40+ | 100 | |

The output says in plain words what the speed feels like, and real measured machines are listed on [[Validated Hardware]].

## Capability stars

Alongside the score, the benchmark rates eight capabilities from 0 to 5 stars. The text capabilities (chat, translation, OCR, document Q&A, voice, coding) are derived from the measured generation speed, with coding demanding the most because long outputs need speed. Image generation and video need a GPU that the text benchmark cannot exercise and an engine that can drive it. The packaged engine is CPU-only, so both are 0 stars on every machine today, whatever VRAM the card has (since ai-2 0.13.4; before that a machine with the NVIDIA driver installed got image stars for a path that does not exist). The VRAM thresholds are kept for the day a GPU engine ships.

## Why not just use RAM?

RAM says what fits, not what runs. The recommendation logic takes both, from the models that fit your RAM (with headroom for the system), it picks the largest whose estimated speed on your measured hardware is still usable. If a larger model fits but would be too slow, or nothing clears the speed floor, AI-2 says so and suggests remote inference for the heavy work instead of pretending. Details on [[Models]].
