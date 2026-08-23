"""Score-gated model recommendation, the loop's closing piece.

RAM says what fits; the AI Score says what is fast enough. A 4 GB machine has
room for a 1.5B model, but on the SSE2 A4-3305M that model would run at ~0.6
tok/s (unusable). So we estimate each candidate's speed by scaling the
benchmark's measured tok/s by the parameter ratio (inference is compute-bound,
so tok/s falls roughly inversely with parameter count), and recommend the
largest model that both fits in RAM and clears a usability floor. Anything the
machine could hold but not run fast enough becomes a "use remote" suggestion.
"""

from __future__ import annotations

import importlib.resources

import yaml

# Below this generation speed, local chat is too slow to be pleasant; steer the
# user to remote inference for anything larger. ~2 tok/s is the "usable but
# slow" line proven on RMM-PC, so the floor sits just under it.
USABLE_TG_TPS = 1.5

# RAM we keep free for the OS/desktop rather than the model, in MiB.
RAM_HEADROOM_MIB = 1200


def benchmark_model(catalog: list[dict] | None = None) -> dict:
    """The catalog's fixed benchmark workload (flagged `benchmark: true`). The
    AI Score is always measured on it so scores compare across machines even
    when other models (e.g. one bundled on the ISO) are present."""
    catalog = catalog or load_catalog()
    return next((m for m in catalog if m.get("benchmark")), min(catalog, key=lambda m: m["params_b"]))


def best_present_model(catalog: list[dict], ram_mib: int | None = None,
                       find=None) -> dict | None:
    """The largest catalog model already on disk that fits RAM, for a
    ready-to-chat fallback before there is an AI Score."""
    from .runtime import find_model_file
    find = find or find_model_file
    have = [m for m in catalog if find(m["file"])]
    if ram_mib is not None:
        budget = max(0, ram_mib - RAM_HEADROOM_MIB)
        have = [m for m in have if m["ram_peak_mb"] <= budget] or have
    return max(have, key=lambda m: m["params_b"]) if have else None


def load_catalog() -> list[dict]:
    data = yaml.safe_load(
        importlib.resources.files("ai2").joinpath("data/models.yml").read_text()
    )
    return sorted(data["models"], key=lambda m: m["params_b"])


def estimate_tps(measured_tps: float, measured_params_b: float, candidate_params_b: float) -> float:
    if candidate_params_b <= 0:
        return 0.0
    return measured_tps * (measured_params_b / candidate_params_b)


def recommend(ram_mib: int, measured_tps: float, measured_params_b: float,
              catalog: list[dict] | None = None) -> dict:
    """Return {'local': <model or None>, 'remote_suggested': bool, 'reason': str}."""
    catalog = catalog or load_catalog()
    budget = max(0, ram_mib - RAM_HEADROOM_MIB)
    fits = [m for m in catalog if m["ram_peak_mb"] <= budget]
    if not fits:
        return {"local": None, "remote_suggested": True,
                "reason": f"no catalog model fits {budget} MiB usable RAM; use remote inference"}

    scored = [(m, estimate_tps(measured_tps, measured_params_b, m["params_b"])) for m in fits]
    usable = [(m, tps) for m, tps in scored if tps >= USABLE_TG_TPS]

    if usable:
        best, _ = max(usable, key=lambda mt: mt[0]["params_b"])
        # If a larger model would fit in RAM but is too slow, suggest remote for it.
        larger_but_slow = any(
            m["params_b"] > best["params_b"] for m, tps in scored if tps < USABLE_TG_TPS
        )
        return {"local": best, "remote_suggested": larger_but_slow,
                "reason": f"largest model that fits RAM and runs >= {USABLE_TG_TPS} tok/s"}

    # Nothing clears the speed floor: recommend the smallest (fastest) that fits,
    # and lean on remote.
    best, _ = min(scored, key=lambda mt: mt[0]["params_b"])
    return {"local": best, "remote_suggested": True,
            "reason": f"even the smallest fitting model runs below {USABLE_TG_TPS} tok/s here"}
