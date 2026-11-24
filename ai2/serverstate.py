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
EMBED2 = "embed2"            # a second search model beside the first, when memory allows (doc.EMBED_PORT2)
EMBED_SLOTS = (EMBED, EMBED2)
GOPHER = "gopher"
LOG_NAMES = {CHAT: "serve.log", EMBED: "embed.log", EMBED2: "embed2.log", GOPHER: "gopher.log"}


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
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return not _exited(pid)


def _exited(pid: int) -> bool:
    """A process that has ended but whose parent has not collected it still
    answers kill(pid, 0). The Gopher server starts the engine and does not wait
    for it, so without this every stop waited out both of its time limits for
    a process that was already gone."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] == "Z"
    except (OSError, IndexError):
        return False


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


def _stat(pid: int) -> list[str] | None:
    """The fields of /proc/PID/stat after the command name (state first, then
    ppid, pgrp, ...), or None when the process is gone."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as fh:
            return fh.read().rsplit(")", 1)[1].split()
    except (OSError, IndexError):
        return None


def _children(pid: int) -> list[tuple[int, str]]:
    """The direct children of pid that share its process group, each with its
    start time so a reused pid is never mistaken for it later. That is the
    engine `ai-2 serve` runs. A child started in a session of its own (the
    engines the Gopher server starts) is left alone, since it has its own
    record and `ai-2 stop` stops it by that."""
    me = _stat(pid)
    if not me:
        return []
    found = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        fields = _stat(int(entry))
        if fields and len(fields) > 19 and fields[1] == str(pid) and fields[2] == me[2]:
            found.append((int(entry), fields[19]))
    return found


def _same_alive(pid: int, started: str) -> bool:
    fields = _stat(pid)
    return bool(fields) and len(fields) > 19 and fields[19] == started and fields[0] != "Z"


def stop_server(timeout_s: float = 30.0, kill_after_s: float = 10.0, name: str = CHAT,
                grace_s: float = 5.0) -> bool:
    """Stop the recorded server and the engine under it, and only then drop
    the record, so a second `ai-2 stop` never says "nothing running" while
    the RAM is still held. Returns True if one was running.

    SIGTERM first, then after timeout_s a second SIGTERM, which makes the
    wrapper kill and reap a slow engine at once. The wrapper's own wait for
    the engine is also 30 s, so a SIGKILL at that moment used to land just as
    it gave up, and when the wrapper did not lead its process group (`ai-2
    serve` started from a script) the SIGKILL took the wrapper alone and left
    llama-server running. A wrapper from 0.29.5 or older also exits on a
    second SIGTERM without killing the engine. So the engine's pid is taken
    before the first signal, and once the wrapper is gone, or after grace_s
    more, whatever is left is SIGKILLed, the wrapper (its group when it leads
    one) and the engine by pid. The worst case is timeout_s + grace_s +
    kill_after_s, 45 s by default; a process stuck in uninterruptible I/O can
    outlast even SIGKILL, and the record is dropped after that wait anyway."""
    import time
    data = read_server(name)
    if not data:
        return False
    pid = int(data["pid"])
    engines = _children(pid)

    def left() -> list[int]:
        return [c for c, started in engines if _same_alive(c, started)]

    def wait(seconds: float, engines_too: bool = False) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and (_alive(pid) or (engines_too and left())):
            time.sleep(0.2)

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        clear_server(name)
        return False
    wait(timeout_s)
    if _alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        wait(grace_s)
    if _alive(pid):
        # The wrapper leads its own process group when `ai-2 chat` started it
        # (start_new_session); killing the group takes the engine with it.
        try:
            if os.getpgid(pid) == pid:
                os.killpg(pid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    for child in left():
        try:
            os.kill(child, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    wait(kill_after_s, engines_too=True)
    clear_server(name)
    return True
