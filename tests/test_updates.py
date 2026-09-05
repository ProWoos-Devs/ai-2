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


def test_cli_update_check_every_keeps_going_and_notifies_only_fresh_finds(tmp_path, monkeypatch, capsys):
    """The autostart loop: login round notifies from the cache, later rounds
    only when a fresh check ran (a bubble still up is not stacked), and a
    check after `pacman -Syu` that finds nothing stays quiet."""
    from ai2 import cli
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    sent, checks, slept = [], [], []
    monkeypatch.setattr(updates, "notify", lambda n: sent.append(n) or True)
    fresh = iter([True, True, False, False])          # cache fresh, fresh, stale, stale
    monkeypatch.setattr(updates, "state_is_fresh", lambda h: next(fresh))
    counts = iter([3, 0])                             # fresh checks: 3 pending, then current
    def check_now():
        checks.append(1)
        return {"count": next(counts), "packages": []}
    monkeypatch.setattr(updates, "check_now", check_now)
    monkeypatch.setattr(updates, "load_state", lambda: {"count": 2, "packages": []})
    def sleep(s):
        slept.append(s)
        if len(slept) == 4:
            raise KeyboardInterrupt
    import argparse
    args = argparse.Namespace(notify=True, max_age=20.0, every=6.0)
    try:
        cli.cmd_update_check(args, sleep=sleep)
    except KeyboardInterrupt:
        pass
    assert slept == [21600] * 4
    assert sent == [2, 3]          # login reminder from the cache; then only the fresh find
    assert len(checks) == 2        # two stale rounds ran a real check


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


def _gui(monkeypatch, present):
    from ai2 import software
    monkeypatch.setattr(software, "gui_available", lambda: present)


def test_notify_says_nothing_when_nothing_is_pending():
    assert updates.notify(0) is False


def test_build_wording_depends_on_the_gui_being_there(monkeypatch):
    _gui(monkeypatch, True)
    title, body, action = updates.build(3)
    assert "3" in title and action
    assert "Software Updates" in body
    _gui(monkeypatch, False)
    title, body, action = updates.build(1)
    assert "1" in title and action is None
    assert "ai-2 update" in body


def test_the_bubble_never_expires(monkeypatch):
    """A ten-second bubble throws away the click that does the job."""
    _gui(monkeypatch, False)
    rec = _Recorder()
    assert updates.show("t", "b", None, run=rec) is True
    assert "-t" in rec.calls[0] and "0" in rec.calls[0]


def test_show_carries_the_button_and_acts_on_the_click(monkeypatch):
    from ai2 import software
    opened = []
    monkeypatch.setattr(software, "open_gui", lambda updates=False: opened.append(updates))
    rec = _Recorder(stdout="open\n")
    assert updates.show("t", "b", "Open Software Updates", run=rec) is True
    assert any(a.startswith("--action=open=") for a in rec.calls[0])
    assert opened == [True], "clicking the button must open the updates page"


def test_show_falls_back_when_actions_are_unsupported():
    """An old libnotify rejects --action. The plain bubble must still show."""
    calls = []

    def run(cmd, *a, **kw):
        calls.append(cmd)

        class Proc:
            returncode = 1 if any(x.startswith("--action=") for x in cmd) else 0
            stdout = ""
        return Proc()

    assert updates.show("t", "b", "Open", run=run) is True
    assert len(calls) == 2 and not any(x.startswith("--action=") for x in calls[1])
    assert "-t" in calls[1], "the fallback bubble must still be sticky"


def test_notify_forks_a_holder_only_when_there_is_a_button(monkeypatch):
    """The button needs a live client; without one there is nothing to hold."""
    _no_reader(monkeypatch)
    monkeypatch.setattr(updates.shutil, "which", lambda name: "/usr/bin/" + name)
    forks = []
    _gui(monkeypatch, True)
    assert updates.notify(2, fork=lambda: forks.append(1) or 4242) is True
    assert forks == [1], "a bubble with a button must be held by a forked child"

    forks.clear()
    _gui(monkeypatch, False)
    rec = _Recorder()
    monkeypatch.setattr(updates.subprocess, "run", rec)
    assert updates.notify(2, fork=lambda: forks.append(1) or 4242) is True
    assert forks == [], "no button, nothing to hold, no fork"
    assert rec.calls, "the plain bubble is sent by the caller itself"


def test_notify_still_shows_something_when_fork_fails(monkeypatch):
    _no_reader(monkeypatch)
    _gui(monkeypatch, True)
    monkeypatch.setattr(updates.shutil, "which", lambda name: "/usr/bin/" + name)
    rec = _Recorder()
    monkeypatch.setattr(updates.subprocess, "run", rec)

    def boom():
        raise OSError("cannot fork")

    assert updates.notify(5, fork=boom) is True
    assert not any(a.startswith("--action=") for a in rec.calls[0]), \
        "with no holder the button would be a lie"


def test_notify_is_spoken_to_a_screen_reader(monkeypatch):
    from ai2 import a11y
    monkeypatch.setattr(updates.shutil, "which", lambda name: None)
    _gui(monkeypatch, False)
    monkeypatch.setattr(a11y, "reader_active", lambda: True)
    spoken = []
    monkeypatch.setattr(a11y, "speak_once", lambda text: spoken.append(text))
    assert updates.notify(4) is False        # nothing visual, no notify-send
    assert spoken and "ai-2 update" in spoken[0]
