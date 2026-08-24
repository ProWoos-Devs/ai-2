"""ai-2 model list / rm / verify, on a temp model dir with no hardware."""
import hashlib
import os

from ai2 import cli, runtime
from ai2.detect import Hardware
from ai2.models import load_catalog


def _setup(tmp_path, monkeypatch):
    d = tmp_path / "models"; d.mkdir()
    monkeypatch.setenv("AI2_MODEL_DIR", str(d))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(cli, "detect", lambda: Hardware(ram_mib=3800, ram_nominal_gib=4, logical_cores=2, flags=set()))
    m = next(x for x in load_catalog() if x["id"] == "qwen2.5-0.5b")
    (d / m["file"]).write_bytes(b"q" * 2048)
    (d / "stray.gguf").write_bytes(b"s" * 1024)
    return d, m


def test_list_shows_installed_and_available(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    assert cli.main(["model", "list"]) == 0
    out = capsys.readouterr().out
    assert "qwen2.5-0.5b" in out and "(not in catalog)" in out and "gemma3-270m" in out


def test_rm_deletes_and_refuses_loaded(tmp_path, monkeypatch, capsys):
    d, m = _setup(tmp_path, monkeypatch)
    from ai2 import serverstate
    serverstate.write_server(os.getpid(), "qwen2.5-0.5b", str(d / m["file"]), 8080, "127.0.0.1")
    assert cli.main(["model", "rm", "qwen2.5-0.5b"]) == 1      # loaded by the (fake) server
    serverstate.clear_server()
    assert cli.main(["model", "rm", "qwen2.5-0.5b"]) == 0
    assert not (d / m["file"]).exists()
    assert cli.main(["model", "rm", "qwen2.5-0.5b"]) == 0      # already gone, not an error


def test_verify_detects_mismatch_and_match(tmp_path, monkeypatch, capsys):
    d, m = _setup(tmp_path, monkeypatch)
    assert cli.main(["model", "verify", "qwen2.5-0.5b"]) == 2   # 2048 bytes of "q" is not the real file
    assert "BAD" in capsys.readouterr().out
    good = next(x for x in load_catalog() if x["id"] == "gemma3-270m")
    data = b"g" * 100
    (d / good["file"]).write_bytes(data)
    monkeypatch.setattr(runtime, "verify_model", lambda p, s: hashlib.sha256(data).hexdigest() == hashlib.sha256(open(p, "rb").read()).hexdigest())
    monkeypatch.setattr(cli, "verify_model", runtime.verify_model)
    assert cli.main(["model", "verify", "gemma3-270m"]) == 0


def test_bare_command_prints_help(capsys):
    from ai2 import cli
    assert cli.main([]) == 0
    assert "detect" in capsys.readouterr().out
    assert cli.main(["model"]) == 0
    assert "pull" in capsys.readouterr().out
    assert cli.main(["runtime"]) == 0
    assert "install" in capsys.readouterr().out


def test_chat_notes_starter_model(tmp_path, monkeypatch, capsys):
    from ai2 import cli, serverstate
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(cli, "_server_ready", lambda url, timeout=2.0: True)
    serverstate.write_server(os.getpid(), "gemma3-270m", "/x/m.gguf", 8080, "127.0.0.1")
    assert cli.main(["chat", "--no-browser"]) == 0
    out = capsys.readouterr().out
    assert "starter model" in out and "ai-2 model list" in out
    serverstate.clear_server()
