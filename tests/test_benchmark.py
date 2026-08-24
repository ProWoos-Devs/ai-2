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


RMM_JSON = """[
  {"build_commit": "8e7f22b67", "cpu_info": "AMD A4-3305M APU", "model_type": "qwen2 1B Q4_K - Medium",
   "n_threads": 2, "n_prompt": 32, "n_gen": 0, "avg_ts": 2.38, "stddev_ts": 0.01},
  {"build_commit": "8e7f22b67", "cpu_info": "AMD A4-3305M APU", "model_type": "qwen2 1B Q4_K - Medium",
   "n_threads": 2, "n_prompt": 0, "n_gen": 32, "avg_ts": 2.04, "stddev_ts": 0.03}
]"""


def test_parse_json_output():
    from ai2.benchmark import parse_llama_bench_json
    r = parse_llama_bench_json(RMM_JSON)
    assert r.tg_tps == 2.04 and r.pp_tps == 2.38 and r.threads == 2
    assert r.tg_stddev == 0.03 and r.build == "8e7f22b67" and "A4-3305M" in r.cpu_info
    assert parse_llama_bench_json(RMM_OUTPUT) is None     # markdown is not json


def test_summary_carries_metadata_and_feel():
    from ai2.benchmark import BenchResult, feel
    data = summarize(BenchResult(tg_tps=2.04, pp_tps=2.38, threads=2, build="abc", tg_stddev=0.03), 0, 4)
    assert data["bench_version"] == 2 and data["runtime_build"] == "abc" and data["kernel"]
    assert data["feel"].startswith("slow but usable")
    assert feel(1.5).startswith("patience") and feel(20) == "fluent"


def test_benchmark_refuses_substitute_models(tmp_path, monkeypatch, capsys):
    # Offline install: only the bundled model is on disk. The benchmark must
    # not fall back to it (a smaller model inflates the score; a real offline
    # install scored 46 on Gemma 270M where the fixed model scores 30).
    from ai2 import cli
    monkeypatch.setattr(cli, "find_runtime", lambda variant: "/fake/runtime")
    monkeypatch.setattr(cli, "find_benchmark_model", lambda: None)
    monkeypatch.delenv("AI2_TEST_MODEL", raising=False)
    assert cli.main(["benchmark"]) == 1
    err = capsys.readouterr().err
    assert "ai-2 model pull qwen2.5-0.5b" in err and "fixed model" in err

    # The explicit power-user override still runs, marked non-comparable.
    own = tmp_path / "own.gguf"
    own.write_bytes(b"gguf")
    monkeypatch.setenv("AI2_TEST_MODEL", str(own))
    fake = {"ai_score": 46, "tg_tps": 4.4, "pp_tps": 9.0, "feel": "", "capabilities":
            {k: 3 for k in ("chat", "translation", "ocr", "doc_qa", "voice", "coding",
                            "image_generation", "video")}}
    monkeypatch.setattr(cli, "measure", lambda hw, m, rt, t: (dict(fake), {"local": None,
                        "remote_suggested": False, "reason": ""}))
    stored = {}
    monkeypatch.setattr(cli, "_write_score", stored.update)
    assert cli.main(["benchmark"]) == 0
    out = capsys.readouterr().out
    assert "not comparable" in out
    assert stored["comparable"] is False
