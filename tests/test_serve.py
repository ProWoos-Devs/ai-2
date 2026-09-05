"""The on-demand server's idle accounting and state file."""
import os
import stat
import textwrap

from ai2 import runtime, serverstate
from ai2.tiers import load_tiers, runtime_defaults

FAKE_SERVER = textwrap.dedent('''\
    #!/usr/bin/env python3
    # Stand-in for llama-server: answers /slots with an idle slot list.
    import http.server, sys
    port = int(sys.argv[sys.argv.index("--port") + 1])
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"[]" if self.path == "/slots" else b"{}"
            self.send_response(200); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def log_message(self, *a): pass
    http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
''')

DEAF_SERVER = "#!/bin/sh\nexec sleep 600\n"   # never answers a poll


def _runtime_dir(tmp_path, script):
    d = tmp_path / "rt"
    d.mkdir()
    p = d / "llama-server"
    p.write_text(script)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(d)


def test_idle_server_exits_after_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    rt = _runtime_dir(tmp_path, FAKE_SERVER)
    rc = runtime.serve(rt, "m.gguf", threads=1, port=18765, idle_timeout_s=3, model_id="t")
    assert rc in (0, -15)               # terminated by us after idling
    assert serverstate.read_server() is None   # state file cleared


def test_unreachable_server_counts_as_idle_after_grace(tmp_path, monkeypatch):
    # A server that never answers must not stay resident forever (fail closed).
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    rt = _runtime_dir(tmp_path, DEAF_SERVER)
    rc = runtime.serve(rt, "m.gguf", threads=1, port=18766, idle_timeout_s=2,
                       startup_grace_s=1, model_id="t")
    assert rc in (0, -15)
    assert serverstate.read_server() is None


def test_server_state_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    serverstate.write_server(os.getpid(), "qwen2.5-0.5b", "/x/m.gguf", 8080, "127.0.0.1")
    assert serverstate.read_server()["model"] == "qwen2.5-0.5b"
    serverstate.write_server(999999, "dead", "/x/m.gguf", 8080, "127.0.0.1")
    assert serverstate.read_server() is None   # stale pid removed


def test_runtime_defaults_follow_the_tier(tmp_path):
    tiers = load_tiers()
    tiny = runtime_defaults("qwen3-0.6b", tiers, tier_id="tiny")
    assert tiny["idle_timeout_s"] == 300 and tiny["ctx"] == 1024
    light = runtime_defaults(None, tiers, tier_id="light")
    assert light["idle_timeout_s"] == 600 and light["ctx"] == 2048
    standard = runtime_defaults(None, tiers, tier_id="standard")
    assert standard["service"] == "persistent" and standard["idle_timeout_s"] == 0
    workstation = runtime_defaults(None, tiers, tier_id="workstation")
    assert workstation["service"] == "persistent" and workstation["idle_timeout_s"] == 0
    assert runtime_defaults(None, tiers, tier_id=None) == {"idle_timeout_s": 600, "ctx": 2048, "service": "on-demand"}


def test_sampling_args_from_catalog():
    from ai2.models import load_catalog
    gemma = next(m for m in load_catalog() if m["id"] == "gemma3-270m")
    args = runtime.sampling_args(gemma)
    assert args == ["--temp", "1.0", "--top-k", "64", "--top-p", "0.95", "--min-p", "0.0"]
    assert runtime.sampling_args({"id": "no-block"}) == []
    # unknown keys are skipped, never passed through to llama-server
    assert runtime.sampling_args({"sampling": {"temp": 0.7, "bogus": 1}}) == ["--temp", "0.7"]


def test_sigterm_takes_the_child_down(tmp_path):
    # `ai-2 stop` SIGTERMs the serve wrapper; llama-server must die with it
    # (regression: default SIGTERM handling orphaned it, RMM-PC 2026-08-23).
    import signal
    import subprocess
    import sys
    import time
    rt = _runtime_dir(tmp_path, FAKE_SERVER)
    code = (f"import os; os.environ['XDG_STATE_HOME']=r'{tmp_path}/state'\n"
            f"from ai2 import runtime\n"
            f"runtime.serve(r'{rt}', 'm.gguf', threads=1, port=18767, "
            f"idle_timeout_s=600, model_id='t')\n")
    env = dict(os.environ, PYTHONPATH=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    wrapper = subprocess.Popen([sys.executable, "-c", code], env=env)
    deadline = time.monotonic() + 20
    child = None
    while time.monotonic() < deadline and child is None:
        out = subprocess.run(["pgrep", "-P", str(wrapper.pid), "-f", "llama-server"],
                             capture_output=True, text=True).stdout.strip()
        child = int(out) if out else None
        time.sleep(0.2)
    assert child, "fake llama-server never started"
    wrapper.send_signal(signal.SIGTERM)
    # serve() turns the SIGTERM into its normal shutdown path and returns,
    # so the wrapper ends by itself (the exact code is the child's, not 143).
    wrapper.wait(timeout=40)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.2)
    else:
        os.kill(child, signal.SIGKILL)
        raise AssertionError("llama-server survived the wrapper's SIGTERM")


# --- the model chat/serve actually use ---------------------------------------

def _hw(ram_mib=4096):
    from types import SimpleNamespace
    return SimpleNamespace(ram_mib=ram_mib)


def test_usable_model_falls_back_when_recommended_absent(monkeypatch):
    """Declining the recommended download must not block chatting: when the
    recommended model's file is not on disk, use the best model actually
    present (regression from the 20260826 ISO verify, where chat said
    "not set up" right after the wizard because only Qwen2.5 0.5B was on
    disk and the score recommended Qwen3 1.7B)."""
    from ai2 import cli, models
    rec = {"id": "qwen3-1.7b", "file": "missing.gguf"}
    present = {"id": "qwen2.5-0.5b", "file": "present.gguf"}
    monkeypatch.setattr(cli, "_recommended_model", lambda hw: rec)
    monkeypatch.setattr(cli, "find_model_file",
                        lambda name: "/x/present.gguf" if name == "present.gguf" else None)
    monkeypatch.setattr(models, "best_present_model", lambda cat, ram: present)
    assert cli._usable_model(_hw()) is present


def test_usable_model_prefers_recommended_when_present(monkeypatch):
    from ai2 import cli, models
    rec = {"id": "qwen3-1.7b", "file": "rec.gguf"}
    monkeypatch.setattr(cli, "_recommended_model", lambda hw: rec)
    monkeypatch.setattr(cli, "find_model_file", lambda name: "/x/" + name)
    monkeypatch.setattr(models, "best_present_model",
                        lambda cat, ram: (_ for _ in ()).throw(AssertionError("must not be called")))
    assert cli._usable_model(_hw()) is rec


# --- 2026-09-03 review: poll URL, pid guard, stop escalation ------------------

def test_poll_url_brackets_ipv6_and_loops_back_wildcards():
    assert runtime._poll_url("127.0.0.1", 8080) == "http://127.0.0.1:8080/slots"
    assert runtime._poll_url("0.0.0.0", 8080) == "http://127.0.0.1:8080/slots"
    assert runtime._poll_url("::", 8080) == "http://127.0.0.1:8080/slots"
    assert runtime._poll_url("::1", 8080) == "http://[::1]:8080/slots"
    assert runtime._poll_url("192.168.1.5", 8081) == "http://192.168.1.5:8081/slots"


def test_alive_never_signals_pid_zero_or_negative(monkeypatch):
    """kill(0, sig) is the caller's own process group; a state file without a
    pid must be treated as "no server", not as "everyone"."""
    def boom(*a):
        raise AssertionError("os.kill must not be called")
    monkeypatch.setattr(serverstate.os, "kill", boom)
    assert serverstate._alive(0) is False
    assert serverstate._alive(-1) is False


def test_stop_server_escalates_to_sigkill(tmp_path, monkeypatch):
    """A wrapper that ignores SIGTERM (wedged shutdown) is killed after the
    deadline, and only then is the record dropped."""
    import subprocess
    import sys
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    stubborn = subprocess.Popen(
        [sys.executable, "-c", "import signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                               "print('ready', flush=True); time.sleep(600)"],
        start_new_session=True, stdout=subprocess.PIPE, text=True)
    try:
        assert stubborn.stdout.readline().strip() == "ready"   # handler installed
        serverstate.write_server(stubborn.pid, "t", "/x/m.gguf", 8080, "127.0.0.1")
        assert serverstate.stop_server(timeout_s=1, kill_after_s=5) is True
        assert stubborn.wait(timeout=5) == -9
        assert serverstate.read_server() is None
    finally:
        if stubborn.poll() is None:
            stubborn.kill()
