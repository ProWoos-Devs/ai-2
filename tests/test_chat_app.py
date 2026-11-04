"""`ai-2 chat` opens the AI-2 Gopher app, and which cases stay elsewhere."""
import argparse
from types import SimpleNamespace

from ai2 import a11y, cli, gopher


def _args(**given):
    plain = dict(terminal=False, browser=False, no_browser=False, model=None, speak=False,
                 port=8080, idle_timeout=None)
    return argparse.Namespace(**{**plain, **given})


def _desktop(monkeypatch, app="/usr/bin/ai-2-gopher", reader=False):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(cli, "_chat_app", lambda: app)
    monkeypatch.setattr(a11y, "reader_active", lambda: reader)


def test_a_desktop_with_the_app_uses_it(monkeypatch):
    _desktop(monkeypatch)
    assert cli._wants_chat_app(_args()) is True


def test_a_request_only_the_other_chats_can_do_stays_with_them(monkeypatch):
    _desktop(monkeypatch)
    for given in ({"terminal": True}, {"browser": True}, {"no_browser": True}, {"model": "x"},
                  {"speak": True}, {"port": 9000}, {"idle_timeout": 60}):
        assert cli._wants_chat_app(_args(**given)) is False, given


def test_a_screen_reader_stays_on_the_terminal_chat(monkeypatch):
    _desktop(monkeypatch, reader=True)
    assert cli._wants_chat_app(_args()) is False


def test_no_display_stays_in_the_terminal(monkeypatch):
    _desktop(monkeypatch)
    monkeypatch.delenv("DISPLAY")
    assert cli._wants_chat_app(_args()) is False


def test_without_the_app_the_browser_opens_and_it_says_how_to_get_it(monkeypatch, capsys):
    _desktop(monkeypatch, app=None)
    assert cli._wants_chat_app(_args()) is False
    opened = _record_popen(monkeypatch)
    monkeypatch.setattr(cli, "detect", lambda: SimpleNamespace(ram_mib=2048, cpu_variant="avx2"))
    monkeypatch.setattr(cli.remote, "load", lambda: None)
    monkeypatch.setattr(cli.runner, "_server_ready", lambda url: True)
    monkeypatch.setattr(cli.runner, "endpoint_problem", lambda *a: None)
    assert cli.main(["chat"]) == 0
    assert opened == [["xdg-open", "http://127.0.0.1:8080/"]]
    assert "sudo pacman -S ai-2-gopher" in capsys.readouterr().out


def _record_popen(monkeypatch, on_server=None):
    started = []

    def popen(cmd, **kwargs):
        started.append(cmd)
        if "--for-chat" in cmd and on_server:
            on_server()
        return SimpleNamespace(poll=lambda: None)
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", popen)
    return started


def test_a_running_server_is_reused_and_the_app_gets_its_menu_directly(monkeypatch):
    monkeypatch.setattr(gopher, "offers_chat", lambda *a, **k: True)
    started = _record_popen(monkeypatch)
    assert cli._open_chat_app() is True
    assert started == [["ai-2-gopher", gopher.chat_url()]]


def test_a_stopped_server_is_started_first(monkeypatch):
    up = []
    monkeypatch.setattr(gopher, "offers_chat", lambda *a, **k: bool(up))
    started = _record_popen(monkeypatch, on_server=lambda: up.append(True))
    assert cli._open_chat_app() is True
    assert "--for-chat" in started[0] and started[1] == ["ai-2-gopher", gopher.chat_url()]


def test_a_server_that_cannot_start_does_not_open_the_app(monkeypatch):
    monkeypatch.setattr(gopher, "offers_chat", lambda *a, **k: False)
    started = []

    def popen(cmd, **kwargs):
        started.append(cmd)
        return SimpleNamespace(poll=lambda: 1)
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", popen)
    assert cli._open_chat_app() is False
    assert len(started) == 1 and "--for-chat" in started[0]
