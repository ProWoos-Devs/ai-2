"""The machine profile: everything AI-2 knows about this machine, assembled
from the modules that own each piece (hardware detection, tier assignment,
the persisted AI Score). Read-side only on purpose: storage stays split the
way the permission model demands (/etc/ai2/tier is written by init --apply
as root, score.json falls back to the user's home when the benchmark ran
without root). This module is the one place that puts the pieces together
for consumers: `ai-2 profile`, scripts via --json, a future control center.
The dict is JSON-serializable as returned."""

from __future__ import annotations

from dataclasses import asdict

from . import __version__
from .detect import Hardware, detect
from .state import load_score
from .tiers import assign, installed_tier_id, load_tiers


def machine_profile(hw: Hardware | None = None) -> dict:
    hw = hw or detect()
    tiers = load_tiers()
    score = load_score()
    return {
        "ai2_version": __version__,
        "hardware": asdict(hw) | {"flags": sorted(hw.flags), "cpu_variant": hw.cpu_variant},
        "tier": {
            "assigned": assign(hw, tiers).id,
            "configured": installed_tier_id(),
        },
        "benchmark": score,
        "capabilities": (score or {}).get("capabilities"),
    }
