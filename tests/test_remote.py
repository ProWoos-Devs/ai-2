"""ai-2 remote: the config file, the probe, and chat --remote against a fake
OpenAI-compatible server that checks the bearer key."""
import http.server
import json
import os
import stat
import threading

import pytest

from ai2 import chatterm, cli, remote

KEY = "secret-key-1234"


class _Handler(http.server.BaseHTTPRequestHandler):
    seen: list = []
    llama = True    # /props exists (llama-server) or not (an API provider)

    def _auth(self) -> bool:
        return self.headers.get("Authorization") == "Bearer " + KEY

    def do_GET(self):
        if self.path == "/v1/models":
            body = json.dumps({"data": [{"id": "/srv/models/qwen2.5-7b.gguf"}, {"id": "other"}]}).encode()
        elif self.path == "/props" and self.llama:
            if not self._auth():   # llama-server gates /props, not /v1/models
                self.send_response(401); self.end_headers(); return
            body = json.dumps({"ui_settings": {}}).encode()
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(n))
        _Handler.seen.append({"auth": self.headers.get("Authorization"), "body": payload})
        if not self._auth():
            self.send_response(401); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        for piece in ("Hi", " there."):
            self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {"content": piece}}]}).encode() + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Handler.seen = []
    _Handler.llama = True
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    return tmp_path


def test_save_normalizes_url_and_keeps_the_key_private(home):
    p = remote.save("192.168.1.20:8080/", api_key=KEY, default=True)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    cfg = remote.load()
    assert cfg["url"] == "http://192.168.1.20:8080" and cfg["default"] is True
    assert remote.normalize_url("https://api.example.com/v1/") == "https://api.example.com"
    assert remote.masked_key(cfg) == "...1234"
    assert remote.headers(cfg)["Authorization"] == "Bearer " + KEY
    assert remote.set_default(False)["default"] is False
    assert remote.clear() and remote.load() is None and not remote.clear()


def test_probe_lists_models_detects_llama_server_and_bad_key(server, home):
    info = remote.probe({"url": server, "api_key": KEY})
    assert info["ok"] and info["models"] == ["qwen2.5-7b", "other"] and info["web_ui"]
    bad = remote.probe({"url": server, "api_key": "nope"})   # /v1/models is public, /props is not
    assert not bad["ok"] and "401" in bad["error"] and "API key" in bad["error"]
    _Handler.llama = False   # an API provider: no /props, so no chat page
    assert remote.probe({"url": server, "api_key": KEY})["web_ui"] is False


def test_remote_command_set_show_test_default_clear(server, home, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(KEY + "\n"))
    assert cli.main(["remote", "set", server, "--api-key-stdin", "--model", "qwen2.5-7b"]) == 0
    out = capsys.readouterr().out
    assert "...1234" in out and "Reachable" in out and "Has a chat page" in out and "with --remote" in out
    assert cli.main(["remote", "show"]) == 0
    assert "only with ai-2 chat --remote" in capsys.readouterr().out
    assert cli.main(["remote", "test"]) == 0
    assert "qwen2.5-7b" in capsys.readouterr().out
    assert cli.main(["remote", "default", "on"]) == 0
    assert remote.load()["default"] is True
    assert cli.main(["remote", "clear"]) == 0
    assert cli.main(["remote", "test"]) == 1


def test_chat_remote_sends_key_and_model_and_says_where_messages_go(server, home, capsys, monkeypatch):
    remote.save(server, api_key=KEY, model="qwen2.5-7b")
    captured = {}

    def fake_repl(url, stream=chatterm.stream_reply, ask=input, say=print, streaming=False, speak=None, system=None):
        captured["url"] = url
        captured["system"] = system
        captured["reply"] = "".join(stream(url, [{"role": "user", "content": "hi"}]))
        return 0

    monkeypatch.setattr(chatterm, "repl", fake_repl)
    assert cli.main(["chat", "--remote", "--terminal"]) == 0
    out = capsys.readouterr().out
    assert "Your messages leave this computer" in out and server in out
    assert captured["url"] == server and captured["reply"] == "Hi there."
    assert "another computer" in captured["system"] and "qwen2.5-7b" in captured["system"]
    assert _Handler.seen[0]["auth"] == "Bearer " + KEY
    assert _Handler.seen[0]["body"]["model"] == "qwen2.5-7b"


def test_chat_remote_default_and_local_override(server, home, capsys, monkeypatch):
    remote.save(server, api_key=KEY, default=True)
    calls = []
    monkeypatch.setattr(cli, "_chat_remote", lambda args, cfg: calls.append(cfg["url"]) or 0)
    assert cli.main(["chat"]) == 0
    assert calls == [server]
    # --local skips the remote and goes on to the local path (which is not set up here)
    monkeypatch.setattr(cli, "_server_ready", lambda url, timeout=2.0: False)
    monkeypatch.setattr(cli, "find_runtime", lambda variant: None)
    assert cli.main(["chat", "--local", "--no-browser"]) == 1
    assert "not set up" in capsys.readouterr().err
    assert calls == [server]


def test_chat_remote_needs_a_config_and_notes_one_when_not_used(home, capsys, monkeypatch):
    assert cli.main(["chat", "--remote"]) == 1
    assert "ai-2 remote set" in capsys.readouterr().err
    remote.save("http://10.0.0.5:8080", default=False)
    monkeypatch.setattr(cli, "_server_ready", lambda url, timeout=2.0: True)
    from ai2 import serverstate
    serverstate.write_server(os.getpid(), "gemma3-270m", "/x/m.gguf", 8080, "127.0.0.1")
    assert cli.main(["chat", "--no-browser"]) == 0
    assert "a remote AI is configured, http://10.0.0.5:8080" in capsys.readouterr().out
    serverstate.clear_server()
