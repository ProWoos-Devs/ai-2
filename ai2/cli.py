from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

from . import __version__, branding
from .backends import get_package_backend, get_service_backend
from .benchmark import STAR_LABELS, measure
from .detect import detect
from .models import load_catalog, recommend
from . import serverstate
from .runtime import (download_model, download_preflight, find_model_file, find_runtime,
                      find_test_model, installed_models, model_dir, run_llama_bench,
                      runtime_package, serve, serve_preflight, verify_model)
from .state import load_score, write_score
from .tiers import assign, installed_tier_id, load_tiers, resolve_config, runtime_defaults
from .tuning import apply_plan, build_plan, render_plan

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
    if rec["remote_suggested"]:
        print("  For anything larger, use remote inference, this machine can hold it "
              "but can't run it fast enough locally.")


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
    model = find_test_model()
    if model is None:
        print("error: no .gguf test model found (set AI2_TEST_MODEL or put one in "
              "~/models or /var/lib/ai2/models).", file=sys.stderr)
        return 1
    threads = max(1, hw.logical_cores)
    print(f"Benchmarking with {hw.cpu_variant} runtime, {threads} threads, "
          f"model {model.split('/')[-1]} ... (this can take a minute)")
    try:
        data, rec = measure(hw, model, runtime_dir, threads)
    except Exception as exc:
        print(f"error: benchmark failed: {exc}", file=sys.stderr)
        return 1
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


def _catalog_entry(model_id: str) -> dict | None:
    return next((m for m in load_catalog() if m["id"] == model_id), None)


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
    existing = find_model_file(model["file"])
    if existing:
        print(f"{model['label']} already present at {existing}")
        return 0
    dest = model_dir()
    problem = download_preflight(model, dest)
    if problem and not args.force:
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
    if args.model:
        model = _catalog_entry(args.model)
        if model is None:
            print(f"error: '{args.model}' is not in the catalog", file=sys.stderr)
            return 1
    else:
        model = _recommended_model(hw)
        if model is None:
            print("error: no recommendation yet. Run 'ai-2 benchmark' first, or name a "
                  "model: ai-2 serve --model <id>", file=sys.stderr)
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
    if serverstate.read_server():
        running = serverstate.read_server()
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
    return serve(runtime_dir, path, threads, ctx=ctx, host=args.host,
                 port=args.port, idle_timeout_s=idle, api_key=api_key, model_id=model["id"])


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


def cmd_chat(args) -> int:
    """Make sure the local AI server runs (start it on demand, detached) and
    open the chat page in the browser. The server stops itself when idle."""
    import os
    import subprocess
    import time
    hw = detect()
    url = f"http://127.0.0.1:{args.port}/"
    running = serverstate.read_server()
    if running and args.model and running.get("model") and running["model"] != args.model:
        print(f"The AI is already running with {running['model']}, not {args.model}. "
              f"Stop it first:  ai-2 stop", file=sys.stderr)
        return 1
    if not _server_ready(url):
        runtime_dir = find_runtime(hw.cpu_variant)
        model = _catalog_entry(args.model) if args.model else _recommended_model(hw)
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
        print(f"Starting the AI ({model['label']}) ... this takes a moment on a slow disk", end="", flush=True)
        deadline = time.monotonic() + args.wait
        while time.monotonic() < deadline and not _server_ready(url):
            time.sleep(2)
            print(".", end="", flush=True)
        print()
        if not _server_ready(url):
            print(f"error: the server did not come up within {args.wait} s "
                  f"(see {os.path.join(state_dir, 'serve.log')})", file=sys.stderr)
            return 1
    idle = args.idle_timeout if args.idle_timeout is not None else runtime_defaults(args.model)["idle_timeout_s"]
    print(f"Chat with the AI at {url}  (it stops by itself after {idle} s without use; ai-2 stop ends it now)")
    if not args.no_browser:
        try:
            subprocess.Popen(["xdg-open", url], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except FileNotFoundError:
            print("Open that address in your browser.")
    return 0


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

    p_rec = sub.add_parser("recommend", help="recommend a local model from the stored AI Score")
    p_rec.set_defaults(func=cmd_recommend)

    p_rt = sub.add_parser("runtime", help="manage the llama.cpp runtime for this CPU")
    rt_sub = p_rt.add_subparsers(dest="runtime_cmd", required=True)
    p_rt_i = rt_sub.add_parser("install", help="install the runtime package for this CPU class")
    p_rt_i.add_argument("--apply", action="store_true", help="really install (root)")
    p_rt_i.set_defaults(func=cmd_runtime_install)

    p_model = sub.add_parser("model", help="manage local models")
    m_sub = p_model.add_subparsers(dest="model_cmd", required=True)
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
    p_serve.add_argument("--model", help="catalog id (default: the recommended model)")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8080)
    p_serve.add_argument("--ctx", type=int, default=None, help="context size (default: the tier's, else 2048)")
    p_serve.add_argument("--idle-timeout", type=int, default=None,
                         help="stop after this many idle seconds (default: the tier's, else 600; 0 = keep running)")
    p_serve.add_argument("--api-key", help="require this bearer token from clients (needed to bind off localhost; also AI2_API_KEY)")
    p_serve.add_argument("--insecure", action="store_true", help="allow a non-localhost --host without an API key")
    p_serve.set_defaults(func=cmd_serve)

    p_chat = sub.add_parser("chat", help="start the local AI (if needed) and open the chat page in the browser")
    p_chat.add_argument("--model", help="catalog id (default: the recommended model)")
    p_chat.add_argument("--port", type=int, default=8080)
    p_chat.add_argument("--idle-timeout", type=int, default=None,
                        help="stop the AI after this many idle seconds (default: the tier's, else 600; a chat page left open does not count as use)")
    p_chat.add_argument("--wait", type=int, default=180, help="seconds to wait for the server to come up")
    p_chat.add_argument("--no-browser", action="store_true", help="do not open the browser, just print the address")
    p_chat.set_defaults(func=cmd_chat)

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

    p_logo = sub.add_parser("logo", help="print the AI-2 logo")
    p_logo.set_defaults(func=cmd_logo)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
