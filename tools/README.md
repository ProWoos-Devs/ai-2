# tools

Helpers that are not part of the `ai-2` command. The measurement ones run on an installed AI-2 (or with `PYTHONPATH=.` from this tree) and change nothing on the system.

## sync-pack-catalog.py, before every ai-2 release

The package carries a copy of the community catalog (https://github.com/ProWoos-Devs/ai2-knowledge/blob/main/catalog/community.yml) as `ai2/data/packs.yml`, and a pack installs by name only from that copy, because the package signature is what vouches for the hashes in it. `python3 tools/sync-pack-catalog.py` refreshes the copy from GitHub (or from a working copy given as an argument). Read the diff and commit it, so packs merged since the last release reach `ai-2 knowledge available`. When a pack on the ISO changes, `iso/packs/` has to follow, and `tests/test_iso_profile.py` says so.

## spec-ab.sh

A/B of generation speed without and with self-speculative decoding on Qwen3.5 0.8B (the catalog's `spec_type_measured` note came from it).

## moe-bench.py, the small mixture-of-experts candidates

From the 2026-09-14 review, item 6. Small MoE models (Granite 4.0 H-Tiny, 7B total / 1B active, Apache 2.0; LFM2.5-8B-A1B, 8.3B / 1.5B active, LFM Open License) decode at roughly the speed of a dense model of their active size while carrying 3 to 4B-class quality, in the RAM of the cataloged 7B. Whether that helps a real Standard or Creator machine is a measurement, not an estimate, so the order is measurement first, catalog entry second.

Procedure:

1. Run it on the machine the entry would serve. The reference machine is rafaminu-pc (Standard tier, AI Score 23). Before starting there: stop the REAL8 runit services (`real8-arb-bot`, `real8-arb-status`, `real8-arb-sync`) for the session, agreed with Rafael, and stay clear of the 21:30 backup window, because a 4.8 GiB file on an 8 GB box can swap and the machine executes trades.
2. `python3 tools/moe-bench.py --report ~/moe-report.md` downloads the candidates and the comparison models (qwen3-1.7b and smollm3-3b from the catalog), verifies every SHA-256, runs llama-bench and, for the hybrid models, a two-turn chat that shows whether the second turn reuses the prompt cache. It prints how long to expect (long) and writes a Markdown table.
3. The entry gate: generation speed at least the reference model's (qwen3-1.7b) on that box AND, for a hybrid, the prompt cache reused on turn 2. A hybrid that re-reads the whole conversation every turn stays out until a llama.cpp bump with upstream PR 28302 (2026-09-08), which is a rebuild, ISA check and signing of three packages.
4. Only a candidate that clears the gate gets a catalog entry, and that entry lands together with two new optional fields: `active_params_b` (feeds the speed estimate) and `class_b` (the dense-equivalent quality class, feeds the ranking that `params_b` does today). Never before, a key nothing reads is the `gpu_offload` mistake again. The LFM license (not OSI, commercial use capped at 10 million USD annual revenue) is acceptable in the catalog, Rafael's decision of 2026-09-15.

An avx2-class data point is worth adding (the beneficiaries are avx2 machines; the reference laptop runs the noavx build): run the tool on any AVX2 machine with `--runtime-dir` pointing at the avx2 runtime and set the field to the more conservative calibration.
