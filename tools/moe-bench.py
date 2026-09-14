#!/usr/bin/env python3
"""Measure the small mixture-of-experts candidates for the Standard and Creator
catalog slot ON THIS MACHINE, the way the 2026-09-14 review's item 6 asks:
measurement first, and a catalog entry only for a candidate that clears the
gate. Nothing here changes the catalog or the system.

  python3 tools/moe-bench.py --report moe-report.md
      [--runtime-dir DIR]        the llama.cpp runtime (default: the [ai2] one for this CPU)
      [--dir DIR]                where the GGUF files live or go (default: the AI-2 model dir)
      [--candidates a,b,c]       subset of: granite-4.0-h-tiny lfm2.5-8b-a1b gemma4-e2b
      [--reference ID]           catalog model the gate compares against (default qwen3-1.7b)
      [--threads N]              default: every logical core
      [--chat-check hybrid|all|none]   the two-turn prompt-cache check (default hybrid)
      [--pp N --ng N]            llama-bench prompt and generation sizes (default 512 / 128)

What it does, per model: verifies the file's SHA-256 (downloads it first if
it is missing, with a disk preflight), runs llama-bench for prompt processing
and generation with the peak RSS of the process (VmHWM), and for the hybrid
models (Granite and LFM keep a recurrent state next to the KV cache) runs a
two-turn chat against a temporary llama-server to see whether the second
turn reuses the prompt cache or re-reads the whole conversation, which on a
slow CPU is the difference between a usable chat and minutes per turn.

The gate, from the review: a candidate enters the catalog only if its
generation speed on this box is at least the reference model's (qwen3-1.7b,
the Light tier's model) AND, for a hybrid, the second turn reused the cache.
Two catalog fields (active_params_b for the speed estimate, class_b for the
quality rank) land together with the entry that needs them, never earlier.

HOW LONG IT TAKES. This is not measured, it is arithmetic on the review's
numbers for the 2016 reference laptop (about 1.3 tokens per second on a 0.5B
model): a 4 to 5 GB file loads for minutes from disk, the bench generates 128
tokens at well under one token per second, and the chat check reads two
prompts at a similar rate, so expect on the order of an hour per candidate
there and the whole run to take an afternoon. On the machine the review
names, rafaminu-pc, stop the REAL8 runit services first and stay clear of the
21:30 backup window; the 4.8 GiB LFM file may swap on an 8 GB box.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

# The installed tool lives at /usr/lib/ai2 (not in site-packages).
try:
    import ai2  # noqa: F401
except ImportError:
    sys.path.insert(0, "/usr/lib/ai2")
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# File names, sizes and LFS hashes read from the Hugging Face API on
# 2026-09-14; the license lines from the same API and the model cards.
CANDIDATES = [
    {"id": "granite-4.0-h-tiny", "label": "Granite 4.0 H-Tiny", "params_b": 7.0, "active_b": 1.0,
     "hybrid": True, "license": "apache-2.0",
     "repo": "ibm-granite/granite-4.0-h-tiny-GGUF", "file": "granite-4.0-h-tiny-Q4_K_M.gguf",
     "bytes": 4230976352, "sha256": "5a38b08c441ae1adbafb1d2b8a7167e0d48734d83af68b268cefea1eec553dcd"},
    {"id": "lfm2.5-8b-a1b", "label": "LFM2.5 8B A1B", "params_b": 8.3, "active_b": 1.5,
     "hybrid": True, "license": "LFM Open License v1.0 (not OSI, commercial use capped by revenue)",
     "repo": "LiquidAI/LFM2.5-8B-A1B-GGUF", "file": "LFM2.5-8B-A1B-Q4_K_M.gguf",
     "bytes": 5155564768, "sha256": "4923ec14f06b968b74d663e5949867d2d9c3bf13a20b8be1a9f9af39989b2bb0"},
    # Dense with per-layer embeddings, not a MoE: an architecture smoke test
    # for gemma4 on this runtime, by the review's arithmetic it cannot pass
    # the speed gate on the validated machines.
    {"id": "gemma4-e2b", "label": "Gemma 4 E2B (smoke test, not a MoE)", "params_b": 5.1, "active_b": 2.3,
     "hybrid": False, "license": "apache-2.0", "optional": True,
     "repo": "unsloth/gemma-4-E2B-it-GGUF", "file": "gemma-4-E2B-it-Q4_K_M.gguf",
     "bytes": 3106738272, "sha256": "740185b21d22ceb83a11c3aa62ad5842ef32c70f6096d756bbee85a1e4ec34b8"},
]
COMPARISON_IDS = ["qwen3-1.7b", "smollm3-3b"]   # cataloged dense models, same box, same run
DEFAULT_REFERENCE = "qwen3-1.7b"
DOWNLOAD_MARGIN = 300 * 1024 * 1024

# One long Spanish paragraph so the first turn is a real prompt and the second
# turn's cache reuse (or its absence) shows in the numbers.
TURN1 = ("Lee este texto y responde con una sola palabra. " +
         "La Constitución se fundamenta en la indisoluble unidad de la Nación española, patria común e "
         "indivisible de todos los españoles, y reconoce y garantiza el derecho a la autonomía de las "
         "nacionalidades y regiones que la integran y la solidaridad entre todas ellas. El castellano es "
         "la lengua española oficial del Estado. Todos los españoles tienen el deber de conocerla y el "
         "derecho a usarla. Las demás lenguas españolas serán también oficiales en las respectivas "
         "Comunidades Autónomas de acuerdo con sus Estatutos. La riqueza de las distintas modalidades "
         "lingüísticas de España es un patrimonio cultural que será objeto de especial respeto y "
         "protección. La bandera de España está formada por tres franjas horizontales, roja, amarilla y "
         "roja, siendo la amarilla de doble anchura que cada una de las rojas. La capital del Estado es "
         "la villa de Madrid. ") * 2 + "¿Cuál es la capital del Estado?"
TURN2 = "¿Y cuál es la lengua oficial?"


# ------------------------------------------------------------ pure pieces

def file_mb(n_bytes: int) -> int:
    """The catalog's convention: decimal MB, rounded up."""
    return math.ceil(n_bytes / 1_000_000)


def cache_reused(prompt_n_turn1: int | None, prompt_n_turn2: int | None, server_log: str) -> bool | None:
    """Did the second turn reuse the prompt cache? Turn 2's prompt contains all
    of turn 1's, so without reuse the server processes MORE tokens on turn 2
    than on turn 1; with reuse it processes only the new tail. llama-server
    also logs when it had to start over. None when the numbers are missing."""
    if "forcing full prompt re-processing" in server_log:
        return False
    if prompt_n_turn1 is None or prompt_n_turn2 is None:
        return None
    return prompt_n_turn2 < prompt_n_turn1


def clears_gate(row: dict, reference_tg: float | None) -> str:
    """'yes', 'no' or 'undetermined' with the reason, from the review's rule."""
    if reference_tg is None or row.get("tg") is None:
        return "undetermined (no reference or no measurement)"
    if row["tg"] < reference_tg:
        return f"no (tg {row['tg']:.2f} < reference {reference_tg:.2f})"
    if row.get("hybrid") and row.get("cache_reused") is not True:
        return "no (hybrid without prompt-cache reuse on turn 2)"
    return "yes"


def build_report(rows: list[dict], reference_id: str, machine: str = "") -> str:
    ref = next((r for r in rows if r["id"] == reference_id), None)
    ref_tg = ref.get("tg") if ref else None
    lines = [f"# moe-bench report{' on ' + machine if machine else ''}", "",
             f"Reference for the gate: {reference_id}"
             + (f" ({ref_tg:.2f} tok/s)" if ref_tg is not None else " (not measured, gate undetermined)"), "",
             "| model | file MiB | params total/active | tg tok/s | pp tok/s | peak RSS MiB | cache reused | gate |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        params = f"{r.get('params_b', '?')} / {r.get('active_b', r.get('params_b', '?'))}"
        tg = f"{r['tg']:.2f}" if r.get("tg") is not None else "failed"
        pp = f"{r['pp']:.2f}" if r.get("pp") is not None else "-"
        rss = str(r["peak_rss_mib"]) if r.get("peak_rss_mib") is not None else "-"
        cache = {True: "yes", False: "NO", None: "-"}[r.get("cache_reused")]
        gate = "-" if r.get("role") == "comparison" else clears_gate(r, ref_tg)
        lines.append(f"| {r['label']} | {r.get('file_mib', '?')} | {params} | {tg} | {pp} | {rss} | {cache} | {gate} |")
    lines += ["", "tg/pp are llama-bench averages (one repetition each); peak RSS is VmHWM of the process that "
              "loaded the model; cache reused compares the prompt tokens llama-server processed on turn 2 with "
              "turn 1 and honors its own 'forcing full prompt re-processing' line."]
    for r in rows:
        if r.get("error"):
            lines.append(f"- {r['label']}: {r['error']}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------- running things

def _vmhwm_mib(pid: int) -> int | None:
    try:
        with open(f"/proc/{pid}/status") as fh:
            for line in fh:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


def run_with_peak(cmd: list[str], env: dict, timeout: int) -> tuple[int, str, str, int | None]:
    """Run cmd, return (rc, stdout, stderr, peak RSS MiB), the peak polled
    every half second (VmHWM only grows, so the last reading is the peak)."""
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    peak = {"mib": None}

    def poll():
        while proc.poll() is None:
            v = _vmhwm_mib(proc.pid)
            if v is not None:
                peak["mib"] = v
            time.sleep(0.5)
    t = threading.Thread(target=poll, daemon=True)
    t.start()
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        return -1, out, err + f"\n(timeout after {timeout} s)", peak["mib"]
    t.join(2)
    return proc.returncode, out, err, peak["mib"]


def bench(runtime_dir: str, model_path: str, threads: int, pp: int, ng: int, timeout: int) -> dict:
    from ai2.benchmark import parse_llama_bench_json
    env = dict(os.environ, LD_LIBRARY_PATH=runtime_dir)
    cmd = [os.path.join(runtime_dir, "llama-bench"), "-m", model_path, "-p", str(pp), "-n", str(ng),
           "-r", "1", "-t", str(threads), "-o", "json"]
    rc, out, err, peak = run_with_peak(cmd, env, timeout)
    if rc != 0:
        return {"error": f"llama-bench exit {rc}: {err.strip()[-300:]}", "peak_rss_mib": peak}
    res = parse_llama_bench_json(out)
    if res is None:
        return {"error": "could not parse llama-bench output", "peak_rss_mib": peak}
    return {"tg": res.tg_tps, "pp": res.pp_tps, "peak_rss_mib": peak}


def _post(port: int, path: str, payload: dict, timeout: int):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _ready(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            return r.status == 200 and b'"ok"' in r.read(200)
    except Exception:
        return False


def chat_check(runtime_dir: str, model_path: str, threads: int, port: int, timeout: int) -> dict:
    """Two turns against a temporary llama-server; see cache_reused()."""
    env = dict(os.environ, LD_LIBRARY_PATH=runtime_dir)
    log = tempfile.NamedTemporaryFile("w+", prefix="moe-bench-server-", suffix=".log", delete=False)
    proc = subprocess.Popen([os.path.join(runtime_dir, "llama-server"), "-m", model_path, "-c", "2048",
                             "-t", str(threads), "--host", "127.0.0.1", "--port", str(port), "--slots"],
                            env=env, stdout=log, stderr=subprocess.STDOUT)
    peak = None
    try:
        t0 = time.monotonic()
        while not _ready(port):
            if proc.poll() is not None or time.monotonic() - t0 > timeout:
                log.seek(0)
                return {"error": "llama-server did not come up: " + log.read()[-300:], "server_log": log.name}
            time.sleep(1)
        messages = [{"role": "user", "content": TURN1}]
        r1 = _post(port, "/v1/chat/completions", {"messages": messages, "max_tokens": 8, "temperature": 0}, timeout)
        peak = _vmhwm_mib(proc.pid)
        reply = r1["choices"][0]["message"]["content"]
        messages += [{"role": "assistant", "content": reply}, {"role": "user", "content": TURN2}]
        r2 = _post(port, "/v1/chat/completions", {"messages": messages, "max_tokens": 8, "temperature": 0}, timeout)
        peak = max(peak or 0, _vmhwm_mib(proc.pid) or 0) or None
        n1 = (r1.get("timings") or {}).get("prompt_n")
        n2 = (r2.get("timings") or {}).get("prompt_n")
        log.flush()
        log.seek(0)
        text = log.read()
        return {"prompt_n_turn1": n1, "prompt_n_turn2": n2, "cache_reused": cache_reused(n1, n2, text),
                "server_peak_rss_mib": peak, "server_log": log.name}
    except Exception as exc:
        return {"error": f"chat check failed: {exc}", "server_log": log.name}
    finally:
        proc.terminate()
        try:
            proc.wait(15)
        except subprocess.TimeoutExpired:
            proc.kill()


def ensure_file(entry: dict, dest_dir: str) -> str:
    """The model file, downloaded with verification when missing, its hash
    checked when present (a partial or wrong file must never be measured)."""
    from ai2.runtime import download_model, verify_model
    path = os.path.join(dest_dir, entry["file"])
    if not os.path.isfile(path):
        free = shutil.disk_usage(dest_dir).free
        if free < entry["bytes"] + DOWNLOAD_MARGIN:
            raise RuntimeError(f"{free // 2**20} MiB free in {dest_dir}, {entry['bytes'] // 2**20} MiB needed")
        print(f"  downloading {entry['file']} ({entry['bytes'] // 2**20} MiB) ...", flush=True)
        model = {"id": entry["id"], "label": entry["label"], "repo": entry["repo"], "file": entry["file"],
                 "sha256": entry["sha256"], "file_mb": file_mb(entry["bytes"])}
        path = download_model(model, dest_dir, progress=lambda d, t: print(f"\r  {d // 2**20} MiB", end="", flush=True))
        print()
    else:
        print(f"  verifying {entry['file']} ...", flush=True)
        if not verify_model(path, entry["sha256"]):
            raise RuntimeError(f"{path} does not match the expected SHA-256; delete it and run again")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--report", required=True)
    ap.add_argument("--runtime-dir")
    ap.add_argument("--dir")
    ap.add_argument("--candidates", default=",".join(c["id"] for c in CANDIDATES if not c.get("optional")))
    ap.add_argument("--reference", default=DEFAULT_REFERENCE)
    ap.add_argument("--threads", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--chat-check", choices=["hybrid", "all", "none"], default="hybrid")
    ap.add_argument("--pp", type=int, default=512)
    ap.add_argument("--ng", type=int, default=128)
    ap.add_argument("--timeout", type=int, default=7200, help="per step, seconds (a slow box needs hours)")
    ap.add_argument("--port", type=int, default=8098)
    a = ap.parse_args()

    from ai2.detect import detect
    from ai2.models import load_catalog
    from ai2.runtime import find_runtime, model_dir
    hw = detect()
    runtime_dir = a.runtime_dir or find_runtime(hw.cpu_variant)
    if not runtime_dir or not os.path.isfile(os.path.join(runtime_dir, "llama-bench")):
        print("error: no llama.cpp runtime (ai-2 runtime install, or --runtime-dir)", file=sys.stderr)
        return 1
    dest = a.dir or model_dir()
    os.makedirs(dest, exist_ok=True)
    wanted = [c for c in CANDIDATES if c["id"] in a.candidates.split(",")]
    catalog = {m["id"]: m for m in load_catalog()}
    comparisons = [dict(id=i, label=catalog[i]["label"], params_b=catalog[i]["params_b"], hybrid=False,
                        repo=catalog[i]["repo"], file=catalog[i]["file"], sha256=catalog[i]["sha256"],
                        bytes=catalog[i]["file_mb"] * 1_000_000, role="comparison")
                   for i in dict.fromkeys([a.reference] + COMPARISON_IDS) if i in catalog]
    print(f"moe-bench on {hw.cpu_model} ({hw.logical_cores} cores, {hw.ram_nominal_gib} GB), runtime {runtime_dir}, "
          f"{a.threads} threads, files in {dest}")
    print("Expect a long run on an old CPU: minutes to load each file and well under one token per second "
          "(see the header of this script); leave it running.")
    rows = []
    for entry in comparisons + wanted:
        row = {k: entry.get(k) for k in ("id", "label", "params_b", "active_b", "hybrid", "role", "license")}
        row.setdefault("role", "candidate")
        print(f"\n== {entry['label']}", flush=True)
        try:
            path = ensure_file(entry, dest)
        except Exception as exc:
            row["error"] = str(exc)
            rows.append(row)
            print(f"  skipped: {exc}")
            continue
        row["file_mib"] = os.path.getsize(path) // 2**20
        t0 = time.monotonic()
        row.update(bench(runtime_dir, path, a.threads, a.pp, a.ng, a.timeout))
        print(f"  bench: tg {row.get('tg')} pp {row.get('pp')} peak {row.get('peak_rss_mib')} MiB "
              f"({int(time.monotonic() - t0)} s)" + (f"  ERROR {row['error']}" if row.get("error") else ""))
        if a.chat_check == "all" or (a.chat_check == "hybrid" and entry.get("hybrid")):
            t0 = time.monotonic()
            row.update(chat_check(runtime_dir, path, a.threads, a.port, a.timeout))
            print(f"  chat: prompt_n turn1 {row.get('prompt_n_turn1')} turn2 {row.get('prompt_n_turn2')} "
                  f"cache reused {row.get('cache_reused')} server peak {row.get('server_peak_rss_mib')} MiB "
                  f"({int(time.monotonic() - t0)} s)" + (f"  ERROR {row['error']}" if row.get("error") else ""))
        rows.append(row)
    report = build_report(rows, a.reference, machine=f"{hw.cpu_model}, {hw.ram_nominal_gib} GB, {runtime_dir}")
    with open(a.report, "w") as fh:
        fh.write(report)
    print("\n" + report)
    print(f"report written to {a.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
