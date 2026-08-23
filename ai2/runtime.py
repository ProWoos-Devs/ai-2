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


# Searched in order; computed at call time so HOME/env changes (doctor under
# sudo looking at the invoking user) are honored.
def _model_dirs() -> list[str]:
    return [
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
    for d in _model_dirs():
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
    for d in _model_dirs() + [model_dir()]:
        if d and os.path.isfile(os.path.join(d, filename)):
            return os.path.join(d, filename)
    return None


def installed_models(catalog: list[dict]) -> list[dict]:
    """Every .gguf on disk: catalog entries with their path, plus unknown
    files found in the model directories (id None)."""
    out = []
    seen = set()
    for m in catalog:
        path = find_model_file(m["file"])
        if path:
            out.append({"id": m["id"], "label": m["label"], "path": path,
                        "size_mb": os.path.getsize(path) // (1024 * 1024), "catalog": m})
            seen.add(os.path.realpath(path))
    for d in _model_dirs() + [model_dir()]:
        if d and os.path.isdir(d):
            for f in sorted(glob.glob(os.path.join(d, "*.gguf"))):
                if os.path.realpath(f) not in seen:
                    seen.add(os.path.realpath(f))
                    out.append({"id": None, "label": os.path.basename(f), "path": f,
                                "size_mb": os.path.getsize(f) // (1024 * 1024), "catalog": None})
    return out


def verify_model(path: str, expected_sha256: str) -> bool:
    return _sha256_of(path).hexdigest() == expected_sha256.lower()


def hf_url(model: dict) -> str:
    return f"https://huggingface.co/{model['repo']}/resolve/main/{model['file']}"


DOWNLOAD_MARGIN_MB = 200


def download_preflight(model: dict, dest_dir: str | None = None) -> str | None:
    """Why a download of `model` into dest_dir would fail, or None if it looks
    fine. Checks free disk against file_mb plus a margin (the .part file and
    the final file never coexist, so one copy is enough)."""
    from .sysinfo import free_disk_mb
    dest_dir = dest_dir or model_dir()
    free = free_disk_mb(dest_dir)
    if free is None:
        return None
    part = os.path.join(dest_dir, model["file"] + ".part")
    have_mb = os.path.getsize(part) // (1024 * 1024) if os.path.isfile(part) else 0
    need = int(model.get("file_mb", 0)) - have_mb + DOWNLOAD_MARGIN_MB
    if free < need:
        return (f"not enough disk space in {dest_dir}: {free} MB free, "
                f"{model.get('file_mb', '?')} MB needed (plus {DOWNLOAD_MARGIN_MB} MB margin)")
    return None


def serve_preflight(model: dict) -> str | None:
    """A warning if the model's peak RAM exceeds what is available right now."""
    from .sysinfo import mem_available_mib
    avail = mem_available_mib()
    peak = int(model.get("ram_peak_mb", 0))
    if avail is None or not peak:
        return None
    if avail < peak:
        return (f"only {avail} MiB of RAM is free right now and {model.get('label', model.get('id'))} "
                f"peaks at about {peak} MiB; close other programs or expect swapping")
    return None


def _sha256_of(path: str, chunk: int = 1 << 20):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            data = fh.read(chunk)
            if not data:
                break
            h.update(data)
    return h


def download_model(model: dict, dest_dir: str | None = None,
                   progress=None) -> str:
    """Download a catalog model (Hugging Face) into dest_dir.

    Writes to a .part file first and resumes it with a Range request if a
    previous attempt was interrupted (old laptops on wifi, multi-GB files).
    Verifies the byte count against Content-Length and, when the catalog entry
    carries `sha256`, the hash of the whole file; a mismatch removes the file
    and raises. Returns the final path; an existing file is left alone."""
    import hashlib
    import urllib.error
    import urllib.request

    dest_dir = dest_dir or model_dir()
    os.makedirs(dest_dir, exist_ok=True)
    final = os.path.join(dest_dir, model["file"])
    if os.path.isfile(final):
        return final
    part = final + ".part"
    expected_sha = (model.get("sha256") or "").lower() or None

    have = os.path.getsize(part) if os.path.isfile(part) else 0
    hasher = _sha256_of(part) if (have and expected_sha) else hashlib.sha256()
    headers = {"User-Agent": "ai-2"}
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(hf_url(model), headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and have:
            # The server says our .part already covers the whole file.
            resp = None
        else:
            raise
    if resp is not None:
        with resp:
            if have and resp.status == 200:
                # Server ignored the Range header: start over.
                have = 0
                hasher = hashlib.sha256()
                mode = "wb"
            else:
                mode = "ab" if have else "wb"
            length = int(resp.headers.get("Content-Length") or 0)
            total = have + length if length else 0
            done = have
            with open(part, mode) as out:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
                    hasher.update(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        size = os.path.getsize(part)
        if total and size != total:
            # Keep the .part so the next attempt resumes instead of restarting.
            raise RuntimeError(f"download incomplete: got {size} of {total} bytes "
                               f"(run the same command again to resume)")
    if expected_sha:
        got = hasher.hexdigest() if hasher else _sha256_of(part).hexdigest()
        if got != expected_sha:
            os.remove(part)
            raise RuntimeError(f"checksum mismatch for {model['file']}: expected "
                               f"{expected_sha[:12]}..., got {got[:12]}... (file removed)")
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
