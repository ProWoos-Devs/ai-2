"""Starting and reaching the on-demand llama-server, and the model catalog
entries the commands share.

`ai-2 chat`, `ai-2 doc` and `ai-2 knowledge` all need the same few things: is
a server answering on that port, start one and wait for it, which catalog
entry is this id, download this model. They lived in cli.py, which meant that
splitting the knowledge commands out of it would have made that module import
cli, and `python -m ai2.cli` (which is how a server is started) would then
execute cli twice. They belong to neither command area, so they are here.
"""

from __future__ import annotations

import os
import sys

from . import serverstate
from .models import load_catalog
from .runtime import download_model, download_preflight, find_model_file, find_runtime, model_dir


SPEECH_PREFIX = "whisper-"


def _speech_entries() -> list[dict]:
    """The speech models as `ai-2 model` sees them: the same files, ids
    prefixed so nothing confuses one with a chat model. The two catalogs stay
    separate on purpose (everything that reads models.yml treats an entry as
    a chat model), but the files are 44 to 265 MB in the same directory and
    `ai-2 model list|rm|verify` could not see them at all."""
    from . import speech
    return [dict(m, id=SPEECH_PREFIX + m["id"], kind="speech") for m in speech.load_catalog()]


def _catalog_entry(model_id: str) -> dict | None:
    """Any catalog entry by id, embedders and speech models included (pull, rm
    and verify take them; serve and chat check the kind themselves). A speech
    model answers to `whisper-base` and to the bare `base` that
    `ai-2 transcribe --model` uses."""
    found = next((m for m in load_catalog(kind=None) if m["id"] == model_id), None)
    if found is not None:
        return found
    wanted = model_id if model_id.startswith(SPEECH_PREFIX) else SPEECH_PREFIX + model_id
    return next((m for m in _speech_entries() if m["id"] == wanted), None)


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


def EMBED_IDLE_OR(defaults: dict) -> int:
    """The embedding server's idle timeout: the tier's, capped at doc.EMBED_IDLE_S,
    and never 'keep running' (0)."""
    from . import doc as docmod
    tier_idle = defaults.get("idle_timeout_s") or 0
    return min(tier_idle, docmod.EMBED_IDLE_S) if tier_idle else docmod.EMBED_IDLE_S


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


def _ensure_server(hw, model: dict, port: int, record: str, wait: int = 180,
                   idle_timeout: int | None = None) -> str | None:
    """The base URL of a running `ai-2 serve` for `model` on `port`: start it
    detached when nothing answers there (the same way `ai-2 chat` does), wait
    until it reports ready. None, with the reason printed, when it cannot."""
    import subprocess
    import time
    url = f"http://127.0.0.1:{port}/"
    running = serverstate.read_server(record)
    # a server that answers is only this one if it runs this model: an index
    # embedded with the wrong model is wrong without any error
    if _server_ready(url) and not (running and running.get("model") and running["model"] != model["id"]):
        return url
    if running and running.get("model") and running["model"] != model["id"]:
        print(f"error: a server is already running with {running['model']}, not {model['id']}. "
              f"Stop it first:  ai-2 stop", file=sys.stderr)
        return None
    if find_runtime(hw.cpu_variant) is None or find_model_file(model["file"]) is None:
        print("AI-2 is not set up on this computer yet. Run:  ai-2 wizard", file=sys.stderr)
        return None
    state_dir = serverstate.state_dir()
    os.makedirs(state_dir, exist_ok=True)
    log = open(serverstate.log_file(record), "ab")
    cmd = [sys.executable, "-m", "ai2.cli", "serve", "--port", str(port), "--model", model["id"]]
    if idle_timeout is not None:
        cmd += ["--idle-timeout", str(idle_timeout)]
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
                     cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print(f"Starting {model['label']} ... this takes a moment on a slow disk", flush=True)
    start = time.monotonic()
    last_note = start
    while time.monotonic() < start + wait and not _server_ready(url):
        time.sleep(2)
        if time.monotonic() - last_note >= 10:
            last_note = time.monotonic()
            print(f"  still starting ({int(last_note - start)} s)", flush=True)
    if not _server_ready(url):
        print(f"error: the server did not come up within {wait} s (see {serverstate.log_file(record)})",
              file=sys.stderr)
        return None
    return url
