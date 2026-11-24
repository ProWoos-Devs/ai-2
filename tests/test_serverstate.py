"""`ai-2 stop` must never leave the engine running, whatever started the
wrapper and whatever version of it is running."""
import os
import signal
import stat
import subprocess
import sys
import textwrap
import time

from ai2 import serverstate

CODE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Stand-in for a llama-server that never stops on SIGTERM (a model load stuck
# on a slow disk). It writes a file once its handler is in place.
STUBBORN_SERVER = textwrap.dedent('''\
    #!/usr/bin/env python3
    import os, signal, time
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ready"), "w") as f:
        f.write(str(os.getpid()))
    while True:
        time.sleep(0.1)
''')

# A wrapper as 0.29.5 behaved on a second SIGTERM, at its worst. It writes the
# record, starts the engine and exits on any SIGTERM without stopping it.
OLD_WRAPPER = textwrap.dedent('''\
    import os, subprocess, sys
    from ai2 import serverstate
    rt = sys.argv[1]
    proc = subprocess.Popen([os.path.join(rt, "llama-server")])
    serverstate.write_server(os.getpid(), "t", "m.gguf", 19302, "127.0.0.1")
    proc.wait()
''')

# A wrapper wedged so deep it ignores SIGTERM, so only the kill by pid that
# follows the SIGKILL of the wrapper can stop its engine.
DEAF_WRAPPER = textwrap.dedent('''\
    import os, signal, subprocess, sys, time
    from ai2 import serverstate
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    rt = sys.argv[1]
    proc = subprocess.Popen([os.path.join(rt, "llama-server")])
    serverstate.write_server(os.getpid(), "t", "m.gguf", 19303, "127.0.0.1")
    while True:
        time.sleep(0.1)
''')


def _runtime_dir(tmp_path):
    d = tmp_path / "rt"
    d.mkdir()
    p = d / "llama-server"
    p.write_text(STUBBORN_SERVER)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return d


def _gone(pid):
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] == "Z"
    except OSError:
        return True


def _start(tmp_path, monkeypatch, args):
    """Start a wrapper in the test's own process group (no new session, as
    when `ai-2 serve` is run from a script), and wait for its engine."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    rt = _runtime_dir(tmp_path)
    env = dict(os.environ, PYTHONPATH=CODE, XDG_STATE_HOME=str(tmp_path / "state"))
    wrapper = subprocess.Popen([sys.executable, "-c", *args(rt)], env=env)
    ready = rt / "ready"
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not (ready.exists() and ready.read_text()
                                                   and serverstate.read_server()):
            time.sleep(0.1)
        assert ready.exists() and serverstate.read_server(), "the stub engine never started"
        assert os.getpgid(wrapper.pid) != wrapper.pid
        return wrapper, int(ready.read_text())
    except BaseException:
        # the stub ignores SIGTERM and loops forever, so never leave it behind
        engine = int(ready.read_text()) if ready.exists() and ready.read_text() else 0
        for pid in (wrapper.pid, engine):
            if pid > 0 and not _gone(pid):
                os.kill(pid, signal.SIGKILL)
        wrapper.wait()
        raise


def _stop_and_check(wrapper, child, grace_s=5.0):
    try:
        assert serverstate.stop_server(timeout_s=2, kill_after_s=3, grace_s=grace_s) is True
        wrapper.wait(timeout=5)
        deadline = time.monotonic() + 3          # init reaps the orphan, if any
        while time.monotonic() < deadline and not _gone(child):
            time.sleep(0.1)
        assert _gone(child), "the engine outlived `ai-2 stop`"
        assert serverstate.read_server() is None
    finally:
        for pid in (wrapper.pid, child):
            if pid > 0 and not _gone(pid):
                os.kill(pid, signal.SIGKILL)
        if wrapper.poll() is None:
            wrapper.wait()


def test_stop_reaps_the_engine_of_a_wrapper_that_does_not_lead_its_group(tmp_path, monkeypatch):
    """`ai-2 serve` from a script is not a process-group leader, so the
    SIGKILL at the deadline took the wrapper alone, just as its own 30 s wait
    for the engine ended, and left llama-server running."""
    code = lambda rt: [(f"from ai2 import runtime\n"
                        f"runtime.serve(r'{rt}', 'm.gguf', threads=1, port=19301, "
                        f"idle_timeout_s=600, model_id='t')\n")]
    wrapper, child = _start(tmp_path, monkeypatch, code)
    _stop_and_check(wrapper, child)


def test_stop_reaps_the_engine_an_older_wrapper_leaves_behind(tmp_path, monkeypatch):
    """A wrapper still running older code after an upgrade can exit on
    SIGTERM without stopping the engine."""
    wrapper, child = _start(tmp_path, monkeypatch, lambda rt: [OLD_WRAPPER, str(rt)])
    _stop_and_check(wrapper, child)


def test_stop_kills_the_engine_of_a_wrapper_that_ignores_sigterm(tmp_path, monkeypatch):
    """Neither SIGTERM reaches a wedged wrapper, and SIGKILL of a wrapper that
    does not lead its group takes the wrapper alone, so the engine is killed
    by its own pid."""
    wrapper, child = _start(tmp_path, monkeypatch, lambda rt: [DEAF_WRAPPER, str(rt)])
    _stop_and_check(wrapper, child, grace_s=0.5)


def test_children_ignores_ones_in_a_session_of_their_own():
    """The Gopher server's engines are started in their own session and have
    their own records; stopping the Gopher server must not SIGKILL them."""
    same = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    own = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                           start_new_session=True)
    try:
        found = [pid for pid, _ in serverstate._children(os.getpid())]
        assert same.pid in found and own.pid not in found
    finally:
        for p in (same, own):
            p.kill()
            p.wait()
