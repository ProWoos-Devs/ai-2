"""The model's reading of AI-2's own instructions, kept on disk. Every chat opens
with them, and reading them took 54 s of the 65 s from a stopped model to the
first word on the 2011 laptop. Restored from a 1.5 MB file it took 0.11 s, and
that first word came after 18 s (RMM-PC, 2026-11-04).

The file holds the instructions and one fixed word, never anything a person
wrote, so deleting a conversation leaves nothing behind here. It is made once,
the first time the server has been idle after real use, so it does not compete
with someone waiting. Anything that goes wrong only means the model reads as it
always did."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request

SLOT = 0
IDLE_BEFORE_MAKING = 30       # seconds with nothing to do after real use
POLL = 5
UP_POLL = 0.25                # the first question may be waiting for this server: restore before it


def state_dir() -> str | None:
    """The folder, which must exist before llama-server starts: it refuses to
    start without it. None when it cannot be made, and then there is no saved
    start, nothing worse."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    path = os.path.join(base, "ai2", "prompt-state") + os.sep
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
    except OSError:
        return None
    return path


def file_name(model_id: str, model_path: str, system: str, ctx: int, batch: int, server_binary: str) -> str:
    """Changes with anything that makes an old file wrong, so an old one is never read."""
    try:
        st = os.stat(server_binary)
        binary = f"{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        binary = "?"
    mark = "\0".join((os.path.basename(model_path), system, str(ctx), str(batch), binary))
    return f"{model_id or 'model'}-{hashlib.sha256(mark.encode()).hexdigest()[:16]}.bin"


def _http(base: str, path: str, body: dict | None, timeout: float):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


class WarmStart:
    def __init__(self, base_url: str, directory: str, name: str, system: str, call=None, sleep=time.sleep):
        self.dir = directory
        self.name = name
        self.system = system
        self.call = call or (lambda path, body, timeout: _http(base_url.rstrip("/"), path, body, timeout))
        self.sleep = sleep
        self.clock = time.monotonic

    def start(self) -> None:
        threading.Thread(target=self.run, daemon=True).start()

    def run(self) -> None:
        try:
            self._wait_until_up()
            path = os.path.join(self.dir, self.name)
            if os.path.exists(path):
                self._restore(path)
            else:
                self._wait_for_a_quiet_moment()
                self._make(path)
        except Exception as exc:                  # never more than a slower first question
            print(f"The AI's saved start was not used ({exc}).", flush=True)

    def _wait_until_up(self) -> None:
        while True:
            try:
                self.call("/slots", None, 2)
                return
            except Exception:
                self.sleep(UP_POLL)

    def _restore(self, path: str) -> None:
        try:
            self.call(f"/slots/{SLOT}?action=restore", {"filename": self.name}, 30)
        except urllib.error.HTTPError:            # refused: not a file this server can use
            os.remove(path)
            raise

    def _wait_for_a_quiet_moment(self) -> None:
        used = False
        quiet = None
        while True:
            try:
                busy = any(s.get("is_processing") for s in self.call("/slots", None, 2))
            except Exception:                     # too busy to answer
                busy = True
            if busy:
                used, quiet = True, None
            elif used:
                quiet = self.clock() if quiet is None else quiet
                if self.clock() - quiet >= IDLE_BEFORE_MAKING:
                    return
            self.sleep(POLL)

    def _make(self, path: str) -> None:
        self.call("/v1/chat/completions",
                  {"messages": [{"role": "system", "content": self.system}, {"role": "user", "content": "Hello"}],
                   "max_tokens": 1, "cache_prompt": True, "id_slot": SLOT}, 1800)
        self.call(f"/slots/{SLOT}?action=save", {"filename": self.name}, 30)
        prefix = self.name.rsplit("-", 1)[0] + "-"
        for other in os.listdir(self.dir):
            if other.startswith(prefix) and other != self.name:
                os.remove(os.path.join(self.dir, other))
