"""AI Score, the Adaptation Engine's honesty check.

RAM-based tiering over-promises: a 4 GB machine with an SSE2-only CPU measured
~2 tok/s (RMM-PC, 2026-08-13), which is Tiny-tier compute in a Light-tier RAM
envelope. So we measure real generation speed with llama-bench and turn it into
a 0-100 AI Score plus per-capability star ratings that gate what we recommend.

The scoring functions here are pure so they can be tested without hardware; the
actual measurement lives in runtime.py.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field


@dataclass
class BenchResult:
    tg_tps: float           # generation tokens/sec (the number that matters most)
    pp_tps: float = 0.0     # prompt-processing tokens/sec
    model: str = ""
    threads: int = 0
    tg_stddev: float = 0.0  # spread over the repetitions (0 = one run or unknown)
    build: str = ""         # llama.cpp build commit, from the JSON output
    cpu_info: str = ""


def parse_llama_bench_json(output: str) -> BenchResult | None:
    """Parse llama-bench -o json: a list of objects, one per test, with
    n_prompt/n_gen, avg_ts, stddev_ts, n_threads, build_commit, cpu_info,
    model_type. Returns None if it is not that."""
    import json
    try:
        rows = json.loads(output)
    except ValueError:
        return None
    if not isinstance(rows, list) or not rows:
        return None
    tg = pp = None
    tg_sd = 0.0
    model = threads = build = cpu = None
    for row in rows:
        if not isinstance(row, dict) or "avg_ts" not in row:
            continue
        if row.get("n_gen", 0) > 0 and row.get("n_prompt", 0) == 0:
            tg = float(row["avg_ts"]); tg_sd = float(row.get("stddev_ts") or 0.0)
        elif row.get("n_prompt", 0) > 0 and row.get("n_gen", 0) == 0:
            pp = float(row["avg_ts"])
        model = model or row.get("model_type", "")
        threads = threads or row.get("n_threads", 0)
        build = build or row.get("build_commit", "")
        cpu = cpu or row.get("cpu_info", "")
    if tg is None:
        return None
    return BenchResult(tg_tps=tg, pp_tps=pp or 0.0, model=model or "", threads=int(threads or 0),
                       tg_stddev=tg_sd, build=build or "", cpu_info=cpu or "")


def feel(tg_tps: float) -> str:
    """Plain words for what a generation speed feels like in a chat."""
    if tg_tps < 2:
        return "patience mode (answers arrive word by word; fine for short questions)"
    if tg_tps < 5:
        return "slow but usable (about reading speed for short answers)"
    if tg_tps < 12:
        return "comfortable for chat"
    return "fluent"


def parse_llama_bench(output: str) -> BenchResult | None:
    """Parse llama-bench's markdown table (-o md). Rows look like:
    | qwen2 1B Q4_K - Medium | 373 MiB | 494 M | CPU | 2 | tg32 | 2.04 ± 0.00 |
    Columns: model, size, params, backend, threads, test, t/s.
    """
    tg = pp = None
    model = ""
    threads = 0
    for line in output.splitlines():
        if "|" not in line or "t/s" in line or "---" in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        test = cells[-2]
        m = re.search(r"[\d.]+", cells[-1])
        if not m:
            continue
        val = float(m.group())
        if test.startswith("tg"):
            tg = val
        elif test.startswith("pp"):
            pp = val
        if len(cells) >= 7:
            model = cells[0]
            try:
                threads = int(cells[-3])
            except ValueError:
                pass
    if tg is None:
        return None
    return BenchResult(tg_tps=tg, pp_tps=pp or 0.0, model=model, threads=threads)


def ai_score(tg_tps: float) -> int:
    """Map generation tok/s to a 0-100 AI Score on a saturating log curve.
    Calibrated so ~2 tok/s (usable but slow) is ~30, 5 is ~48, 10 is ~65,
    20 is ~82, and 40+ saturates at 100.
    """
    if tg_tps <= 0:
        return 0
    score = 100.0 * math.log10(1.0 + tg_tps) / math.log10(1.0 + 40.0)
    return max(0, min(100, round(score)))


def _stars(value: float, thresholds: list[float]) -> int:
    """Count how many ascending thresholds `value` meets (0-5)."""
    return sum(1 for t in thresholds if value >= t)


def capability_stars(tg_tps: float, max_vram_mb: int) -> dict[str, int]:
    """Per-capability 0-5 star ratings. Text capabilities come from measured
    generation speed; image/video need a GPU the text benchmark can't exercise,
    so they are gated on VRAM (honestly 0 on a CPU-only box)."""
    text_general = [1, 2, 4, 8, 15]      # chat/doc_qa/voice
    text_short = [1, 2, 3, 6, 12]        # translation/ocr, shorter outputs
    text_heavy = [2, 4, 8, 15, 30]       # coding, long outputs need speed
    stars = {
        "chat": _stars(tg_tps, text_general),
        "translation": _stars(tg_tps, text_short),
        "ocr": _stars(tg_tps, text_short),
        "doc_qa": _stars(tg_tps, text_general),
        "voice": _stars(tg_tps, text_general),
        "coding": _stars(tg_tps, text_heavy),
    }
    stars["image_generation"] = _stars(max_vram_mb, [2000, 4000, 6000, 8000, 12000])
    stars["video"] = _stars(max_vram_mb, [8000, 10000, 12000, 16000, 24000])
    return stars


def summarize(result: BenchResult, max_vram_mb: int) -> dict:
    import platform
    import time
    score = ai_score(result.tg_tps)
    stars = capability_stars(result.tg_tps, max_vram_mb)
    return {
        "bench_version": 2,
        "ai_score": score,
        "tg_tps": round(result.tg_tps, 2),
        "tg_stddev": round(result.tg_stddev, 3),
        "pp_tps": round(result.pp_tps, 2),
        "feel": feel(result.tg_tps),
        "bench_model": result.model,
        "threads": result.threads,
        "runtime_build": result.build,
        "cpu_info": result.cpu_info,
        "kernel": platform.release(),
        "measured_at": time.strftime("%Y-%m-%d %H:%M"),
        "capabilities": stars,
    }


STAR_LABELS = {"chat": "Chat", "translation": "Translation", "coding": "Programming",
               "ocr": "OCR", "doc_qa": "Document Q&A", "voice": "Voice",
               "image_generation": "Image generation", "video": "Video"}


def bench_params_b(model_path: str, catalog: list) -> float:
    """Best-effort: which catalog model was benchmarked, to scale estimates."""
    import os
    name = os.path.basename(model_path).lower()
    for m in catalog:
        if m.get("file", "").lower() == name:
            return m["params_b"]
    for m in catalog:
        if m["id"].replace("-", "").replace(".", "") in name.replace("-", "").replace(".", ""):
            return m["params_b"]
    return 0.5  # assume the standard 0.5B test model


def measure(hw, model_path: str, runtime_dir: str, threads: int | None = None) -> tuple[dict, dict]:
    """Run llama-bench on model_path with the given runtime and turn the result
    into the AI Score record (what `ai-2 benchmark` prints and persists) plus
    the model recommendation. Raises RuntimeError when the bench fails."""
    from .models import load_catalog, recommend
    from .runtime import run_llama_bench

    threads = threads or max(1, hw.logical_cores)
    out = run_llama_bench(runtime_dir, model_path, threads, variant=hw.cpu_variant)
    result = parse_llama_bench_json(out) or parse_llama_bench(out)
    if result is None:
        raise RuntimeError("could not parse llama-bench output")
    max_vram = max((g.vram_mb or 0 for g in hw.gpus), default=0)
    catalog = load_catalog()
    params_b = bench_params_b(model_path, catalog)
    rec = recommend(hw.ram_mib, result.tg_tps, params_b, catalog)
    data = summarize(result, max_vram) | {
        "cpu_variant": hw.cpu_variant,
        "bench_params_b": params_b,
        "recommended_model": rec["local"]["id"] if rec["local"] else None,
        "remote_suggested": rec["remote_suggested"],
    }
    return data, rec
