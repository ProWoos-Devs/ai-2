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
