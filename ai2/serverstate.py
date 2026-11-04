"""Where the on-demand servers record themselves (pid, model, port), so `ai-2
chat` can tell which model is loaded, `ai-2 stop` can free the RAM, and `ai-2
doctor` can report it. One small JSON file per server per user in the state
dir: the chat server (the default record, "server"), the embedding server
`ai-2 doc` starts (EMBED), which loads a different model on another port, and
the Gopher server AI-2 Chat starts for the app (GOPHER), which loads no model."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import sys

CHAT = "server"
EMBED = "embed"
GOPHER = "gopher"
LOG_NAMES = {CHAT: "serve.log", EMBED: "embed.log", GOPHER: "gopher.log"}


def state_dir() -> str:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "ai2")


def server_file(name: str = CHAT) -> str:
    return os.path.join(state_dir(), f"{name}.json")


def log_file(name: str = CHAT) -> str:
    return os.path.join(state_dir(), LOG_NAMES.get(name, f"{name}.log"))


def write_server(pid: int, model_id: str, model_path: str, port: int, host: str,
                 name: str = CHAT) -> None:
    os.makedirs(state_dir(), exist_ok=True)
    # replaced in one step, so a reader never meets half a record
    tmp = f"{server_file(name)}.{os.getpid()}.tmp"
    with open(tmp, "w") as fh:
        json.dump({"pid": pid, "model": model_id, "model_path": model_path,
                   "port": port, "host": host}, fh)
    os.replace(tmp, server_file(name))


@contextlib.contextmanager
def start_lock(name: str = CHAT):
    """Only one command at a time starts this server: two starting together
    would load the model twice and fight over the port. The second waits, then
    finds the server up. The kernel drops the lock if the holder dies, and a
    started server does not inherit it (Python's files are not inheritable)."""
    import fcntl
    os.makedirs(state_dir(), exist_ok=True)
    with open(os.path.join(state_dir(), f"{name}.lock"), "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another AI-2 command is starting the AI, waiting for it ...", file=sys.stderr, flush=True)
            fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def clear_server(name: str = CHAT) -> None:
    try:
        os.remove(server_file(name))
    except OSError:
        pass


def _alive(pid: int) -> bool:
    if pid <= 0:
        # kill(0, sig) is the caller's own process group and kill(-1, sig) is
        # everything; a state file without a pid must never lead there.
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def read_server(name: str = CHAT) -> dict | None:
    """The running server's record, or None (a stale file is removed)."""
    try:
        with open(server_file(name)) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not _alive(int(data.get("pid", 0))):
        clear_server(name)
        return None
    return data


def stop_server(timeout_s: float = 30.0, kill_after_s: float = 10.0, name: str = CHAT) -> bool:
    """SIGTERM the recorded server, SIGKILL it if it is still there after
    timeout_s (the wrapper's own shutdown can wedge behind a model load in
    uninterruptible I/O), and only then drop the record, so a second `ai-2
    stop` never says "nothing running" while the RAM is still held. Returns
    True if one was running."""
    import time
    data = read_server(name)
    if not data:
        return False
    pid = int(data["pid"])
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        clear_server(name)
        return False
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and _alive(pid):
        time.sleep(0.5)
    if _alive(pid):
        # The wrapper leads its own process group when `ai-2 chat` started it
        # (start_new_session); killing the group takes llama-server with it.
        try:
            if os.getpgid(pid) == pid:
                os.killpg(pid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        deadline = time.monotonic() + kill_after_s
        while time.monotonic() < deadline and _alive(pid):
            time.sleep(0.2)
    clear_server(name)
    return True
