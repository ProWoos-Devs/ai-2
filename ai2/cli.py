from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

from . import __version__, branding, persona, remote
from .backends import get_package_backend, get_service_backend
from .benchmark import STAR_LABELS, measure
from .detect import detect
from .models import benchmark_model, is_starter, load_catalog, recommend
from . import serverstate
from .runtime import (download_model, download_preflight, find_benchmark_model, find_model_file, find_runtime,
                      installed_models, model_dir, run_llama_bench,
                      runtime_package, sampling_args, serve, serve_preflight, verify_model)
from .state import load_score, write_score
from .tiers import assign, installed_tier_id, load_tiers, resolve_config, runtime_defaults
from .tuning import apply_plan, build_plan, render_plan, revert

SCORE_PATH = "/etc/ai2/score.json"   # system location; see state.py for the user fallback


def cmd_logo(args) -> int:
    print(branding.full())
    return 0


def cmd_detect(args) -> int:
    hw = detect()
    if args.json:
        print(json.dumps(asdict(hw) | {"cpu_variant": hw.cpu_variant}, default=list, indent=2))
        return 0
    print(branding.compact())
    print()
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


def cmd_profile(args) -> int:
    """One view of everything AI-2 knows about this machine."""
    from .profile import machine_profile
    prof = machine_profile()
    if args.json:
        print(json.dumps(prof, indent=2))
        return 0
    hwd = prof["hardware"]
    print(branding.compact())
    print()
    print(f"ai-2     {prof['ai2_version']}")
    print(f"CPU      {hwd['cpu_model']} ({hwd['cpu_variant']} build, {hwd['logical_cores']} cores)")
    print(f"RAM      {hwd['ram_nominal_gib']} GB")
    tier = prof["tier"]
    line = tier["assigned"]
    if tier["configured"] is None:
        line += " (not configured yet; run: sudo ai-2 init --apply)"
    elif tier["configured"] != tier["assigned"]:
        line += f" (configured as {tier['configured']})"
    print(f"Tier     {line}")
    bench = prof["benchmark"]
    if not bench:
        print("AI Score not measured yet; run: ai-2 benchmark")
        return 0
    feel = f" ({bench['feel']})" if bench.get("feel") else ""
    print(f"AI Score {bench.get('ai_score')}/100, {bench.get('tg_tps')} tok/s{feel}")
    caps = prof["capabilities"] or {}
    for key, label in STAR_LABELS.items():
        if key in caps:
            n = caps[key]
            print(f"  {'★' * n}{'☆' * (5 - n)}  {label}")
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
    if args.revert:
        try:
            done = revert(backend)
        except PermissionError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print("\n".join("  " + d for d in done) if done else "  nothing recorded to revert")
        print("Reverted AI-2's tuning (packages stay installed). Reboot to drop zram/earlyoom from memory.")
        return 0
    plan = build_plan(hw, tier, config, backend, pkg_backend)
    print(f"Tier {tier.label} on {hw.init_system}, plan:")
    print(render_plan(plan))
    if not args.apply:
        print("\nDry run, nothing changed. Re-run with --apply as root to execute.")
        return 0
    try:
        apply_plan(plan, backend)
    except (PermissionError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("\nApplied.")
    return 0


def _write_score(data: dict) -> None:
    write_score(data)   # system-wide when root, else per user


def _print_recommendation(rec: dict) -> None:
    local = rec["local"]
    if local:
        print(f"\nRecommended local model: {local['label']} "
              f"({local['params_b']}B {local['quant']})")
    else:
        print("\nNo local model is a good fit for this machine.")
    if rec["remote_suggested"] or not local:
        print("  For anything larger, use remote inference, this machine can hold it "
              "but can't run it fast enough locally.")
        print("  Another computer on your network (ai-2 serve --host 0.0.0.0 --api-key KEY there) "
              "or an API key can run it:\n    ai-2 remote set <url> [--api-key KEY]   then   ai-2 chat --remote")


def cmd_recommend(args) -> int:
    hw = detect()
    score = load_score()
    if score is None:
        print("error: no AI Score yet. Run 'ai-2 benchmark' first.", file=sys.stderr)
        return 1
    catalog = load_catalog()
    params_b = score.get("bench_params_b", 0.5)
    rec = recommend(hw.ram_mib, score.get("tg_tps", 0.0), params_b, catalog)
    print(f"AI Score {score.get('ai_score')} / 100, "
          f"{score.get('tg_tps')} tok/s on a {params_b}B model, {hw.ram_nominal_gib} GB RAM")
    print(f"Reason   {rec['reason']}")
    _print_recommendation(rec)
    return 0


def cmd_benchmark(args) -> int:
    hw = detect()
    runtime_dir = find_runtime(hw.cpu_variant)
    if runtime_dir is None:
        print(f"error: no llama.cpp runtime found for '{hw.cpu_variant}' variant "
              f"(looked in the standard paths). Install the runtime first.", file=sys.stderr)
        return 1
    model = find_benchmark_model()
    comparable = True
    if model is None:
        env_model = os.environ.get("AI2_TEST_MODEL")
        if env_model and os.path.isfile(env_model):
            # A power user's own workload. Allowed, but the result is marked so
            # it is never mistaken for a comparable AI Score.
            model = env_model
            comparable = False
        else:
            bench = benchmark_model(load_catalog())
            # Benchmarking whatever gguf happens to be on disk (e.g. the model
            # bundled on the ISO) inflates the score: a smaller model runs
            # faster on the same machine. Found on an offline install 2026-08-24
            # (bundled Gemma 270M scored 46 where the fixed model scores 30).
            print(f"error: the AI Score is measured on one fixed model so scores compare "
                  f"across machines, and that model ({bench['label']}, {bench['file_mb']} MB) "
                  f"is not on this computer.\nOnce online, run:  ai-2 model pull {bench['id']}  "
                  f"and then  ai-2 benchmark", file=sys.stderr)
            return 1
    threads = max(1, hw.logical_cores)
    print(f"Benchmarking with {hw.cpu_variant} runtime, {threads} threads, "
          f"model {model.split('/')[-1]} ... (this can take a minute)")
    try:
        data, rec = measure(hw, model, runtime_dir, threads)
    except Exception as exc:
        print(f"error: benchmark failed: {exc}", file=sys.stderr)
        return 1
    data["comparable"] = comparable
    if not comparable:
        print("note: measured on your own model (AI2_TEST_MODEL), not the fixed benchmark "
              "model. This score and the stars are not comparable with other machines; "
              "it is stored marked as such.")
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(f"\nAI Score   {data['ai_score']} / 100")
        bar = "#" * (data["ai_score"] // 10) + "." * (10 - data["ai_score"] // 10)
        print(f"           [{bar}]  {data['tg_tps']} tok/s generation, "
              f"{data['pp_tps']} tok/s prompt")
        print(f"           {data.get('feel', '')}")
        print("\nRecommended for:")
        for key, label in STAR_LABELS.items():
            n = data["capabilities"][key]
            print(f"  {'★' * n}{'☆' * (5 - n)}  {label}")
        _print_recommendation(rec)
    _write_score(data)
    return 0


def _load_score() -> dict | None:
    return load_score()


def _recommended_model(hw) -> dict | None:
    """The catalog entry the stored AI Score points at, or None."""
    score = _load_score()
    if not score:
        return None
    catalog = load_catalog()
    rec = recommend(hw.ram_mib, score.get("tg_tps", 0.0), score.get("bench_params_b", 0.5), catalog)
    return rec["local"]


def _usable_model(hw) -> dict | None:
    """A model to serve/chat with: the one the AI Score recommends when its
    file is actually on disk, else the best model already present (e.g. one
    bundled on the ISO). The recommendation alone is not enough: a user who
    declines the recommended download must still be able to chat with what is
    installed (hit on the 20260826 ISO verify: recommend said Qwen3 1.7B,
    only Qwen2.5 0.5B was on disk, chat refused with "not set up")."""
    from .models import best_present_model
    rec = _recommended_model(hw)
    if rec is not None and find_model_file(rec["file"]) is not None:
        return rec
    return best_present_model(load_catalog(), hw.ram_mib)


def _catalog_entry(model_id: str) -> dict | None:
    return next((m for m in load_catalog() if m["id"] == model_id), None)


PICK_MODEL = "?"   # `--model` given with no value: ask interactively


def _pick_model(hw) -> dict | None:
    """Numbered menu of the catalog models on disk; Enter takes the default
    (the one serve/chat would use anyway). Numbers rather than arrow keys so
    it works in any terminal, over SSH and with a screen reader."""
    have = [m for m in installed_models(load_catalog()) if m["id"]]
    if not have:
        print("error: no catalog model on this computer. Run 'ai-2 wizard' or 'ai-2 model pull'.",
              file=sys.stderr)
        return None
    if not sys.stdin.isatty():
        print("error: --model without a value needs a terminal to choose from; name one: "
              "--model " + " | ".join(m["id"] for m in have), file=sys.stderr)
        return None
    default = _usable_model(hw)
    rec = _recommended_model(hw)
    running = serverstate.read_server()
    default_n = next((i for i, m in enumerate(have, 1) if default and m["id"] == default["id"]), 1)
    print("Models on this computer:")
    for i, m in enumerate(have, 1):
        marks = []
        if rec and m["id"] == rec["id"]:
            marks.append("recommended")
        if running and os.path.realpath(running.get("model_path", "")) == os.path.realpath(m["path"]):
            marks.append("loaded")
        print(f"  {i}) {m['label']}  ({m['id']}, {m['size_mb']} MB)"
              + (f"  [{', '.join(marks)}]" if marks else ""))
    while True:
        try:
            answer = input(f"Choose 1-{len(have)} [{default_n}]: ").strip()
        except EOFError:
            print()
            return None
        if not answer:
            return have[default_n - 1]["catalog"]
        if answer.isdigit() and 1 <= int(answer) <= len(have):
            return have[int(answer) - 1]["catalog"]
        by_id = next((m for m in have if m["id"] == answer), None)
        if by_id:
            return by_id["catalog"]
        print(f"  not a choice: {answer}")


def cmd_runtime_install(args) -> int:
    hw = detect()
    pkg = runtime_package(hw.cpu_variant)
    if pkg is None:
        print(f"error: no runtime package for CPU variant '{hw.cpu_variant}'", file=sys.stderr)
        return 1
    try:
        pkg_backend = get_package_backend()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if pkg_backend.is_installed(pkg):
        print(f"{pkg} already installed (runtime at {find_runtime(hw.cpu_variant)})")
        return 0
    cmd = pkg_backend.install_cmd([pkg])
    print(f"CPU variant {hw.cpu_variant}, installing {pkg}: {' '.join(cmd)}")
    if not args.apply:
        print("Dry run. Re-run with --apply as root to install.")
        return 0
    import subprocess
    try:
        subprocess.run(cmd, check=True)
    except (subprocess.CalledProcessError, PermissionError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Installed. Runtime at {find_runtime(hw.cpu_variant)}")
    return 0


def cmd_model_pull(args) -> int:
    hw = detect()
    if args.model:
        model = _catalog_entry(args.model)
        if model is None:
            print(f"error: '{args.model}' is not in the catalog "
                  f"(ids: {', '.join(m['id'] for m in load_catalog())})", file=sys.stderr)
            return 1
    else:
        model = _recommended_model(hw)
        if model is None:
            print("error: no recommendation yet. Run 'ai-2 benchmark' first, or name a "
                  "model: ai-2 model pull <id>", file=sys.stderr)
            return 1
    return _pull_model(model, force=args.force)


def _pull_model(model: dict, force: bool = False) -> int:
    existing = find_model_file(model["file"])
    if existing:
        print(f"{model['label']} already present at {existing}")
        return 0
    dest = model_dir()
    problem = download_preflight(model, dest)
    if problem and not force:
        print(f"error: {problem}. Free some space, or pass --force to try anyway.", file=sys.stderr)
        return 1
    print(f"Downloading {model['label']} ({model['file_mb']} MB) to {dest}/ ...")

    def progress(done, total):
        pct = f"{done * 100 // total:3d}%" if total else ""
        print(f"\r  {done // (1 << 20):5d} MB {pct}", end="", flush=True)

    try:
        path = download_model(model, dest, progress=progress)
    except Exception as exc:
        print(f"\nerror: download failed: {exc}", file=sys.stderr)
        return 1
    print(f"\nSaved {path}")
    return 0


def cmd_model_list(args) -> int:
    hw = detect()
    catalog = load_catalog()
    rec = _recommended_model(hw)
    have = installed_models(catalog)
    running = serverstate.read_server()
    if args.json:
        print(json.dumps([{k: v for k, v in m.items() if k != "catalog"} for m in have], indent=2))
        return 0
    print(f"Models on this computer (download dir {model_dir()}):")
    if not have:
        print("  none yet; run: ai-2 model pull")
    for m in have:
        marks = []
        if rec and m["id"] == rec["id"]:
            marks.append("recommended")
        if running and os.path.realpath(running.get("model_path", "")) == os.path.realpath(m["path"]):
            marks.append("loaded")
        print(f"  {m['id'] or '(not in catalog)':<16} {m['size_mb']:>6} MB  {m['path']}"
              + (f"  [{', '.join(marks)}]" if marks else ""))
    others = [m for m in catalog if not any(h["id"] == m["id"] for h in have)]
    if others:
        print("Available to download (ai-2 model pull <id>):")
        for m in others:
            print(f"  {m['id']:<16} {m['file_mb']:>6} MB  {m['label']}"
                  + ("  [recommended]" if rec and m["id"] == rec["id"] else ""))
    return 0


def cmd_model_rm(args) -> int:
    model = _catalog_entry(args.model)
    if model is None:
        print(f"error: '{args.model}' is not in the catalog", file=sys.stderr)
        return 1
    path = find_model_file(model["file"])
    if path is None:
        print(f"{model['label']} is not on this computer.")
        return 0
    running = serverstate.read_server()
    if running and os.path.realpath(running.get("model_path", "")) == os.path.realpath(path):
        print("error: the AI server is using this model; run: ai-2 stop", file=sys.stderr)
        return 1
    if not os.access(os.path.dirname(path), os.W_OK):
        print(f"error: no permission to delete {path} (try with sudo)", file=sys.stderr)
        return 1
    size = os.path.getsize(path) // (1024 * 1024)
    os.remove(path)
    print(f"Removed {path} ({size} MB freed). Download again any time: ai-2 model pull {model['id']}")
    return 0


def cmd_model_verify(args) -> int:
    catalog = load_catalog()
    targets = [m for m in catalog if not args.model or m["id"] == args.model]
    if args.model and not targets:
        print(f"error: '{args.model}' is not in the catalog", file=sys.stderr)
        return 1
    rc = 0
    checked = 0
    for m in targets:
        path = find_model_file(m["file"])
        if not path:
            continue
        checked += 1
        if not m.get("sha256"):
            print(f"  ?     {m['id']}  (no checksum in the catalog)")
            continue
        ok = verify_model(path, m["sha256"])
        print(f"  {'ok  ' if ok else 'BAD '}  {m['id']}  {path}")
        if not ok:
            rc = 2
            print(f"        checksum mismatch; delete and download again: ai-2 model rm {m['id']} && ai-2 model pull {m['id']}")
    if not checked:
        print("No catalog model on this computer.")
    return rc


def cmd_serve(args) -> int:
    hw = detect()
    runtime_dir = find_runtime(hw.cpu_variant)
    if runtime_dir is None:
        print(f"error: no llama.cpp runtime for '{hw.cpu_variant}'. Run 'ai-2 runtime install'.",
              file=sys.stderr)
        return 1
    if args.model == PICK_MODEL:
        model = _pick_model(hw)
        if model is None:
            return 1
        args.model = model["id"]
    elif args.model:
        model = _catalog_entry(args.model)
        if model is None:
            print(f"error: '{args.model}' is not in the catalog", file=sys.stderr)
            return 1
    else:
        model = _usable_model(hw)
        if model is None:
            print("error: no model on this computer yet. Run 'ai-2 wizard', or name one: "
                  "ai-2 serve --model <id>", file=sys.stderr)
            return 1
    path = find_model_file(model["file"])
    if path is None:
        print(f"error: {model['file']} not downloaded. Run 'ai-2 model pull {model['id']}'.",
              file=sys.stderr)
        return 1
    threads = max(1, hw.logical_cores)
    defaults = runtime_defaults(model["id"])
    idle_arg = defaults["idle_timeout_s"] if args.idle_timeout is None else args.idle_timeout
    idle = None if idle_arg == 0 else idle_arg
    ctx = args.ctx or defaults["ctx"]
    api_key = args.api_key or os.environ.get("AI2_API_KEY")
    if args.host not in ("127.0.0.1", "localhost", "::1") and not api_key and not args.insecure:
        print(f"error: binding to {args.host} exposes the AI to the network. Give it "
              "--api-key KEY (or AI2_API_KEY) so other devices must authenticate, or "
              "pass --insecure if this network is trusted.", file=sys.stderr)
        return 1
    if running := serverstate.read_server():
        print(f"error: a server is already running (pid {running['pid']}, model "
              f"{running['model'] or '?'}, port {running['port']}). Stop it with: ai-2 stop",
              file=sys.stderr)
        return 1
    print(f"Serving {model['label']} with the {hw.cpu_variant} runtime, {threads} threads, "
          f"ctx {ctx}, on http://{args.host}:{args.port}/ "
          f"(OpenAI-compatible /v1/chat/completions)")
    if idle:
        print(f"On demand: exits after {idle} s without requests"
              f"{' (tier ' + installed_tier_id() + ')' if args.idle_timeout is None and installed_tier_id() else ''}. Ctrl-C stops it.")
    if api_key:
        print("Clients must send  Authorization: Bearer <key>")
    warning = serve_preflight(model)
    if warning:
        print(f"warning: {warning}")
    sampling = sampling_args(model)
    if sampling:
        print("Sampling as the model card recommends: " + " ".join(sampling))
    extra = sampling + persona.ui_config_args(persona.system_prompt(model["label"]))
    return serve(runtime_dir, path, threads, ctx=ctx, host=args.host,
                 port=args.port, idle_timeout_s=idle, api_key=api_key, model_id=model["id"],
                 extra_args=extra)


def _server_ready(url: str, timeout: float = 2.0) -> bool:
    """True only when llama-server reports status "ok". It answers /health
    with 200 while the model is still loading (found on the 2011 laptop:
    requests then get 503 "Loading model"), so the body must be checked."""
    import urllib.request
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=timeout) as r:
            if r.status != 200:
                return False
            body = r.read(2000).decode("utf-8", "replace")
            return '"ok"' in body
    except Exception:
        return False


def _as_invoking_user() -> str | None:
    """Under sudo, point HOME (and the XDG dirs) at the invoking user so the
    per-user score and models are what gets checked. Returns the user name."""
    user = os.environ.get("SUDO_USER")
    if os.geteuid() != 0 or not user or user == "root":
        return None
    import pwd
    try:
        home = pwd.getpwnam(user).pw_dir
    except KeyError:
        return None
    os.environ["HOME"] = home
    for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME"):
        os.environ.pop(var, None)
    return user


def cmd_accessibility(args) -> int:
    from . import a11y
    return a11y.setup() if args.action == "setup" else a11y.status()


def cmd_chat(args) -> int:
    """Make sure the local AI server runs (start it on demand, detached) and
    open the chat page in the browser. The server stops itself when idle."""
    import os
    import subprocess
    import time
    hw = detect()
    cfg = remote.load()
    if args.remote and cfg is None:
        print("error: no remote AI configured. Set one up with:  ai-2 remote set <url> [--api-key KEY]",
              file=sys.stderr)
        return 1
    if cfg is not None and (args.remote or (cfg.get("default") and not args.local)):
        return _chat_remote(args, cfg)
    if cfg is not None and not args.local:
        print(f"(a remote AI is configured, {remote.describe(cfg)}; ai-2 chat --remote uses it)")
    url = f"http://127.0.0.1:{args.port}/"
    if args.model == PICK_MODEL:
        picked = _pick_model(hw)
        if picked is None:
            return 1
        args.model = picked["id"]
    running = serverstate.read_server()
    if running and args.model and running.get("model") and running["model"] != args.model:
        print(f"The AI is already running with {running['model']}, not {args.model}. "
              f"Stop it first:  ai-2 stop", file=sys.stderr)
        return 1
    started_here = False
    if not _server_ready(url):
        runtime_dir = find_runtime(hw.cpu_variant)
        model = _catalog_entry(args.model) if args.model else _usable_model(hw)
        if runtime_dir is None or model is None or find_model_file(model["file"]) is None:
            print("AI-2 is not set up on this computer yet. Run:  ai-2 wizard", file=sys.stderr)
            return 1
        state_dir = serverstate.state_dir()
        os.makedirs(state_dir, exist_ok=True)
        log = open(serverstate.log_file(), "ab")
        cmd = [sys.executable, "-m", "ai2.cli", "serve", "--port", str(args.port)]
        if args.idle_timeout is not None:
            cmd += ["--idle-timeout", str(args.idle_timeout)]
        if args.model:
            cmd += ["--model", model["id"]]
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         start_new_session=True,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        # whole lines, no dot spinner: screen readers only follow completed
        # lines, and the sighted cost of a line every 10 s is nil
        print(f"Starting the AI ({model['label']}) ... this takes a moment on a slow disk", flush=True)
        start = time.monotonic()
        deadline = start + args.wait
        last_note = start
        while time.monotonic() < deadline and not _server_ready(url):
            time.sleep(2)
            now = time.monotonic()
            if now - last_note >= 10:
                last_note = now
                print(f"  still starting ({int(now - start)} s)", flush=True)
        if not _server_ready(url):
            print(f"error: the server did not come up within {args.wait} s "
                  f"(see {os.path.join(state_dir, 'serve.log')})", file=sys.stderr)
            return 1
        started_here = True
    if started_here:
        # Only this invocation knows what timeout it started the server with
        # (0 means keep running, as for `ai-2 serve`).
        idle = args.idle_timeout if args.idle_timeout is not None else runtime_defaults(model["id"])["idle_timeout_s"]
        how = f"it stops by itself after {idle} s without use" if idle else "it keeps running"
    else:
        how = "it was already running"
    print(f"Chat with the AI at {url}  ({how}; ai-2 stop ends it now)")
    running_id = (serverstate.read_server() or {}).get("model") or (args.model or "")
    running_model = _catalog_entry(running_id) if running_id else None
    if running_model and is_starter(running_model):
        print(f"Note: {running_model['label']} is a very small starter model; it can get facts "
              "and simple math wrong. Bigger models:  ai-2 model list")
    from . import a11y
    reader = not args.terminal and not args.no_browser and a11y.reader_active()
    if args.terminal or reader or (not args.no_browser
                                   and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")):
        from .chatterm import repl
        if reader:
            print("A screen reader is running, so chatting right here instead of the browser "
                  "(ai-2 chat --terminal does this anywhere; add --speak for spoken answers).")
        elif not args.terminal:
            print("No graphical display, so chatting right here (ai-2 chat --terminal does this anywhere).")
        speaker = None
        if args.speak:
            if not a11y.speech_available():
                print("Spoken chat needs a speech engine. Set one up with:  ai-2 accessibility setup")
                return 1
            speaker = a11y.Speaker()
        streaming = args.stream or os.environ.get("AI2_CHAT_STREAM") == "1"
        try:
            label = running_model["label"] if running_model else "a small language model"
            return repl(url, streaming=streaming,
                        speak=speaker.speak if speaker else None,
                        system=persona.system_prompt(label))
        finally:
            if speaker:
                speaker.close()
    if not args.no_browser:
        try:
            subprocess.Popen(["xdg-open", url], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except FileNotFoundError:
            print("Open that address in your browser.")
    return 0


def _chat_remote(args, cfg: dict) -> int:
    """Chat with the configured remote AI. Says where the messages go first.
    A llama-server remote has a chat page of its own, so the browser opens
    it directly; anything else (an API provider) is a terminal chat."""
    import functools
    import os
    import subprocess
    from . import a11y
    from .chatterm import repl, stream_reply
    print(f"Talking to {remote.describe(cfg)}. Your messages leave this computer.")
    info = remote.probe(cfg)
    if not info["ok"]:
        print(f"error: cannot reach {cfg['url']}: {info['error']}  (ai-2 remote test)", file=sys.stderr)
        return 1
    if cfg.get("model") and info["models"] and cfg["model"] not in info["models"]:
        print(f"warning: the remote does not list model {cfg['model']}; it lists "
              + ", ".join(info["models"][:5]))
    reader = not args.terminal and not args.no_browser and a11y.reader_active()
    headless = not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")
    if not (args.terminal or reader or args.no_browser or headless) and info["web_ui"]:
        print(f"Chat with the AI at {cfg['url']}/  (the remote's own chat page"
              + (f"; enter the API key {remote.masked_key(cfg)} in its settings" if cfg.get("api_key") else "")
              + ")")
        try:
            subprocess.Popen(["xdg-open", cfg["url"] + "/"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except FileNotFoundError:
            print("Open that address in your browser.")
        return 0
    if not args.terminal and not info["web_ui"] and not args.no_browser:
        print("This remote has no chat page of its own, so chatting right here.")
    speaker = None
    if args.speak:
        if not a11y.speech_available():
            print("Spoken chat needs a speech engine. Set one up with:  ai-2 accessibility setup")
            return 1
        speaker = a11y.Speaker()
    label = cfg.get("model") or (info["models"][0] if info["models"] else "a language model")
    stream = functools.partial(stream_reply, headers=remote.headers(cfg), model=cfg.get("model"))
    streaming = args.stream or os.environ.get("AI2_CHAT_STREAM") == "1"
    try:
        return repl(cfg["url"], stream=stream, streaming=streaming,
                    speak=speaker.speak if speaker else None,
                    system=persona.system_prompt(label, local=False))
    finally:
        if speaker:
            speaker.close()


def cmd_remote(args) -> int:
    action = args.remote_cmd
    if action == "set":
        key = args.api_key
        if args.api_key_stdin:
            key = sys.stdin.readline().strip()
            if not key:
                print("error: no API key on stdin", file=sys.stderr)
                return 1
        p = remote.save(args.url, key, args.model, args.default)
        cfg = remote.load()
        print(f"Remote AI: {remote.describe(cfg)}, API key {remote.masked_key(cfg)}, saved in {p} (mode 600).")
        print("ai-2 chat uses it " + ("by default now (ai-2 chat --local for this computer's own AI)."
                                      if cfg["default"] else "with --remote (ai-2 remote default on to always use it)."))
        info = remote.probe(cfg)
        if info["ok"]:
            print("Reachable." + (f" Models: {', '.join(info['models'][:8])}" if info["models"] else "")
                  + (" Has a chat page." if info["web_ui"] else ""))
        else:
            print(f"warning: not reachable right now: {info['error']}")
        return 0
    cfg = remote.load()
    if action == "show":
        if cfg is None:
            print("No remote AI configured. Set one up with:  ai-2 remote set <url> [--api-key KEY]")
            return 0
        print(f"Remote AI: {remote.describe(cfg)}")
        print(f"API key:   {remote.masked_key(cfg)}")
        print(f"Default:   {'yes, ai-2 chat talks to it (--local for this computer)' if cfg.get('default') else 'no, only with ai-2 chat --remote'}")
        print(f"File:      {remote.path()}")
        return 0
    if action == "test":
        if cfg is None:
            print("error: no remote AI configured", file=sys.stderr)
            return 1
        info = remote.probe(cfg)
        if not info["ok"]:
            print(f"{cfg['url']}: NOT reachable: {info['error']}")
            return 1
        print(f"{cfg['url']}: reachable" + (", has a chat page (llama-server)" if info["web_ui"] else ""))
        if info["models"]:
            print("Models: " + ", ".join(info["models"][:20]))
        if cfg.get("model") and info["models"] and cfg["model"] not in info["models"]:
            print(f"warning: model {cfg['model']} is not in that list")
            return 1
        return 0
    if action == "default":
        cfg = remote.set_default(args.state == "on")
        if cfg is None:
            print("error: no remote AI configured", file=sys.stderr)
            return 1
        print("ai-2 chat now talks to " + (f"{cfg['url']} (--local for this computer's own AI)" if cfg["default"]
                                           else "this computer's own AI (--remote for the remote one)"))
        return 0
    if action == "clear":
        print("Removed." if remote.clear() else "Nothing configured.")
        return 0
    return 1


def cmd_workflow(args) -> int:
    """What this computer can be used for: profiles gated by the tier's
    grants and the AI Score's stars, with the remote AI as the way out."""
    from . import workflows
    hw = detect()
    score = _load_score()
    catalog = load_catalog()
    profiles = workflows.load_profiles()
    rec = _recommended_model(hw) if score else None
    cfg = remote.load()

    def ev(p):
        return workflows.evaluate(p, hw, score, rec, cfg, find_model_file, catalog)

    action = args.workflow_cmd or "list"
    if action == "list":
        print(workflows.render_list([ev(p) for p in profiles]))
        return 0
    if action == "status":
        print(workflows.render_status([ev(p) for p in profiles]))
        return 0
    profile = workflows.get_profile(args.name, profiles)
    if profile is None:
        print(f"error: no workflow '{args.name}' (names: {', '.join(p['id'] for p in profiles)})",
              file=sys.stderr)
        return 1
    r = ev(profile)
    if action == "info":
        print(workflows.render_info(r))
        return 0
    # install: models pulled, packages printed (read-only toward the system)
    if r["verdict"] == "unavailable":
        print(f"error: {r['why']}", file=sys.stderr)
        return 1
    if r["verdict"] == "unknown":
        print("error: run  ai-2 benchmark  first, the score decides what fits", file=sys.stderr)
        return 1
    models, pacman_line = workflows.install_plan(r)
    rc = 0
    if r["verdict"] == "slow":
        print(f"Note: {r['why']}. Setting it up anyway.")
    for m in models:
        rc = _pull_model(m) or rc
    if pacman_line:
        print("Packages this workflow needs, not installed by ai-2 in this version; run:")
        print(f"  {pacman_line}")
    if not models and not pacman_line:
        print("Nothing to download or install.")
    if r["verdict"] == "remote":
        print(f"On this computer it runs through the remote AI: {r['why'].split('; ', 1)[-1]}")
    if profile.get("usage"):
        print("How to use it:")
        for u in profile["usage"]:
            print(f"  {u}")
    return rc


def cmd_doctor(args) -> int:
    """Read-only health check of the AI-2 setup on this machine."""
    from .doctor import render, run_checks, verdict
    user = _as_invoking_user()
    hw = detect()
    try:
        backend = get_service_backend(hw.init_system)
    except ValueError:
        backend = None
    checks = run_checks(hw, backend)
    print(branding.compact())
    print()
    if user:
        print(f"  (checking the files of user {user})")
    print(render(checks))
    rc = verdict(checks)
    print("\n" + {0: "Everything looks fine.", 1: "Some warnings, see above.",
                   2: "Something is broken, see the FAIL lines."}[rc])
    return rc


def cmd_report(args) -> int:
    """Write a bug-report file (hardware, checks, packages, state, server log tail)."""
    from .doctor import report_text, run_checks
    _as_invoking_user()
    hw = detect()
    try:
        backend = get_service_backend(hw.init_system)
    except ValueError:
        backend = None
    text = report_text(hw, run_checks(hw, backend))
    out = args.output or os.path.expanduser("~/ai2-report.txt")
    with open(out, "w") as fh:
        fh.write(text)
    print(f"Report written to {out}. Attach it to an issue at "
          "https://github.com/ProWoos-Devs/ai-2/issues (it contains no prompts or chat text).")
    return 0


def cmd_stop(args) -> int:
    """Stop the on-demand server started by serve/chat and free its RAM."""
    running = serverstate.read_server()
    if not running:
        print("No AI-2 server is running.")
        return 0
    print(f"Stopping the AI ({running.get('model') or running.get('model_path')}, pid {running['pid']}) ...")
    serverstate.stop_server()
    print("Stopped.")
    return 0


def cmd_update_check(args, sleep=None) -> int:
    """The shared passive update check: refresh the cached count (at most once
    per --max-age hours) and optionally raise a desktop notification. The
    login-shell hint (/etc/profile.d/ai2-updates.sh) reads the same cache.

    With --every HOURS it keeps going for the life of the session (the
    desktop autostart uses this), because a check that runs once at login
    never runs on a machine that is never logged out (rafaminu-pc, up for a
    day with two releases published and nothing announced, 2026-09-04). On
    those later rounds the bubble is raised only when a FRESH check found
    something, so a bubble still on screen is not stacked every round."""
    import time
    from . import updates
    sleep = sleep or time.sleep
    first = True
    while True:
        cached = bool(args.max_age) and updates.state_is_fresh(args.max_age)
        st = (updates.load_state() or {}) if cached else (updates.check_now() or updates.load_state() or {})
        count = st.get("count")
        if count is None:
            print("No update information (offline, or checkupdates missing).", flush=True)
        else:
            if args.notify and count and (first or not cached):
                updates.notify(count)
            print(f"{count} update(s) available. Update with:  ai-2 update"
                  if count else "The system is current.", flush=True)
        if not args.every:
            return 0
        first = False
        sleep(args.every * 3600)


def cmd_update(args) -> int:
    """Update everything. AI-2, the AI engine, the model catalog and the rest
    of the system come from the same rolling repositories, so there is one
    update and this is it."""
    from . import software
    if args.gui:
        if software.open_gui(updates=True):
            print("Opened Add/Remove Software on its updates page.")
            return 0
        print("The graphical package manager is not installed on this computer. "
              "Add it with:  ai-2 install pamac\nUpdating here instead.\n")
    return software.update()


def cmd_install(args) -> int:
    """Install software by plain-language short name or by package name."""
    from . import software
    if args.list:
        print(software.render_catalog())
        return 0
    if args.gui:
        if software.open_gui():
            print("Opened Add/Remove Software.")
            return 0
        print("The graphical package manager is not installed on this computer. "
              "Add it with:  ai-2 install pamac\nInstalling here instead.\n")
    return software.install(args.what, init_system=detect().init_system)


def cmd_guide(args) -> int:
    """The guide for this installed computer: what it can do, how to add
    software, how to update, where to get help."""
    from . import guide
    _as_invoking_user()
    if args.place_desktop:
        written = guide.place_on_desktop(lang=args.lang)
        if written:
            print(f"Guide placed on the desktop: {written}")
        return 0
    path = guide.guide_path(args.lang)
    if path is None:
        print("The AI-2 guide is not installed on this computer "
              "(it belongs to the ai-2 package, in /usr/share/doc/ai2/).", file=sys.stderr)
        return 1
    if args.path:
        print(path)
        return 0
    if args.open and guide.open_in_editor(args.lang):
        print(f"Opened {path}")
        return 0
    print(guide.read(args.lang) or "")
    return 0


def cmd_wizard(args) -> int:
    from .wizard import Wizard
    try:
        return Wizard(yes=args.yes).go()
    except KeyboardInterrupt:
        print("\nStopped. Run  ai-2 wizard  any time to continue.")
        return 130


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ai-2",
        description="AI-2 transforms this PC into the best AI workstation "
                    "its hardware can realistically support.",
    )
    parser.add_argument("--version", action="version", version=f"AI-2 {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="command")

    p_detect = sub.add_parser("detect", help="show detected hardware")
    p_detect.add_argument("--json", action="store_true")
    p_detect.set_defaults(func=cmd_detect)

    p_tier = sub.add_parser("tier", help="show the assigned capability tier")
    p_tier.set_defaults(func=cmd_tier)

    p_prof = sub.add_parser("profile", help="everything AI-2 knows about this machine, in one view")
    p_prof.add_argument("--json", action="store_true")
    p_prof.set_defaults(func=cmd_profile)

    p_init = sub.add_parser("init", help="plan (default) or apply system tuning for the tier")
    p_init.add_argument("--apply", action="store_true", help="execute the plan (root)")
    p_init.add_argument("--revert", action="store_true", help="undo a previous --apply: restore original files, disable the services it enabled (root)")
    p_init.add_argument("--tier", choices=["tiny", "light", "standard", "creator", "studio", "workstation"],
                        help="override the assigned tier")
    p_init.set_defaults(func=cmd_init)

    p_bench = sub.add_parser("benchmark", help="measure real inference speed and compute the AI Score")
    p_bench.add_argument("--json", action="store_true")
    p_bench.set_defaults(func=cmd_benchmark)

    p_rec = sub.add_parser("recommend", help="recommend a local model from the stored AI Score")
    p_rec.set_defaults(func=cmd_recommend)

    p_rt = sub.add_parser("runtime", help="manage the llama.cpp runtime for this CPU")
    rt_sub = p_rt.add_subparsers(dest="runtime_cmd", metavar="action")
    p_rt_i = rt_sub.add_parser("install", help="install the runtime package for this CPU class")
    p_rt_i.add_argument("--apply", action="store_true", help="really install (root)")
    p_rt_i.set_defaults(func=cmd_runtime_install)

    p_model = sub.add_parser("model", help="manage local models")
    m_sub = p_model.add_subparsers(dest="model_cmd", metavar="action")
    p_m_pull = m_sub.add_parser("pull", help="download the recommended model (or a named one)")
    p_m_pull.add_argument("model", nargs="?", help="catalog id, e.g. qwen2.5-0.5b")
    p_m_pull.add_argument("--force", action="store_true", help="download even if the disk-space check fails")
    p_m_pull.set_defaults(func=cmd_model_pull)
    p_m_list = m_sub.add_parser("list", help="models on this computer and in the catalog")
    p_m_list.add_argument("--json", action="store_true")
    p_m_list.set_defaults(func=cmd_model_list)
    p_m_rm = m_sub.add_parser("rm", help="delete a downloaded model to free disk space")
    p_m_rm.add_argument("model", help="catalog id")
    p_m_rm.set_defaults(func=cmd_model_rm)
    p_m_ver = m_sub.add_parser("verify", help="check downloaded models against the catalog checksums")
    p_m_ver.add_argument("model", nargs="?", help="catalog id (default: all)")
    p_m_ver.set_defaults(func=cmd_model_verify)

    p_serve = sub.add_parser("serve", help="run llama-server on demand with the recommended model")
    p_serve.add_argument("-m", "--model", nargs="?", const=PICK_MODEL,
                         help="catalog id (default: the recommended model); with no value, choose from a list")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8080)
    p_serve.add_argument("--ctx", type=int, default=None, help="context size (default: the tier's, else 2048)")
    p_serve.add_argument("--idle-timeout", type=int, default=None,
                         help="stop after this many idle seconds (default: the tier's, else 600; 0 = keep running)")
    p_serve.add_argument("--api-key", help="require this bearer token from clients (needed to bind off localhost; also AI2_API_KEY)")
    p_serve.add_argument("--insecure", action="store_true", help="allow a non-localhost --host without an API key")
    p_serve.set_defaults(func=cmd_serve)

    p_chat = sub.add_parser("chat", help="start the local AI (if needed) and chat: browser page by default, --terminal for the lightest client")
    p_chat.add_argument("--terminal", action="store_true",
                        help="chat in this terminal instead of the browser (fastest, minimal memory, works over SSH)")
    p_chat.add_argument("-m", "--model", nargs="?", const=PICK_MODEL,
                         help="catalog id (default: the recommended model); with no value, choose from a list")
    p_chat.add_argument("--port", type=int, default=8080)
    p_chat.add_argument("--idle-timeout", type=int, default=None,
                        help="stop the AI after this many idle seconds (default: the tier's, else 600; a chat page left open does not count as use)")
    p_chat.add_argument("--wait", type=int, default=180, help="seconds to wait for the server to come up")
    p_chat.add_argument("--no-browser", action="store_true", help="do not open the browser, just print the address")
    p_chat.add_argument("--speak", action="store_true",
                        help="speak the answers aloud through speech-dispatcher (with --terminal)")
    p_chat.add_argument("--stream", action="store_true",
                        help="terminal chat prints token by token instead of whole sentences (also AI2_CHAT_STREAM=1)")
    p_chat.add_argument("--remote", action="store_true",
                        help="talk to the remote AI set with 'ai-2 remote set' instead of this computer's own")
    p_chat.add_argument("--local", action="store_true",
                        help="this computer's own AI even when the remote is the default")
    p_chat.set_defaults(func=cmd_chat)

    p_remote = sub.add_parser("remote", help="a bigger AI on another computer or an API provider, for chat --remote")
    r_sub = p_remote.add_subparsers(dest="remote_cmd", metavar="action")
    p_r_set = r_sub.add_parser("set", help="save the address (and key) of the remote AI")
    p_r_set.add_argument("url", help="http://host:8080 (another computer running ai-2 serve) or a provider's base URL")
    p_r_set.add_argument("--api-key", help="bearer token; prefer --api-key-stdin to keep it out of the shell history")
    p_r_set.add_argument("--api-key-stdin", action="store_true", help="read the API key from the first line of stdin")
    p_r_set.add_argument("--model", help="model name the remote expects (needed by API providers)")
    p_r_set.add_argument("--default", action="store_true", help="make ai-2 chat use it unless --local is given")
    p_r_set.set_defaults(func=cmd_remote)
    r_sub.add_parser("show", help="what is configured").set_defaults(func=cmd_remote)
    r_sub.add_parser("test", help="reach it and list its models").set_defaults(func=cmd_remote)
    p_r_def = r_sub.add_parser("default", help="on: ai-2 chat talks to the remote; off: only with --remote")
    p_r_def.add_argument("state", choices=["on", "off"])
    p_r_def.set_defaults(func=cmd_remote)
    r_sub.add_parser("clear", help="forget the remote AI and its key").set_defaults(func=cmd_remote)

    p_wf = sub.add_parser("workflow", help="what this computer can be used for (chat, translation, documents), honestly gated by the AI Score")
    wf_sub = p_wf.add_subparsers(dest="workflow_cmd", metavar="action")
    wf_sub.add_parser("list", help="every workflow and whether it works here").set_defaults(func=cmd_workflow)
    p_wf_info = wf_sub.add_parser("info", help="what a workflow needs and how to use it")
    p_wf_info.add_argument("name")
    p_wf_info.set_defaults(func=cmd_workflow)
    p_wf_inst = wf_sub.add_parser("install", help="download its models; packages are printed as a pacman line, not installed")
    p_wf_inst.add_argument("name")
    p_wf_inst.set_defaults(func=cmd_workflow)
    wf_sub.add_parser("status", help="workflows ready on this computer").set_defaults(func=cmd_workflow)
    p_wf.set_defaults(func=cmd_workflow)

    p_doc = sub.add_parser("doctor", help="check that the engine, model, tuning and services are in order")
    p_doc.set_defaults(func=cmd_doctor)

    p_rep = sub.add_parser("report", help="write a bug-report file with hardware, checks and logs")
    p_rep.add_argument("-o", "--output", help="file to write (default ~/ai2-report.txt)")
    p_rep.set_defaults(func=cmd_report)

    p_stop = sub.add_parser("stop", help="stop the running local AI server and free its memory")
    p_stop.set_defaults(func=cmd_stop)

    p_wiz = sub.add_parser("wizard", help="guided setup: scan, tune, measure, pick and download a model")
    p_wiz.add_argument("--yes", action="store_true", help="unattended: take the default answer everywhere")
    p_wiz.set_defaults(func=cmd_wizard)

    p_upd = sub.add_parser("update-check", help="check for pending system updates (cached; notifies the desktop with --notify)")
    p_upd.add_argument("--notify", action="store_true", help="send a desktop notification when updates are pending")
    p_upd.add_argument("--max-age", type=float, default=0, metavar="HOURS",
                       help="reuse a cached result younger than this many hours (0 = always check)")
    p_upd.add_argument("--every", type=float, default=0, metavar="HOURS",
                       help="keep checking every this many hours for the life of the session (the desktop autostart does; later rounds notify only when a fresh check finds something)")
    p_upd.set_defaults(func=cmd_update_check)

    p_a11y = sub.add_parser("accessibility",
                            help="screen-reader status, or set up Orca and spoken chat for this user")
    p_a11y.add_argument("action", nargs="?", choices=["setup"],
                        help="setup = install the reader stack (sudo asks once) and wire Orca autostart, the assistive-technologies flag and the Super+Alt+S shortcut for the current user")
    p_a11y.set_defaults(func=cmd_accessibility)

    p_up = sub.add_parser("update", help="update AI-2, the AI engine and the whole system (one command, rolling release)")
    p_up.add_argument("--gui", action="store_true",
                      help="open the graphical Add/Remove Software on its updates page instead")
    p_up.set_defaults(func=cmd_update)

    p_inst = sub.add_parser("install", help="install software AI-2 leaves out (office, printing, media, ...) or any package")
    p_inst.add_argument("what", nargs="*", help="short names from 'ai-2 install --list', or package names")
    p_inst.add_argument("--list", action="store_true", help="show the short names and what they install")
    p_inst.add_argument("--gui", action="store_true",
                        help="open the graphical Add/Remove Software instead")
    p_inst.set_defaults(func=cmd_install)

    p_guide = sub.add_parser("guide", help="the AI-2 guide for this computer: what it does, adding software, updating")
    p_guide.add_argument("--lang", choices=sorted(("en", "es", "de")),
                         help="guide language (default: the system language)")
    p_guide.add_argument("--open", action="store_true", help="open it in the desktop text editor")
    p_guide.add_argument("--path", action="store_true", help="print the file path only")
    p_guide.add_argument("--place-desktop", action="store_true",
                         help="copy it to the desktop once (what the first login does)")
    p_guide.set_defaults(func=cmd_guide)

    p_logo = sub.add_parser("logo", help="print the AI-2 logo")
    p_logo.set_defaults(func=cmd_logo)

    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        # `ai-2`, `ai-2 model`, `ai-2 runtime` with nothing after it: list what
        # is available instead of argparse's "arguments are required" error.
        {None: parser, "model": p_model, "runtime": p_rt, "remote": p_remote}[args.command].print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
