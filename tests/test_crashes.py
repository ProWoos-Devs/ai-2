"""Crash records (ai2/crashes.py): the kernel handler keeps one line per
crash and no dump, the desktop says so once, doctor says what to do."""
import argparse
import os
import pathlib
import subprocess
import time

import pytest

from ai2 import cli, crashes, doctor

HANDLER = pathlib.Path("packaging/ai-2/crash-handler.sh")
SYSCTL = pathlib.Path("packaging/ai-2/60-ai2-crashes.conf")


@pytest.fixture
def log(tmp_path, monkeypatch):
    path = tmp_path / "crashes.log"
    monkeypatch.setattr(crashes, "LOG", str(path))
    monkeypatch.setattr(crashes, "recording", lambda: True)
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    return path


def _line(t, comm="firefox", sig=11, uid=1000, path="!usr!bin!firefox"):
    return f"{t} {uid} 4242 {sig} {comm} {path}\n"


def test_handler_records_one_line_and_keeps_no_dump(tmp_path):
    log = tmp_path / "var" / "crashes.log"
    env = dict(os.environ, AI2_CRASH_LOG=str(log))
    # the kernel feeds the dump on stdin; the handler must not read it
    proc = subprocess.run(["sh", str(HANDLER), "1760000000", "1000", "77", "11", "firefox", "!usr!bin!firefox"],
                          input=b"x" * 1_000_000, env=env, capture_output=True, timeout=10)
    assert proc.returncode == 0
    assert log.read_text() == "1760000000 1000 77 11 firefox !usr!bin!firefox\n"
    assert oct(log.stat().st_mode & 0o777) == "0o644"


def test_handler_trims_a_crash_loop(tmp_path):
    log = tmp_path / "crashes.log"
    log.write_text("".join(_line(1760000000 + i) for i in range(500)))
    env = dict(os.environ, AI2_CRASH_LOG=str(log))
    subprocess.run(["sh", str(HANDLER), "1760001000", "1000", "1", "11", "firefox", "!usr!bin!firefox"],
                   env=env, capture_output=True, timeout=10, check=True)
    lines = log.read_text().splitlines()
    assert len(lines) == 200 and lines[-1].startswith("1760001000 ")


def test_sysctl_file_names_the_handler_and_the_package_ships_both():
    conf = SYSCTL.read_text(encoding="utf-8")
    assert f"kernel.core_pattern = |{crashes.HANDLER} %t %u %p %s %e %E" in conf
    assert subprocess.run(["sh", "-n", str(HANDLER)]).returncode == 0
    pkgbuild = pathlib.Path("packaging/ai-2/PKGBUILD").read_text(encoding="utf-8")
    assert f'install -Dm755 packaging/ai-2/crash-handler.sh "$pkgdir{crashes.HANDLER}"' in pkgbuild
    assert 'install -Dm644 packaging/ai-2/60-ai2-crashes.conf "$pkgdir/usr/lib/sysctl.d/60-ai2-crashes.conf"' in pkgbuild


def test_parse_and_mine_keep_only_this_account_and_the_window(log):
    now = int(time.time())
    log.write_text(_line(now - 100) + _line(now - 200, uid=1001) + _line(now - 30 * 86400)
                   + "garbage line\n" + _line(now - 50, comm="llama-server", sig=4,
                                              path="!usr!lib!ai2!runtimes!llama.cpp!llama-server"))
    mine = crashes.mine()
    assert [c.comm for c in mine] == ["firefox", "llama-server"]
    engine = mine[1]
    assert engine.is_engine and engine.program == "the AI engine" and engine.path.startswith("/usr/lib/ai2/")
    assert engine.signal_name == "SIGILL"


def test_summary_describes_counts_and_the_engine_hint(log):
    now = int(time.time())
    log.write_text(_line(now - 300) + _line(now - 100)
                   + _line(now - 50, comm="llama-server", sig=4, path="!usr!lib!ai2!runtimes!llama.cpp!llama-server"))
    entries = crashes.summarize(crashes.mine())
    assert [e["program"] for e in entries] == ["the AI engine", "firefox"]
    assert entries[1]["count"] == 2 and "2 times" in crashes.describe(entries[1])
    assert "memory access error" in crashes.describe(entries[1])
    assert "does not fit this CPU" in crashes.hint(entries[0]) and "ai-2 doctor" in crashes.hint(entries[0])
    assert "Search Knowledge" in crashes.hint(entries[1])


def test_doctor_check_levels(log, monkeypatch):
    assert doctor.check_crashes().status == doctor.OK
    now = int(time.time())
    log.write_text(_line(now - 100))
    c = doctor.check_crashes()
    assert c.status == doctor.WARN and "firefox" in c.detail
    log.write_text(_line(now - 50, comm="llama-server", sig=4, path="!usr!lib!ai2!runtimes!llama.cpp!llama-server"))
    c = doctor.check_crashes()
    assert c.status == doctor.FAIL and "the AI engine" in c.detail
    monkeypatch.setattr(crashes, "recording", lambda: False)
    c = doctor.check_crashes()
    assert c.status == doctor.INFO and "sysctl --system" in c.detail


def test_notice_is_shown_once_and_only_for_the_last_day_at_first(log):
    now = int(time.time())
    log.write_text(_line(now - 3 * 86400) + _line(now - 100) + _line(now - 60, comm="mousepad"))
    shown = []
    assert crashes.notify_new(show=lambda t, b, a: shown.append((t, b, a)) or True)
    title, body, action = shown[0]
    assert title == "Mousepad and one other program stopped unexpectedly" and action is None
    assert "ai-2 doctor" in body
    # the mark: nothing new, so nothing said again
    assert not crashes.notify_new(show=lambda *a: pytest.fail("said twice"))
    # a new crash after the mark is told
    with open(log, "a") as fh:
        fh.write(_line(now + 5, comm="epiphany"))
    assert crashes.notify_new(show=lambda t, b, a: shown.append((t, b, a)) or True)
    assert shown[1][0] == "Epiphany stopped unexpectedly"
    for i, extra in enumerate(("a", "b", "c")):
        with open(log, "a") as fh:
            fh.write(_line(now + 9 + i, comm=extra))
    assert crashes.notify_new(show=lambda t, b, a: shown.append((t, b, a)) or True)
    assert shown[2][0] == "C and 2 other programs stopped unexpectedly"


def test_notice_not_marked_when_no_bubble_could_be_shown(log):
    now = int(time.time())
    log.write_text(_line(now - 10))
    assert not crashes.notify_new(show=lambda *a: False)
    assert crashes.last_seen() == 0
    assert crashes.notify_new(show=lambda *a: True)
    assert crashes.last_seen() == now - 10


def test_engine_notice_names_the_cpu_build(log):
    now = int(time.time())
    log.write_text(_line(now - 50, comm="llama-server", sig=4, path="!usr!lib!ai2!runtimes!llama.cpp!llama-server"))
    title, body = crashes.build_notice(crashes.unseen())
    assert title == "The AI engine stopped unexpectedly" and "does not fit this CPU" in body


def test_update_check_tells_about_crashes_on_every_notify_round(monkeypatch, capsys):
    from ai2 import updates
    calls = []
    monkeypatch.setattr(crashes, "notify_new", lambda: calls.append(1) or True)
    monkeypatch.setattr(updates, "state_is_fresh", lambda h: True)
    monkeypatch.setattr(updates, "load_state", lambda: {"count": 0, "packages": []})
    assert cli.cmd_update_check(argparse.Namespace(notify=True, max_age=20.0, every=None)) == 0
    assert calls == [1] and "stopped unexpectedly" in capsys.readouterr().out
    assert cli.cmd_update_check(argparse.Namespace(notify=False, max_age=20.0, every=None)) == 0
    assert calls == [1]


def test_listing_and_report(log, capsys, monkeypatch):
    assert cli.main(["crashes"]) == 0
    assert "Nothing stopped unexpectedly" in capsys.readouterr().out
    now = int(time.time())
    log.write_text(_line(now - 100) + _line(now - 50, comm="llama-server", sig=4,
                                            path="!usr!lib!ai2!runtimes!llama.cpp!llama-server"))
    assert cli.main(["crashes"]) == 0
    out = capsys.readouterr().out
    assert "firefox" in out and "the AI engine" in out and "does not fit this CPU" in out
    monkeypatch.setattr(crashes, "recording", lambda: False)
    assert cli.main(["crashes"]) == 1
    assert "not being recorded" in capsys.readouterr().out
    monkeypatch.setattr(crashes, "recording", lambda: True)
    from ai2.detect import detect
    text = doctor.report_text(detect(), [])
    assert "== Crashes of this account" in text and "llama-server  SIGILL" in text
