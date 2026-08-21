"""Runtime Engine, locates the CPU-variant llama.cpp build and drives it.

Today the binaries are placed manually (proven on RMM-PC in ~/llama). Once the
signed AI-2 pacman repo exists, install_runtime() will pull the right variant
package (llama.cpp-baseline / -noavx / -avx2) for hw.cpu_variant; the finder
below already prefers a per-variant path so that transition is a drop-in.
"""

from __future__ import annotations

import glob
import os
import subprocess

# Searched in order; first dir containing a llama-bench wins.
def _runtime_candidates(variant: str) -> list[str]:
    return [
        os.environ.get("AI2_RUNTIME_DIR", ""),
        f"/usr/lib/ai2/runtimes/llama.cpp-{variant}",
        "/opt/ai2/llama",
        os.path.expanduser("~/llama"),
    ]


def find_runtime(variant: str) -> str | None:
    for d in _runtime_candidates(variant):
        if d and os.path.isfile(os.path.join(d, "llama-bench")):
            return d
    return None


# Searched in order; smallest gguf is used as the benchmark's fixed workload.
_MODEL_DIRS = [
    os.environ.get("AI2_MODEL_DIR", ""),
    "/var/lib/ai2/models",
    os.path.expanduser("~/.local/share/ai2/models"),   # where `ai-2 model pull` puts them as a user
    os.path.expanduser("~/models"),
]


def find_test_model() -> str | None:
    env = os.environ.get("AI2_TEST_MODEL")
    if env and os.path.isfile(env):
        return env
    ggufs: list[str] = []
    for d in _MODEL_DIRS:
        if d and os.path.isdir(d):
            ggufs += glob.glob(os.path.join(d, "*.gguf"))
    if not ggufs:
        return None
    return min(ggufs, key=os.path.getsize)


def run_llama_bench(runtime_dir: str, model: str, threads: int,
                    pp: int = 32, ng: int = 32, timeout: int = 600) -> str:
    """Run llama-bench and return its stdout (markdown table). Raises on failure."""
    env = dict(os.environ, LD_LIBRARY_PATH=runtime_dir)
    cmd = [
        os.path.join(runtime_dir, "llama-bench"),
        "-m", model, "-p", str(pp), "-n", str(ng),
        "-r", "1", "-t", str(threads), "-o", "md",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"llama-bench failed (exit {proc.returncode}): "
                           f"{proc.stderr.strip()[:300]}")
    return proc.stdout


# ---------------------------------------------------------------------------
# Closing the loop: install the runtime, fetch the model, serve on demand.

# One package per CPU class in the signed [ai2] repo (see packaging/).
RUNTIME_PACKAGES = {
    "baseline": "ai2-llama-cpp-baseline",
    "noavx": "ai2-llama-cpp-noavx",
    "avx2": "ai2-llama-cpp-avx2",
}


def runtime_package(variant: str) -> str | None:
    return RUNTIME_PACKAGES.get(variant)


def model_dir() -> str:
    """Where models live: the system dir when writable (root), else the user's."""
    env = os.environ.get("AI2_MODEL_DIR")
    if env:
        return env
    if os.access("/var/lib/ai2", os.W_OK) or os.geteuid() == 0:
        return "/var/lib/ai2/models"
    return os.path.expanduser("~/.local/share/ai2/models")


def find_model_file(filename: str) -> str | None:
    for d in _MODEL_DIRS + [model_dir()]:
        if d and os.path.isfile(os.path.join(d, filename)):
            return os.path.join(d, filename)
    return None


def hf_url(model: dict) -> str:
    return f"https://huggingface.co/{model['repo']}/resolve/main/{model['file']}"


def download_model(model: dict, dest_dir: str | None = None,
                   progress=None) -> str:
    """Download a catalog model (Hugging Face) into dest_dir, verifying the
    byte count against Content-Length. Downloads to a .part file first, so an
    interrupted transfer never leaves a truncated .gguf behind. Returns the
    final path; if the file already exists it is left alone."""
    import urllib.request

    dest_dir = dest_dir or model_dir()
    os.makedirs(dest_dir, exist_ok=True)
    final = os.path.join(dest_dir, model["file"])
    if os.path.isfile(final):
        return final
    part = final + ".part"
    req = urllib.request.Request(hf_url(model), headers={"User-Agent": "ai-2"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(part, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    size = os.path.getsize(part)
    if total and size != total:
        os.remove(part)
        raise RuntimeError(f"download incomplete: got {size} of {total} bytes")
    os.replace(part, final)
    return final


def serve(runtime_dir: str, model_path: str, threads: int, ctx: int = 2048,
          host: str = "127.0.0.1", port: int = 8080,
          idle_timeout_s: int | None = 600, api_key: str | None = None,
          startup_grace_s: int = 900, model_id: str = "",
          extra_args: list[str] | None = None) -> int:
    """Run llama-server in the foreground and stop it after idle_timeout_s
    seconds without any request in flight (the tier's `service: on-demand`
    semantics). Returns the server's exit code.

    Idle accounting fails CLOSED: once the server has answered a poll, a poll
    failure counts as idle time (the old behavior reset the idle clock on every
    error, so one transient failure kept the model resident forever, found in
    the 2026-08-21 review). Before the first successful poll the clock is held
    for at most startup_grace_s (a cold HDD load can take minutes)."""
    import json
    import time
    import urllib.request

    from . import serverstate

    env = dict(os.environ, LD_LIBRARY_PATH=runtime_dir)
    cmd = [os.path.join(runtime_dir, "llama-server"), "-m", model_path,
           "-t", str(threads), "-c", str(ctx), "--host", host, "--port", str(port),
           "--slots"]
    if api_key:
        cmd += ["--api-key", api_key]
    cmd += list(extra_args or [])
    proc = subprocess.Popen(cmd, env=env)
    serverstate.write_server(os.getpid(), model_id, model_path, port, host)
    started = time.monotonic()
    last_busy = started
    seen_up = False
    poll_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        while True:
            try:
                rc = proc.wait(timeout=5)
                return rc
            except subprocess.TimeoutExpired:
                pass
            if idle_timeout_s is None:
                continue
            now = time.monotonic()
            try:
                req = urllib.request.Request(f"http://{poll_host}:{port}/slots", headers=headers)
                with urllib.request.urlopen(req, timeout=2) as r:
                    slots = json.load(r)
                seen_up = True
                if any(s.get("is_processing") for s in slots):
                    last_busy = now
            except Exception:
                if not seen_up and now - started < startup_grace_s:
                    last_busy = now       # still loading, do not count as idle
                # otherwise the failure counts as idle time (fail closed)
            if now - last_busy >= idle_timeout_s:
                proc.terminate()
                return proc.wait(timeout=30)
    except KeyboardInterrupt:
        proc.terminate()
        return proc.wait(timeout=30)
    finally:
        serverstate.clear_server()
