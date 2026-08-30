"""The passive update check behind the desktop notification and login hint."""
import json
import os
import stat
import time

from ai2 import updates


def _fake_checkupdates(tmp_path, monkeypatch, script):
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    p = d / "checkupdates"
    p.write_text(script)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{d}:{os.environ['PATH']}")


def test_check_now_counts_and_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    _fake_checkupdates(tmp_path, monkeypatch,
                       "#!/bin/sh\necho 'ai-2 0.5.1-1 -> 0.5.2-1'\necho 'linux 6.9-1 -> 6.10-1'\n")
    st = updates.check_now()
    assert st["count"] == 2 and st["packages"] == ["ai-2", "linux"]
    assert json.load(open(updates.state_file()))["count"] == 2


def test_check_failure_keeps_old_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    _fake_checkupdates(tmp_path, monkeypatch, "#!/bin/sh\necho x\n")
    assert updates.check_now()["count"] == 1
    # exit 1 = real error (offline): old state must survive
    _fake_checkupdates(tmp_path, monkeypatch, "#!/bin/sh\nexit 1\n")
    assert updates.check_now() is None
    assert updates.load_state()["count"] == 1
    # exit 2 = checked fine, nothing pending: state becomes 0
    _fake_checkupdates(tmp_path, monkeypatch, "#!/bin/sh\nexit 2\n")
    assert updates.check_now()["count"] == 0


def test_state_freshness(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(updates, "PACMAN_LOCAL_DB", str(tmp_path / "nonexistent"))
    os.makedirs(os.path.dirname(updates.state_file()))
    now = time.time()
    json.dump({"checked_at": now - 3600, "count": 3}, open(updates.state_file(), "w"))
    assert updates.state_is_fresh(20, now=now)          # 1 h old, 20 h window
    assert not updates.state_is_fresh(0.5, now=now)     # 1 h old, 30 min window
    # a pacman run after the check makes it stale
    db = tmp_path / "db"
    db.mkdir()
    monkeypatch.setattr(updates, "PACMAN_LOCAL_DB", str(db))
    assert not updates.state_is_fresh(20, now=now)


def test_cli_update_check(tmp_path, monkeypatch, capsys):
    from ai2 import cli
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    _fake_checkupdates(tmp_path, monkeypatch, "#!/bin/sh\necho 'pkg 1-1 -> 2-1'\n")
    sent = []
    monkeypatch.setattr(updates, "notify", lambda n: sent.append(n) or True)
    assert cli.main(["update-check", "--notify"]) == 0
    assert "1 update(s) available" in capsys.readouterr().out
    assert sent == [1]


class _Recorder:
    """Stands in for notify-send: records the argv it was called with and
    answers with whatever the test wants on stdout."""

    def __init__(self, returncode=0, stdout=""):
        self.calls = []
        self.returncode = returncode
        self.stdout = stdout

    def __call__(self, cmd, *a, **kw):
        self.calls.append(cmd)

        class Proc:
            pass

        proc = Proc()
        proc.returncode = self.returncode
        proc.stdout = self.stdout
        return proc


def _no_reader(monkeypatch):
    from ai2 import a11y
    monkeypatch.setattr(a11y, "reader_active", lambda: False)


def test_notify_says_nothing_when_nothing_is_pending():
    assert updates.notify(0) is False


def test_notify_carries_a_button_when_the_gui_is_installed(monkeypatch):
    from ai2 import software
    _no_reader(monkeypatch)
    monkeypatch.setattr(updates.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(software, "gui_available", lambda: True)
    opened = []
    monkeypatch.setattr(software, "open_gui", lambda updates=False: opened.append(updates))
    rec = _Recorder(stdout="open\n")
    monkeypatch.setattr(updates.subprocess, "run", rec)
    assert updates.notify(3) is True
    assert any(arg.startswith("--action=open=") for arg in rec.calls[0])
    assert "3" in rec.calls[0][-2]
    assert opened == [True], "clicking the button must open the updates page"


def test_notify_without_the_gui_points_at_the_command(monkeypatch):
    from ai2 import software
    _no_reader(monkeypatch)
    monkeypatch.setattr(updates.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(software, "gui_available", lambda: False)
    rec = _Recorder()
    monkeypatch.setattr(updates.subprocess, "run", rec)
    assert updates.notify(1) is True
    assert not any(arg.startswith("--action=") for arg in rec.calls[0])
    assert "ai-2 update" in rec.calls[0][-1]


def test_notify_falls_back_when_actions_are_unsupported(monkeypatch):
    """An old libnotify rejects --action. The plain bubble must still show."""
    from ai2 import software
    _no_reader(monkeypatch)
    monkeypatch.setattr(updates.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(software, "gui_available", lambda: True)
    calls = []

    def run(cmd, *a, **kw):
        calls.append(cmd)

        class Proc:
            returncode = 1 if any(x.startswith("--action=") for x in cmd) else 0
            stdout = ""
        return Proc()

    monkeypatch.setattr(updates.subprocess, "run", run)
    assert updates.notify(2) is True
    assert len(calls) == 2 and not any(x.startswith("--action=") for x in calls[1])


def test_notify_is_spoken_to_a_screen_reader(monkeypatch):
    from ai2 import a11y, software
    monkeypatch.setattr(updates.shutil, "which", lambda name: None)
    monkeypatch.setattr(software, "gui_available", lambda: False)
    monkeypatch.setattr(a11y, "reader_active", lambda: True)
    spoken = []
    monkeypatch.setattr(a11y, "speak_once", lambda text: spoken.append(text))
    assert updates.notify(4) is False        # nothing visual, no notify-send
    assert spoken and "ai-2 update" in spoken[0]
