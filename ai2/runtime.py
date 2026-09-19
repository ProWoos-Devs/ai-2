"""Runtime Engine, locates the llama.cpp build and drives it.

One runtime package, ai2-llama-cpp, ships one llama.cpp built for plain
x86-64 plus one CPU backend module per instruction-set level
(libggml-cpu-<variant>.so); ggml scores every module against the CPU at start
and loads the best, x64 always qualifying. hw.cpu_variant (baseline / noavx /
avx2) stays as AI-2's own coarse class for the record and the wizard text;
which module actually ran is read from llama-bench's log line
"load_backend: loaded CPU backend from <path>" and stored with the score.
Until 10398-1 there were three packages, one full build each, in
/usr/lib/ai2/runtimes/llama.cpp-<variant>/; the finder still accepts those
directories so a machine that has not swapped yet keeps working.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import sys

RUNTIME_DIR = "/usr/lib/ai2/runtimes/llama.cpp"


# Searched in order; first dir containing a llama-bench wins.
def _runtime_candidates(variant: str) -> list[str]:
    return [
        os.environ.get("AI2_RUNTIME_DIR", ""),
        RUNTIME_DIR,
        f"/usr/lib/ai2/runtimes/llama.cpp-{variant}",   # the 10398-1 per-CPU packages
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
def user_model_dir() -> str:
    """Where `ai-2 model pull` puts models for a user, under the same data
    directory as the documents index (doc.data_dir()). It follows
    XDG_DATA_HOME: a scratch run that redirects XDG must not download 85 MB
    into the real home, which is what happened on 2026-09-18."""
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "ai2", "models")


def _model_dirs() -> list[str]:
    return [
        os.environ.get("AI2_MODEL_DIR", ""),
        "/var/lib/ai2/models",
        user_model_dir(),
        os.path.expanduser("~/models"),
    ]


def find_benchmark_model() -> str | None:
    """The fixed benchmark model, if it is on disk. The AI Score is measured on
    this and only this, so it stays comparable across machines."""
    from .models import benchmark_model, load_catalog
    return find_model_file(benchmark_model(load_catalog())["file"])


BENCH_TIMEOUT_S = {"baseline": 300, "noavx": 240, "avx2": 150}   # the plan's 1-2 min budget, wider on weak CPUs


LOADED_BACKEND_RE = re.compile(r"load_backend: loaded (\S+) backend from (\S+)")


def loaded_backends(stderr: str) -> dict[str, str]:
    """{backend name: module file} from ggml's log lines, printed
    unconditionally when a dynamic backend is loaded (ggml-backend-reg.cpp).
    A CPU entry names the variant that won the score, e.g. {"CPU":
    "libggml-cpu-haswell.so"}; a static build prints nothing."""
    return {m.group(1): os.path.basename(m.group(2)) for m in LOADED_BACKEND_RE.finditer(stderr or "")}


def cpu_variant_loaded(stderr: str) -> str | None:
    """The CPU variant name (x64, sse42, haswell, ...) that ggml loaded, or
    None when the log does not say (a static build, or an old package)."""
    mod = loaded_backends(stderr).get("CPU")
    if not mod:
        return None
    m = re.fullmatch(r"libggml-cpu(?:-(.+))?\.so", mod)
    return (m.group(1) or "static") if m else mod


def run_llama_bench(runtime_dir: str, model: str, threads: int,
                    pp: int = 32, ng: int = 32, reps: int = 2, timeout: int | None = None,
                    variant: str = "baseline", fmt: str = "json", info: dict | None = None) -> str:
    """Run llama-bench and return its stdout (JSON by default, markdown with
    fmt="md"). Time-boxed per CPU class so a weak machine does not sit in the
    benchmark for ten minutes; raises on failure or timeout. When `info` is
    given, info["stderr"] receives llama-bench's log, where ggml names the
    backend module it loaded."""
    env = dict(os.environ, LD_LIBRARY_PATH=runtime_dir)
    cmd = [
        os.path.join(runtime_dir, "llama-bench"),
        "-m", model, "-p", str(pp), "-n", str(ng),
        "-r", str(reps), "-t", str(threads), "-o", fmt,
    ]
    timeout = timeout or BENCH_TIMEOUT_S.get(variant, 300)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"llama-bench did not finish within {timeout} s; this machine is "
                           f"below what AI-2 can measure in its time budget")
    if info is not None:
        info["stderr"] = proc.stderr
    if proc.returncode != 0:
        raise RuntimeError(f"llama-bench failed (exit {proc.returncode}): "
                           f"{proc.stderr.strip()[:300]}")
    return proc.stdout


# ---------------------------------------------------------------------------
# Closing the loop: install the runtime, fetch the model, serve on demand.

# One package for every CPU class in the signed [ai2] repo (see packaging/);
# the per-class map is kept so callers keep asking by variant.
RUNTIME_PACKAGE = "ai2-llama-cpp"
RUNTIME_PACKAGES = {v: RUNTIME_PACKAGE for v in ("baseline", "noavx", "avx2")}
# The packages this one replaced (10398-1); doctor names them when they linger.
OLD_RUNTIME_PACKAGES = {v: f"ai2-llama-cpp-{v}" for v in ("baseline", "noavx", "avx2")}


def runtime_package(variant: str) -> str | None:
    return RUNTIME_PACKAGES.get(variant)


def model_dir() -> str:
    """Where models live: the system dir when writable (root), else the user's."""
    env = os.environ.get("AI2_MODEL_DIR")
    if env:
        return env
    if os.access("/var/lib/ai2", os.W_OK) or os.geteuid() == 0:
        return "/var/lib/ai2/models"
    return user_model_dir()


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

    from .safefetch import is_safe_url, opener

    url = hf_url(model)
    if not is_safe_url(url):
        raise RuntimeError(f"refusing to download {model.get('file', '')} over {url.split(':')[0]}: "
                           "a model download must be https")
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
    req = urllib.request.Request(url, headers=headers)
    try:
        # the same rule as a knowledge pack: a redirect (Hugging Face sends
        # every file to a CDN) may not drop out of HTTPS
        resp = opener().open(req, timeout=60)
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


SAMPLING_FLAGS = {"temp": "--temp", "top_k": "--top-k", "top_p": "--top-p",
                  "min_p": "--min-p", "repeat_penalty": "--repeat-penalty"}


def sampling_args(model: dict) -> list[str]:
    """llama-server flags for the catalog entry's optional `sampling` block
    (the values the model card recommends). Unknown keys are ignored so a
    catalog typo cannot stop the server from starting."""
    out: list[str] = []
    for key, value in (model.get("sampling") or {}).items():
        flag = SAMPLING_FLAGS.get(key)
        if flag is not None:
            out += [flag, str(value)]
    return out


def _is_timeout(exc: BaseException) -> bool:
    """A poll that timed out (connect or read), as urllib reports it."""
    import socket
    import urllib.error
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    return isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, (TimeoutError, socket.timeout))


def _shutdown(proc) -> int:
    """Terminate llama-server and really wait it out; escalate to SIGKILL if
    it ignores SIGTERM (a model loading from a slow disk can hang a while)."""
    proc.terminate()
    try:
        return proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.wait(timeout=10)


def _poll_url(host: str, port: int) -> str:
    """The wrapper's own poll of llama-server's /slots. A wildcard bind is
    reached through loopback, and an IPv6 literal must be bracketed in a URL:
    `http://::1:8080/` is not a URL and urlopen refuses it, which made a
    `--host ::1` server look permanently down and get shut down as idle
    (2026-09-03 review)."""
    poll_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    if ":" in poll_host:
        poll_host = f"[{poll_host}]"
    return f"http://{poll_host}:{port}/slots"


def serve(runtime_dir: str, model_path: str, threads: int, ctx: int = 2048,
          host: str = "127.0.0.1", port: int = 8080,
          idle_timeout_s: int | None = 600, api_key: str | None = None,
          startup_grace_s: int = 900, model_id: str = "",
          extra_args: list[str] | None = None, record: str = "server") -> int:
    """Run llama-server in the foreground and stop it after idle_timeout_s
    seconds without any request in flight (the tier's `service: on-demand`
    semantics). Returns the server's exit code.

    Idle accounting fails CLOSED: once the server has answered a poll, a poll
    failure counts as idle time (the old behavior reset the idle clock on every
    error, so one transient failure kept the model resident forever, found in
    the 2026-08-21 review). Before the first successful poll the clock is held
    for at most startup_grace_s (a cold HDD load can take minutes).

    One exception, a poll that TIMES OUT counts as busy. llama-server answers
    /slots from the same loop that runs the model, so while it chews on a long
    batch (an embedding batch, or a 900-token prompt at 1.5 tok/s on the
    validated laptops) it cannot answer for minutes; those timeouts were
    counted as idle and the wrapper killed the server in the middle of an
    `ai-2 doc index` on rafaminu-pc (2026-09-14). A dead server refuses the
    connection instead of timing out, so failing closed still holds for it."""
    import json
    import signal
    import socket
    import time
    import urllib.error
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
    # `ai-2 stop` sends SIGTERM to THIS wrapper process. Python's default
    # SIGTERM action kills it without running except/finally, which orphaned
    # llama-server with all its RAM (found on the 2011 laptop 2026-08-23).
    # Turn SIGTERM into SystemExit so the shutdown path below runs.
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(143))
    serverstate.write_server(os.getpid(), model_id, model_path, port, host, name=record)
    started = time.monotonic()
    last_busy = started
    seen_up = False
    poll_url = _poll_url(host, port)
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
                req = urllib.request.Request(poll_url, headers=headers)
                with urllib.request.urlopen(req, timeout=2) as r:
                    slots = json.load(r)
                seen_up = True
                if any(s.get("is_processing") for s in slots):
                    last_busy = now
            except Exception as exc:
                if _is_timeout(exc):
                    last_busy = now       # too busy to answer: working, not idle
                elif not seen_up and now - started < startup_grace_s:
                    last_busy = now       # still loading, do not count as idle
                # otherwise the failure counts as idle time (fail closed)
            if now - last_busy >= idle_timeout_s:
                return _shutdown(proc)
    except (KeyboardInterrupt, SystemExit):
        return _shutdown(proc)
    finally:
        serverstate.clear_server(record)
