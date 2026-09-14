"""tools/moe-bench.py, the pure parts: the gate, the cache rule, the report.
No downloads, no server."""
import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("moe_bench", HERE.parent / "tools" / "moe-bench.py")
mb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mb)


def test_gate_follows_the_review_rule():
    ref = 0.39
    assert mb.clears_gate({"tg": 0.67, "hybrid": True, "cache_reused": True}, ref) == "yes"
    assert mb.clears_gate({"tg": 0.29, "hybrid": False}, ref).startswith("no (tg 0.29 < reference 0.39")
    assert mb.clears_gate({"tg": 0.67, "hybrid": True, "cache_reused": False}, ref).startswith("no (hybrid")
    assert mb.clears_gate({"tg": 0.67, "hybrid": True, "cache_reused": None}, ref).startswith("no (hybrid")
    assert mb.clears_gate({"tg": 0.67, "hybrid": False}, None).startswith("undetermined")
    assert mb.clears_gate({"hybrid": False}, ref).startswith("undetermined")


def test_cache_rule_reads_turn_counts_and_the_server_line():
    assert mb.cache_reused(600, 20, "") is True                # turn 2 processed only its tail
    assert mb.cache_reused(600, 640, "") is False              # turn 2 re-read everything
    assert mb.cache_reused(600, 20, "forcing full prompt re-processing due to lack of cache data") is False
    assert mb.cache_reused(None, 20, "") is None


def test_report_table_and_errors():
    rows = [{"id": "qwen3-1.7b", "label": "Qwen3 1.7B", "params_b": 1.7, "active_b": None, "hybrid": False, "role": "comparison",
             "file_mib": 1011, "tg": 0.39, "pp": 0.5, "peak_rss_mib": 1900, "cache_reused": None},
            {"id": "granite-4.0-h-tiny", "label": "Granite 4.0 H-Tiny", "params_b": 7.0, "active_b": 1.0,
             "hybrid": True, "role": "candidate", "file_mib": 4035, "tg": 0.67, "pp": 0.9,
             "peak_rss_mib": 4700, "cache_reused": True},
            {"id": "lfm2.5-8b-a1b", "label": "LFM2.5 8B A1B", "params_b": 8.3, "active_b": 1.5,
             "hybrid": True, "role": "candidate", "error": "3000 MiB free, 4917 MiB needed"}]
    text = mb.build_report(rows, "qwen3-1.7b", machine="test box")
    assert text.startswith("# moe-bench report on test box")
    assert "Reference for the gate: qwen3-1.7b (0.39 tok/s)" in text
    assert "| Qwen3 1.7B | 1011 | 1.7 / 1.7 | 0.39 | 0.50 | 1900 | - | - |" in text
    assert "| Granite 4.0 H-Tiny | 4035 | 7.0 / 1.0 | 0.67 | 0.90 | 4700 | yes | yes |" in text
    assert "| LFM2.5 8B A1B | ? | 8.3 / 1.5 | failed | - | - | - | undetermined" in text
    assert "- LFM2.5 8B A1B: 3000 MiB free, 4917 MiB needed" in text
    # no reference measured: the gate is undetermined, the report says so
    text = mb.build_report(rows[1:], "qwen3-1.7b")
    assert "(not measured, gate undetermined)" in text


def test_file_mb_is_the_catalog_convention():
    assert mb.file_mb(4230976352) == 4231
    assert mb.file_mb(1_000_000) == 1
