"""Capability tiers. Six names in the schema, four maintained configurations.

Tier definitions are YAML data in ai2/data/tiers/. A tier may declare
`config_from: <tier>` to reuse another tier's configuration (Studio and
Workstation share Creator's until real divergence).
"""

from __future__ import annotations

import importlib.resources
from dataclasses import dataclass, field

import yaml

from .detect import Hardware

REQUIRED_KEYS = {"tier", "label", "requires"}


@dataclass
class Tier:
    id: str
    label: str
    ram_gib: int
    cores: int
    config: dict = field(default_factory=dict)
    config_from: str | None = None


def _tier_dir():
    return importlib.resources.files("ai2").joinpath("data/tiers")


def load_tiers() -> dict[str, Tier]:
    tiers: dict[str, Tier] = {}
    for entry in sorted(_tier_dir().iterdir()):
        if not entry.name.endswith(".yml"):
            continue
        data = yaml.safe_load(entry.read_text())
        missing = REQUIRED_KEYS - set(data)
        if missing:
            raise ValueError(f"tier file {entry.name} missing keys: {sorted(missing)}")
        config = {k: v for k, v in data.items()
                  if k not in ("tier", "label", "requires", "config_from")}
        tiers[data["tier"]] = Tier(
            id=data["tier"],
            label=data["label"],
            ram_gib=int(data["requires"].get("ram_gib", 0)),
            cores=int(data["requires"].get("cores", 1)),
            config=config,
            config_from=data.get("config_from"),
        )
    if not tiers:
        raise ValueError("no tier definitions found")
    return tiers


def resolve_config(tier: Tier, tiers: dict[str, Tier]) -> dict:
    seen = set()
    current = tier
    while current.config_from:
        if current.id in seen:
            raise ValueError(f"config_from cycle at tier {current.id}")
        seen.add(current.id)
        current = tiers[current.config_from]
    return current.config


def assign(hw: Hardware, tiers: dict[str, Tier] | None = None) -> Tier:
    """Pick the highest tier the machine qualifies for.

    Below the lowest tier's floor we still return the lowest tier; AI-2 never
    refuses a machine, it configures the best possible experience and is
    honest about the limits.
    """
    tiers = tiers or load_tiers()
    eligible = [t for t in tiers.values()
                if hw.ram_nominal_gib >= t.ram_gib and hw.logical_cores >= t.cores]
    if eligible:
        return max(eligible, key=lambda t: t.ram_gib)
    return min(tiers.values(), key=lambda t: t.ram_gib)


INSTALLED_TIER_FILE = "/etc/ai2/tier"


def installed_tier_id(path: str = INSTALLED_TIER_FILE) -> str | None:
    """The tier `ai-2 init --apply` recorded on this machine, or None."""
    try:
        with open(path) as fh:
            tid = fh.read().strip()
    except OSError:
        return None
    return tid or None


def runtime_defaults(model_id: str | None = None, tiers: dict[str, Tier] | None = None,
                     tier_id: str | None = None) -> dict:
    """What the applied tier asks of the runtime: {'idle_timeout_s', 'ctx',
    'service'}. Values missing from the tier fall back to the project defaults
    (600 s, 2048, on-demand). Read by `serve` and `chat` so a Tiny machine
    really gets its 300 s / 1024-token configuration."""
    out = {"idle_timeout_s": 600, "ctx": 2048, "service": "on-demand"}
    tier_id = tier_id or installed_tier_id()
    if not tier_id:
        return out
    tiers = tiers or load_tiers()
    tier = tiers.get(tier_id)
    if tier is None:
        return out
    config = resolve_config(tier, tiers)
    rt = config.get("runtime") or {}
    if rt.get("idle_timeout_s"):
        out["idle_timeout_s"] = int(rt["idle_timeout_s"])
    if rt.get("service"):
        out["service"] = rt["service"]
    models = config.get("models") or []
    match = next((m for m in models if m.get("id") == model_id), None) or (models[0] if models else None)
    if match and match.get("ctx"):
        out["ctx"] = int(match["ctx"])
    return out
