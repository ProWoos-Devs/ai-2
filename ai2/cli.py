from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from . import __version__
from .backends import get_package_backend, get_service_backend
from .benchmark import parse_llama_bench, summarize
from .detect import detect
from .runtime import find_runtime, find_test_model, run_llama_bench
from .tiers import assign, load_tiers, resolve_config
from .tuning import apply_plan, build_plan, render_plan

SCORE_PATH = "/etc/ai2/score.json"


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
        pkg_backend = get_package_backend()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    plan = build_plan(hw, tier, config, backend, pkg_backend)
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


def _write_score(data: dict) -> None:
    import os
    try:
        os.makedirs(os.path.dirname(SCORE_PATH), exist_ok=True)
        with open(SCORE_PATH, "w") as fh:
            json.dump(data, fh, indent=2)
    except PermissionError:
        pass  # not root; still print the result, just don't persist


def cmd_benchmark(args) -> int:
    hw = detect()
    runtime_dir = find_runtime(hw.cpu_variant)
    if runtime_dir is None:
        print(f"error: no llama.cpp runtime found for '{hw.cpu_variant}' variant "
              f"(looked in the standard paths). Install the runtime first.", file=sys.stderr)
        return 1
    model = find_test_model()
    if model is None:
        print("error: no .gguf test model found (set AI2_TEST_MODEL or put one in "
              "~/models or /var/lib/ai2/models).", file=sys.stderr)
        return 1
    threads = max(1, hw.logical_cores)
    print(f"Benchmarking with {hw.cpu_variant} runtime, {threads} threads, "
          f"model {model.split('/')[-1]} ... (this can take a minute)")
    try:
        out = run_llama_bench(runtime_dir, model, threads)
    except Exception as exc:
        print(f"error: benchmark failed: {exc}", file=sys.stderr)
        return 1
    result = parse_llama_bench(out)
    if result is None:
        print("error: could not parse llama-bench output", file=sys.stderr)
        return 1
    max_vram = max((g.vram_mb or 0 for g in hw.gpus), default=0)
    data = summarize(result, max_vram, hw.ram_nominal_gib) | {"cpu_variant": hw.cpu_variant}
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(f"\nAI Score   {data['ai_score']} / 100")
        bar = "#" * (data["ai_score"] // 10) + "." * (10 - data["ai_score"] // 10)
        print(f"           [{bar}]  {data['tg_tps']} tok/s generation, "
              f"{data['pp_tps']} tok/s prompt")
        stars = {"chat": "Chat", "translation": "Translation", "coding": "Programming",
                 "ocr": "OCR", "doc_qa": "Document Q&A", "voice": "Voice",
                 "image_generation": "Image generation", "video": "Video"}
        print("\nRecommended for:")
        for key, label in stars.items():
            n = data["capabilities"][key]
            print(f"  {'★' * n}{'☆' * (5 - n)}  {label}")
    _write_score(data)
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

    p_bench = sub.add_parser("benchmark", help="measure real inference speed and compute the AI Score")
    p_bench.add_argument("--json", action="store_true")
    p_bench.set_defaults(func=cmd_benchmark)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
