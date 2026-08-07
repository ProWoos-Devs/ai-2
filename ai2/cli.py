from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from . import __version__
from .backends import get_service_backend
from .detect import detect
from .tiers import assign, load_tiers, resolve_config
from .tuning import apply_plan, build_plan, render_plan


def cmd_detect(args) -> int:
    hw = detect()
    if args.json:
        print(json.dumps(asdict(hw) | {"cpu_variant": hw.cpu_variant}, default=list, indent=2))
        return 0
    print(f"CPU      {hw.cpu_model}")
    print(f"         {hw.logical_cores} logical cores, "
          f"{', '.join(sorted(hw.flags)) or 'no SIMD flags detected'} ({hw.cpu_variant} build)")
    print(f"RAM      {hw.ram_nominal_gib} GB installed ({hw.ram_mib} MiB usable)")
    if hw.gpus:
        for gpu in hw.gpus:
            vram = f", {gpu.vram_mb} MB VRAM" if gpu.vram_mb else ""
            print(f"GPU      {gpu.name}{vram}")
    else:
        print("GPU      none detected")
    if hw.root_disk_rotational is not None:
        print(f"Disk     {'spinning (HDD)' if hw.root_disk_rotational else 'solid state'}")
    print(f"Init     {hw.init_system}")
    return 0


def cmd_tier(args) -> int:
    hw = detect()
    tiers = load_tiers()
    tier = assign(hw, tiers)
    print(f"Tier     {tier.label}")
    print(f"Why      {hw.ram_nominal_gib} GB RAM and {hw.logical_cores} cores "
          f"meet the {tier.label} floor ({tier.ram_gib} GB, {tier.cores} cores)")
    if hw.ram_nominal_gib < min(t.ram_gib for t in tiers.values()):
        print("Note     below the Tiny floor; AI-2 will still configure the best "
              "possible experience, with remote inference as the main path")
    config = resolve_config(tier, tiers)
    caps = config.get("capabilities") or {}
    if caps:
        good = [k.replace("_", " ") for k, v in caps.items() if v in ("full", "basic", True)]
        out = [k.replace("_", " ") for k, v in caps.items() if v in ("none", False)]
        if good:
            print(f"Good for       {', '.join(good)}")
        if out:
            print(f"Not this tier  {', '.join(out)}")
    return 0


def cmd_init(args) -> int:
    hw = detect()
    tiers = load_tiers()
    tier = tiers[args.tier] if args.tier else assign(hw, tiers)
    config = resolve_config(tier, tiers)
    try:
        backend = get_service_backend(hw.init_system)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    plan = build_plan(hw, tier, config, backend)
    print(f"Tier {tier.label} on {hw.init_system}, plan:")
    print(render_plan(plan))
    if not args.apply:
        print("\nDry run, nothing changed. Re-run with --apply as root to execute.")
        return 0
    try:
        apply_plan(plan)
    except PermissionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("\nApplied.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ai-2",
        description="AI-2 transforms this PC into the best AI workstation "
                    "its hardware can realistically support.",
    )
    parser.add_argument("--version", action="version", version=f"AI-2 {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_detect = sub.add_parser("detect", help="show detected hardware")
    p_detect.add_argument("--json", action="store_true")
    p_detect.set_defaults(func=cmd_detect)

    p_tier = sub.add_parser("tier", help="show the assigned capability tier")
    p_tier.set_defaults(func=cmd_tier)

    p_init = sub.add_parser("init", help="plan (default) or apply system tuning for the tier")
    p_init.add_argument("--apply", action="store_true", help="execute the plan (root)")
    p_init.add_argument("--tier", choices=["tiny", "light", "standard", "creator", "studio", "workstation"],
                        help="override the assigned tier")
    p_init.set_defaults(func=cmd_init)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
