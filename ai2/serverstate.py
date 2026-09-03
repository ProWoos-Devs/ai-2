"""Where the on-demand server records itself (pid, model, port), so `ai-2 chat`
can tell which model is loaded, `ai-2 stop` can free the RAM, and `ai-2 doctor`
can report it. One small JSON file per user in the state dir."""

from __future__ import annotations

import json
import os
import signal


def state_dir() -> str:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "ai2")


def server_file() -> str:
    return os.path.join(state_dir(), "server.json")


def log_file() -> str:
    return os.path.join(state_dir(), "serve.log")


def write_server(pid: int, model_id: str, model_path: str, port: int, host: str) -> None:
    os.makedirs(state_dir(), exist_ok=True)
    with open(server_file(), "w") as fh:
        json.dump({"pid": pid, "model": model_id, "model_path": model_path,
                   "port": port, "host": host}, fh)


def clear_server() -> None:
    try:
        os.remove(server_file())
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


def read_server() -> dict | None:
    """The running server's record, or None (a stale file is removed)."""
    try:
        with open(server_file()) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not _alive(int(data.get("pid", 0))):
        clear_server()
        return None
    return data


def stop_server(timeout_s: float = 30.0, kill_after_s: float = 10.0) -> bool:
    """SIGTERM the recorded server, SIGKILL it if it is still there after
    timeout_s (the wrapper's own shutdown can wedge behind a model load in
    uninterruptible I/O), and only then drop the record, so a second `ai-2
    stop` never says "nothing running" while the RAM is still held. Returns
    True if one was running."""
    import time
    data = read_server()
    if not data:
        return False
    pid = int(data["pid"])
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        clear_server()
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
    clear_server()
    return True
