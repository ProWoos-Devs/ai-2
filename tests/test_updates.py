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
    _pamac_open(monkeypatch, False)
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
    _pamac_open(monkeypatch, False)
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


def _pamac_open(monkeypatch, answer):
    """Pin whether Software Updates counts as open (a list or iterator of
    answers, one per round), so a pamac window on the machine running the
    suite cannot change the result."""
    from ai2 import software
    answers = iter(answer) if isinstance(answer, list) else None
    monkeypatch.setattr(software, "gui_running",
                        (lambda: next(answers)) if answers else (lambda: answer))


def test_cli_update_check_stays_quiet_while_software_updates_is_open(tmp_path, monkeypatch, capsys):
    """Reported 2026-09-11: the bubble asked to open Software Updates while it
    was already open. That round is skipped, and the bubble is owed: a later
    round from the cache still reminds once pamac is closed."""
    from ai2 import cli
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    sent, slept = [], []
    monkeypatch.setattr(updates, "notify", lambda n: sent.append(n) or True)
    monkeypatch.setattr(updates, "state_is_fresh", lambda h: True)   # every round cached
    monkeypatch.setattr(updates, "load_state", lambda: {"count": 4, "packages": []})
    _pamac_open(monkeypatch, [True, True, False])
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
    assert sent == [4]             # only the round after pamac closed; not repeated after
    assert capsys.readouterr().out.count("Software Updates is open") == 2


def test_gui_running_matches_this_users_pamac_only(tmp_path, monkeypatch):
    from ai2 import software
    proc = tmp_path / "proc"
    for pid, comm in (("101", "xfce4-panel"), ("202", "pamac-manager")):
        (proc / pid).mkdir(parents=True)
        (proc / pid / "comm").write_text(comm + "\n")
    (proc / "self").mkdir()                          # non-numeric entries are skipped
    assert software.gui_running(str(proc)) is True
    monkeypatch.setattr(os, "getuid", lambda: os.stat(proc).st_uid + 1)
    assert software.gui_running(str(proc)) is False  # someone else's pamac
    assert software.gui_running(str(tmp_path / "missing")) is False


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


class _Bubble:
    """Stands in for a waiting `notify-send --print-id --action`: prints the
    id, stays "on screen" for `rounds` polls (then acts as clicked or
    dismissed), and records signals."""

    def __init__(self, stdout="7\n", rounds=0, exits_on_sigint=True):
        import io
        self.stdout = io.StringIO(stdout)
        self.rounds = rounds
        self.signals = []
        self.exits_on_sigint = exits_on_sigint
        self.cmd = None
        self.returncode = None

    def __call__(self, cmd, *a, **kw):
        self.cmd = cmd
        return self

    def wait(self, timeout=None):
        if self.returncode is None and timeout is not None and self.rounds > 0:
            self.rounds -= 1
            raise updates.subprocess.TimeoutExpired("notify-send", timeout)
        self.returncode = 0
        return 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.signals.append("TERM")
        self.returncode = -15

    def send_signal(self, sig):
        self.signals.append(sig)
        if sig == updates.signal.SIGINT and self.exits_on_sigint:
            self.rounds = 0


def _pacman(monkeypatch, tmp_path, mtimes, locked=False):
    """Feed hold() a sequence of local-db mtimes, one per look."""
    seq = iter(mtimes)
    last = [None]

    def mtime():
        last[0] = next(seq, last[0])
        return last[0]
    monkeypatch.setattr(updates, "_db_mtime", mtime)
    lock = tmp_path / "db.lck"
    if locked:
        lock.write_text("")
    elif lock.exists():
        lock.unlink()
    monkeypatch.setattr(updates, "PACMAN_LOCK", str(lock))


def test_show_carries_the_button_and_acts_on_the_click(monkeypatch, tmp_path):
    from ai2 import software
    opened = []
    monkeypatch.setattr(software, "open_gui", lambda updates=False: opened.append(updates))
    _pacman(monkeypatch, tmp_path, [1.0])
    bubble = _Bubble(stdout="7\nopen\n", rounds=2)
    assert updates.show("t", "b", "Open Software Updates", popen=bubble) is True
    assert any(a.startswith("--action=open=") for a in bubble.cmd)
    assert "--print-id" in bubble.cmd
    assert opened == [True], "clicking the button must open the updates page"
    assert bubble.signals == []


def test_show_falls_back_when_actions_are_unsupported():
    """An old libnotify rejects --action (no id printed). The plain bubble
    must still show."""
    rec = _Recorder()
    bubble = _Bubble(stdout="")
    assert updates.show("t", "b", "Open", run=rec, popen=bubble) is True
    assert len(rec.calls) == 1 and not any(x.startswith("--action=") for x in rec.calls[0])
    assert "-t" in rec.calls[0], "the fallback bubble must still be sticky"


def test_show_does_not_hang_when_the_bubble_failed(monkeypatch):
    """A failed show prints id 0 and then waits forever: end it, fall back."""
    rec = _Recorder(returncode=1)
    bubble = _Bubble(stdout="0\n")
    bubble.returncode = None
    assert updates.show("t", "b", "Open", run=rec, popen=bubble) is False
    assert bubble.signals == ["TERM"]


def test_bubble_closes_itself_once_the_updates_are_installed(monkeypatch, tmp_path):
    """Asked for 2026-09-11: '19 updates available' stayed on screen after the
    update in pamac. A finished transaction plus a fresh check that finds
    nothing closes it, with SIGINT (notify-send's own close path)."""
    from ai2 import software
    opened = []
    monkeypatch.setattr(software, "open_gui", lambda updates=False: opened.append(updates))
    _pacman(monkeypatch, tmp_path, [1.0, 1.0, 2.0])     # unchanged, then a transaction
    monkeypatch.setattr(updates, "check_now", lambda: {"count": 0, "packages": []})
    bubble = _Bubble(rounds=10)
    assert updates.show("t", "b", "Open", popen=bubble) is True
    assert bubble.signals == [updates.signal.SIGINT]
    assert opened == [], "closing the bubble is not a click"


def test_bubble_stays_while_pacman_runs_offline_or_updates_remain(monkeypatch, tmp_path):
    bubble = _Bubble(rounds=3)
    checks = []
    monkeypatch.setattr(updates, "check_now", lambda: checks.append(1) or {"count": 0})
    _pacman(monkeypatch, tmp_path, [1.0, 2.0], locked=True)   # transaction still running
    assert updates.hold(bubble) is False
    assert checks == [] and bubble.signals == []

    bubble = _Bubble(rounds=3)
    monkeypatch.setattr(updates, "check_now", lambda: {"count": 2, "packages": []})
    _pacman(monkeypatch, tmp_path, [1.0, 2.0])
    assert updates.hold(bubble) is False                      # something still pending
    assert bubble.signals == []

    bubble = _Bubble(rounds=4)
    results = iter([None, {"count": 0}])
    checks.clear()
    monkeypatch.setattr(updates, "check_now", lambda: checks.append(1) or next(results))
    _pacman(monkeypatch, tmp_path, [1.0, 2.0])
    now = iter([0.0, 0.0, 10.0, 400.0])     # check fails (retry at 300), too soon, retry
    assert updates.hold(bubble, clock=lambda: next(now)) is True
    assert len(checks) == 2 and bubble.signals == [updates.signal.SIGINT]


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
