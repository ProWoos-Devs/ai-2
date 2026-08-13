from ai2.benchmark import ai_score, capability_stars, parse_llama_bench, summarize

# Real llama-bench output captured on RMM-PC (A4-3305M, baseline/SSE2).
RMM_OUTPUT = """\
| model                          |       size |     params | backend    | threads |            test |                  t/s |
| ------------------------------ | ---------: | ---------: | ---------- | ------: | --------------: | -------------------: |
| qwen2 1B Q4_K - Medium         | 373.71 MiB |   494.03 M | CPU        |       2 |            pp32 |          2.38 ± 0.00 |
| qwen2 1B Q4_K - Medium         | 373.71 MiB |   494.03 M | CPU        |       2 |            tg32 |          2.04 ± 0.00 |
build: 132753b (1)
"""


def test_parse_real_output():
    r = parse_llama_bench(RMM_OUTPUT)
    assert r is not None
    assert r.tg_tps == 2.04
    assert r.pp_tps == 2.38
    assert r.threads == 2
    assert "qwen2" in r.model


def test_parse_garbage_returns_none():
    assert parse_llama_bench("no table here") is None


def test_ai_score_curve():
    assert ai_score(0) == 0
    assert ai_score(2.04) == 30      # the real RMM-PC number -> "usable but slow"
    assert 45 <= ai_score(5) <= 52
    assert 60 <= ai_score(10) <= 70
    assert ai_score(40) == 100
    assert ai_score(1000) == 100     # saturates, never exceeds 100


def test_capability_stars_cpu_only():
    # ~2 tok/s, no GPU: chat usable (2), coding poor (1), image/video zero.
    caps = capability_stars(2.04, max_vram_mb=0, ram_gib=4)
    assert caps["chat"] == 2
    assert caps["coding"] == 1
    assert caps["image_generation"] == 0
    assert caps["video"] == 0


def test_capability_stars_gpu():
    caps = capability_stars(30.0, max_vram_mb=12000, ram_gib=32)
    assert caps["chat"] == 5
    assert caps["image_generation"] >= 4
    assert caps["video"] >= 1


def test_summarize_shape():
    r = parse_llama_bench(RMM_OUTPUT)
    s = summarize(r, max_vram_mb=0, ram_gib=4)
    assert s["ai_score"] == 30
    assert s["tg_tps"] == 2.04
    assert set(s["capabilities"]) >= {"chat", "coding", "image_generation", "video"}
