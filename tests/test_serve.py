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
    assert runtime_defaults(None, tiers, tier_id=None) == {"idle_timeout_s": 600, "ctx": 2048, "service": "on-demand"}
