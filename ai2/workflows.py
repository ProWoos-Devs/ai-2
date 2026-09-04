"""Workflow profiles: what this computer can be used for, answered honestly.

A profile (ai2/data/profiles/*.yml) REQUESTS capabilities, the assigned tier
GRANTS a subset, and the AI Score's per-capability stars must clear the
profile's MINIMUM. Three verdicts follow from that, never a bare refusal:
usable here, usable through the remote AI (when the profile allows it and
`ai-2 remote` is set up), or too slow on this hardware with the way out
named. `install` is read-only toward the system in this version (decision
2026-09-04): it pulls the models the profile needs and prints the exact
`sudo pacman -S` line for the packages, it does not run it."""

from __future__ import annotations

import importlib.resources
import shutil
import subprocess

import yaml

from .benchmark import STAR_LABELS
from .tiers import assign, load_tiers, resolve_config

GRANT_OK = ("full", "basic")


def load_profiles() -> list[dict]:
    d = importlib.resources.files("ai2").joinpath("data/profiles")
    out = []
    for entry in sorted(d.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".yml"):
            out.append(yaml.safe_load(entry.read_text()))
    return out


def get_profile(name: str, profiles: list[dict] | None = None) -> dict | None:
    return next((p for p in (profiles or load_profiles()) if p["id"] == name), None)


def config_tier_id(hw, tiers=None) -> str:
    """The tier whose configuration applies (Studio/Workstation reuse
    another tier's config; the profile blocks are keyed by that one)."""
    tiers = tiers or load_tiers()
    tier = assign(hw, tiers)
    while tier.config_from:
        tier = tiers[tier.config_from]
    return tier.id


def installed_packages(names: list[str], run=subprocess.run) -> dict[str, bool | None]:
    """{package: installed?}; None when there is no pacman to ask."""
    if not names or shutil.which("pacman") is None:
        return {n: None for n in names}
    out = {}
    for n in names:
        proc = run(["pacman", "-Q", n], capture_output=True, text=True)
        out[n] = proc.returncode == 0
    return out


def evaluate(profile: dict, hw, score: dict | None, recommended: dict | None,
             remote_cfg: dict | None, find_model_file, catalog: list[dict],
             tiers=None, run=subprocess.run) -> dict:
    """Everything `list`, `info`, `status` and `install` print, in one dict."""
    tiers = tiers or load_tiers()
    tier_id = config_tier_id(hw, tiers)
    granted = resolve_config(tiers[tier_id], tiers).get("capabilities") or {}
    stars = (score or {}).get("capabilities") or {}
    block = profile["tiers"].get(tier_id) or {}
    by_id = {m["id"]: m for m in catalog}

    denied = [c for c in profile["requests"] if granted.get(c) not in GRANT_OK]
    short = {c: (stars.get(c, 0), need) for c, need in profile.get("minimum", {}).items()
             if score is not None and stars.get(c, 0) < need}
    models = [by_id[m["id"]] for m in block.get("models", []) if m["id"] in by_id]
    if not models and recommended is not None and not denied:
        models = [recommended]   # the model the AI Score recommends
    model_state = {m["id"]: find_model_file(m["file"]) is not None for m in models}
    packages = list(block.get("packages", []))
    pkg_state = installed_packages(packages, run=run)
    missing_models = [m for m in models if not model_state[m["id"]]]
    missing_pkgs = [p for p, ok in pkg_state.items() if ok is False]

    if denied:
        verdict, why = "unavailable", f"this tier ({tier_id}) does not provide " + ", ".join(STAR_LABELS.get(c, c) for c in denied)
    elif score is None:
        verdict, why = "unknown", "no AI Score yet (ai-2 benchmark)"
    elif short:
        needs = ", ".join(f"{STAR_LABELS.get(c, c)} {have}/{need} stars" for c, (have, need) in short.items())
        if profile.get("remote") and remote_cfg:
            verdict, why = "remote", f"too slow locally ({needs}); uses the remote AI at {remote_cfg['url']}"
        elif profile.get("remote"):
            verdict, why = "slow", f"too slow locally ({needs}); a remote AI would do it: ai-2 remote set <url>"
        else:
            verdict, why = "slow", f"too slow locally ({needs})"
    elif missing_models or missing_pkgs:
        verdict, why = "missing", f"ai-2 workflow install {profile['id']}"
    else:
        verdict, why = "ready", ""
    return {"profile": profile, "tier": tier_id, "verdict": verdict, "why": why,
            "denied": denied, "short": short, "models": models, "model_state": model_state,
            "packages": packages, "pkg_state": pkg_state, "missing_models": missing_models,
            "missing_pkgs": missing_pkgs, "ctx": (block.get("llama_server") or {}).get("ctx")}


VERDICT_WORDS = {"ready": "ready", "missing": "needs setup", "remote": "via remote AI",
                 "slow": "too slow here", "unavailable": "not on this tier", "unknown": "no score yet"}


def render_list(results: list[dict]) -> str:
    lines = ["Workflows (what this computer can be used for):"]
    for r in results:
        p = r["profile"]
        lines.append(f"  {p['id']:<12} {VERDICT_WORDS[r['verdict']]:<16} {p['description']}")
        if r["why"]:
            lines.append(f"  {'':<12} {r['why']}")
    lines.append("Details:  ai-2 workflow info <name>     Set up:  ai-2 workflow install <name>")
    return "\n".join(lines)


def render_info(r: dict) -> str:
    p = r["profile"]
    lines = [f"{p['id']}: {p['description']}", f"  Tier here:   {r['tier']}",
             f"  Needs:       " + ", ".join(f"{STAR_LABELS.get(c, c)} >= {n} star{'s' if n != 1 else ''}"
                                             for c, n in p.get("minimum", {}).items()),
             f"  Verdict:     {VERDICT_WORDS[r['verdict']]}" + (f", {r['why']}" if r["why"] else "")]
    if r["models"]:
        lines.append("  Models:      " + ", ".join(f"{m['label']} ({'present' if r['model_state'][m['id']] else 'to download, ' + str(m['file_mb']) + ' MB'})" for m in r["models"]))
    if r["packages"]:
        def state(pkg):
            ok = r["pkg_state"].get(pkg)
            return "installed" if ok else ("missing" if ok is False else "?")
        lines.append("  Packages:    " + ", ".join(f"{pkg} ({state(pkg)})" for pkg in r["packages"]))
    if r["ctx"]:
        lines.append(f"  Context:     {r['ctx']} tokens on this tier")
    if p.get("remote"):
        lines.append("  Remote:      can use the remote AI when this computer is too slow (ai-2 remote)")
    if p.get("usage"):
        lines.append("  How to use:")
        lines += [f"    {u}" for u in p["usage"]]
    return "\n".join(lines)


def render_status(results: list[dict]) -> str:
    lines = ["Workflows set up on this computer:"]
    for r in results:
        p = r["profile"]
        if r["verdict"] in ("ready", "remote"):
            lines.append(f"  {p['id']:<12} {VERDICT_WORDS[r['verdict']]}")
    if len(lines) == 1:
        lines.append("  none yet;  ai-2 workflow list  shows what this computer can do")
    return "\n".join(lines)


def install_plan(r: dict) -> tuple[list[dict], str | None]:
    """(models to pull, the pacman line to print) for a read-only install."""
    cmd = ("sudo pacman -S --needed " + " ".join(r["missing_pkgs"])) if r["missing_pkgs"] else None
    return list(r["missing_models"]), cmd
