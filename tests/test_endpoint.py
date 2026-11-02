"""A healthy answer on a port is not enough: AI-2 uses an endpoint only once it
has shown it runs the right model under this account. The endpoints here are
real local HTTP servers, so what is tested is the request and the parsing."""
import http.server
import json
import os
import threading
import time

import pytest

from ai2 import cli, runner, runtime, serverstate

GOOD = "nomic-embed-text-v1.5.Q4_K_M.gguf"
MODEL = {"id": "nomic-embed-text-v1.5", "file": GOOD, "label": "Nomic"}
OTHER = "/home/x/models/nomic-embed-text-v2-moe.Q4_K_M.gguf"


def _endpoint(models_reply, status=200):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                code, body = 200, b'{"status":"ok"}'
            elif self.path == "/v1/models":
                code, body = status, models_reply
            else:
                code, body = 404, b"{}"
            self.send_response(code)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _reply(path):
    return json.dumps({"object": "list", "data": [{"id": path, "object": "model"}]}).encode()


@pytest.fixture
def serve(request, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    made = []

    def start(reply, status=200):
        made.append(_endpoint(reply, status))
        return made[-1].server_address[1]
    yield start
    for s in made:
        s.shutdown()


def _url(port):
    return f"http://127.0.0.1:{port}/"


def test_model_file_is_read_from_the_endpoint(serve):
    assert runner._server_model_file(_url(serve(_reply("/m/" + GOOD)))) == GOOD
    assert runner._server_model_file(_url(serve(b"not json"))) is None
    assert runner._server_model_file(_url(serve(b'{"data":[]}'))) is None
    assert runner._server_model_file(_url(serve(b"{}", status=404))) is None


@pytest.mark.parametrize("reply, status, expect_in", [
    (_reply(OTHER), 200, "is running nomic-embed-text-v2-moe.Q4_K_M.gguf, not " + GOOD),   # the wrong model
    (b"<html>a web server</html>", 200, "does not say which model"),                        # an unrelated program
    (b"{}", 404, "does not say which model"),
])
def test_ensure_server_refuses_what_it_cannot_verify_with_no_record(serve, capsys, reply, status, expect_in):
    port = serve(reply, status)
    assert runner._ensure_server(None, MODEL, port, serverstate.EMBED, wait=1) is None
    assert expect_in in capsys.readouterr().err


def test_ensure_server_accepts_the_right_model_with_no_record(serve):
    port = serve(_reply("/m/" + GOOD))
    assert runner._ensure_server(None, MODEL, port, serverstate.EMBED, wait=1) == _url(port)


def test_a_record_naming_the_model_does_not_vouch_for_another_port(serve, capsys):
    """The record says this model runs on 9999; what answers here runs another."""
    serverstate.write_server(os.getpid(), MODEL["id"], "/m/" + GOOD, 9999, "127.0.0.1", name=serverstate.EMBED)
    port = serve(_reply(OTHER))
    assert runner._ensure_server(None, MODEL, port, serverstate.EMBED, wait=1) is None
    assert "is running" in capsys.readouterr().err


def test_port_owners_reads_the_kernel_tables(tmp_path):
    header = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
    (tmp_path / "tcp").write_text(header +
        "   0: 0100007F:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1001        0 11 1\n"   # 8080, listening
        "   1: 0100007F:1F90 0100007F:D000 01 00000000:00000000 00:00000000 00000000  1002        0 12 1\n"   # 8080, a client
        "   2: 0100007F:1F91 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1003        0 13 1\n")  # 8081
    (tmp_path / "tcp6").write_text(header +
        "   0: 00000000000000000000000000000000:1F90 00000000000000000000000000000000:0000 0A 00000000:00000000 00:00000000 00000000  1004        0 14 1\n")
    assert runner._port_owners(8080, str(tmp_path)) == {1001, 1004}
    assert runner._port_owners(8081, str(tmp_path)) == {1003}
    assert runner._port_owners(9000, str(tmp_path)) == set()
    assert runner._port_owners(8080, str(tmp_path / "missing")) == set()


def test_real_port_owner_is_this_account(serve):
    assert runner._port_owners(serve(_reply("/m/" + GOOD))) == {os.getuid()}


def test_another_accounts_port_is_refused_even_with_the_right_model(serve, monkeypatch, capsys):
    port = serve(_reply("/m/" + GOOD))
    monkeypatch.setattr(runner, "_port_owners", lambda p: {os.getuid() + 1})
    assert runner._ensure_server(None, MODEL, port, serverstate.EMBED, wait=1) is None
    assert "another account" in capsys.readouterr().err


def test_unreadable_kernel_tables_rule_nobody_out(serve, monkeypatch):
    port = serve(_reply("/m/" + GOOD))
    monkeypatch.setattr(runner, "_port_owners", lambda p: set())
    assert runner.endpoint_problem(_url(port), port, GOOD) is None


def test_chat_will_not_use_another_accounts_server(serve, monkeypatch, capsys):
    port = serve(_reply("/m/whatever.gguf"))
    monkeypatch.setattr(cli.remote, "load", lambda: None)
    monkeypatch.setattr(cli, "detect", lambda: type("HW", (), {"ram_mib": 8000, "cpu_variant": "avx2"})())
    monkeypatch.setattr(runner, "_port_owners", lambda p: {os.getuid() + 1})
    assert cli.main(["chat", "--no-browser", "--port", str(port)]) == 1
    assert "another account" in capsys.readouterr().err


def test_chat_with_a_named_model_refuses_a_server_running_another(serve, monkeypatch, capsys):
    port = serve(_reply("/m/whatever.gguf"))
    monkeypatch.setattr(cli.remote, "load", lambda: None)
    monkeypatch.setattr(cli, "detect", lambda: type("HW", (), {"ram_mib": 8000, "cpu_variant": "avx2"})())
    assert cli.main(["chat", "--no-browser", "--port", str(port), "--model", "qwen2.5-0.5b"]) == 1
    assert "is running whatever.gguf" in capsys.readouterr().err


def test_write_server_replaces_the_record_in_one_step(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    serverstate.write_server(os.getpid(), "m", "/m", 8080, "127.0.0.1")
    assert serverstate.read_server()["model"] == "m"
    assert os.listdir(serverstate.state_dir()) == ["server.json"]    # no temporary file left


def test_start_lock_makes_the_second_starter_wait_and_says_so(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    order = []

    def second():
        with serverstate.start_lock():
            order.append("second")
    with serverstate.start_lock():
        t = threading.Thread(target=second)
        t.start()
        time.sleep(0.3)
        order.append("first done")
    t.join(5)
    assert order == ["first done", "second"]
    assert "waiting for it" in capsys.readouterr().err


def test_two_commands_starting_together_start_one_server(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    started = []

    class FakePopen:
        def __init__(self, cmd, **kw):
            started.append(cmd)
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(runner, "_server_ready", lambda url, timeout=2.0: bool(started))
    monkeypatch.setattr(runner, "endpoint_problem", lambda url, port, expected_file=None: None)
    monkeypatch.setattr(runtime, "find_runtime", lambda variant: "/x")
    monkeypatch.setattr(runtime, "find_model_file", lambda f: "/x/" + f)
    hw = type("HW", (), {"cpu_variant": "avx2"})()
    results = []
    threads = [threading.Thread(target=lambda: results.append(
        runner._ensure_server(hw, MODEL, 8081, serverstate.EMBED, wait=5))) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert len(started) == 1 and results == ["http://127.0.0.1:8081/"] * 4
