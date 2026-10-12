"""Per-user migrations (ai2/migrate.py): the rules every shipped script must
keep, the runner's order and failure handling, and the places that call it."""
import os
import pathlib
import subprocess

import pytest

from ai2 import migrate

SHIPPED = pathlib.Path("migrations")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An empty home with every XDG dir inside it, so no test reads or writes
    the developer's own state."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("XDG_STATE_HOME", str(h / ".local/state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(h / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(h / ".local/share"))
    return h


def _write(directory: pathlib.Path, name: str, body: str) -> None:
    (directory / name).write_text(body, encoding="utf-8")


def test_every_shipped_migration_keeps_the_rules():
    scripts = sorted(SHIPPED.glob("*.sh"))
    assert scripts, "no migrations shipped"
    for path in scripts:
        assert migrate.NAME_RE.match(path.name), f"{path.name}: must be YYYYMMDD-NN-what-it-does.sh"
        text = path.read_text(encoding="utf-8")
        assert not text.startswith("#!"), f"{path.name}: no shebang, the runner picks the interpreter"
        assert text.startswith("# ") and len(migrate.describe(str(path))) > 10, \
            f"{path.name}: the first line is one sentence saying what it does"
        assert subprocess.run(["bash", "-n", str(path)]).returncode == 0, f"{path.name}: bash -n"
        code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
        assert "ai-2 " not in code and "sudo" not in code, f"{path.name}: own files only, no ai-2 calls"
    stray = [p.name for p in SHIPPED.iterdir() if p.name != "README.md" and not p.name.endswith(".sh")]
    assert stray == [], f"not migrations: {stray}"


def test_every_shipped_migration_runs_twice_on_an_empty_home(home):
    said = []
    completed, failed = migrate.run_pending(say=said.append, directory=str(SHIPPED))
    assert failed is None
    assert completed == [p.name for p in sorted(SHIPPED.glob("*.sh"))]
    for name in completed:
        assert (home / ".local/state/ai2/migrations" / name).read_text().startswith("done ")
    assert migrate.pending(str(SHIPPED)) == []
    # the markers make the second run a no-op; without them every script must still exit 0
    for name in completed:
        (home / ".local/state/ai2/migrations" / name).unlink()
    completed2, failed2 = migrate.run_pending(say=lambda s: None, directory=str(SHIPPED))
    assert (completed2, failed2) == (completed, None)


def test_runs_in_name_order_marks_each_and_stops_at_the_first_failure(home, tmp_path):
    d = tmp_path / "migrations"
    d.mkdir()
    _write(d, "20260101-01-first.sh", "# First thing.\necho first >> \"$AI2_STATE_DIR/order\"\n")
    _write(d, "20260101-02-broken.sh", "# Broken thing.\necho broken >> \"$AI2_STATE_DIR/order\"\nexit 3\n")
    _write(d, "20260102-01-third.sh", "# Third thing.\necho third >> \"$AI2_STATE_DIR/order\"\n")
    _write(d, "notes.txt", "not a migration\n")
    _write(d, "99-wrong-name.sh", "# Wrong name.\necho wrong >> \"$AI2_STATE_DIR/order\"\n")
    (home / ".local/state/ai2").mkdir(parents=True)
    said = []
    completed, failed = migrate.run_pending(say=said.append, directory=str(d))
    assert completed == ["20260101-01-first.sh"] and failed == "20260101-02-broken.sh"
    assert (home / ".local/state/ai2/order").read_text() == "first\nbroken\n"
    assert migrate.pending(str(d)) == ["20260101-02-broken.sh", "20260102-01-third.sh"]
    text = "\n".join(said)
    assert "ok    First thing." in text and "FAIL  Broken thing." in text and "code 3" in text
    assert "ai-2 migrate" in text and "Third thing" not in text
    # fixed in the next release: the rerun starts at the one that failed
    _write(d, "20260101-02-broken.sh", "# Mended thing.\necho mended >> \"$AI2_STATE_DIR/order\"\n")
    completed, failed = migrate.run_pending(say=said.append, directory=str(d))
    assert (completed, failed) == (["20260101-02-broken.sh", "20260102-01-third.sh"], None)
    assert (home / ".local/state/ai2/order").read_text() == "first\nbroken\nmended\nthird\n"
    assert migrate.run_pending(say=said.append, directory=str(d)) == ([], None)


def test_a_migration_sees_the_account_dirs_and_the_version(home, tmp_path):
    d = tmp_path / "migrations"
    d.mkdir()
    _write(d, "20260101-01-env.sh",
           "# Env check.\nmkdir -p \"$AI2_CONFIG_DIR\"\n"
           "echo \"$AI2_STATE_DIR|$AI2_CONFIG_DIR|$AI2_DATA_DIR|$AI2_VERSION|$PWD\" > \"$AI2_CONFIG_DIR/env\"\n")
    assert migrate.run_pending(say=lambda s: None, directory=str(d))[1] is None
    from ai2 import __version__
    assert (home / ".config/ai2/env").read_text().strip() == "|".join([
        str(home / ".local/state/ai2"), str(home / ".config/ai2"), str(home / ".local/share/ai2"),
        __version__, str(home)])


def test_the_first_migration_forgets_a_saved_update_count_once(home):
    state = home / ".local/state/ai2"
    state.mkdir(parents=True)
    (state / "updates.json").write_text('{"count": 51, "checked_at": 1}')
    said = []
    migrate.run_pending(say=said.append, directory=str(SHIPPED))
    assert not (state / "updates.json").exists()
    assert "forgotten" in "\n".join(said)


def test_quiet_run_says_nothing_and_writes_the_log(home, tmp_path, capsys):
    d = tmp_path / "migrations"
    d.mkdir()
    _write(d, "20260101-01-thing.sh", "# A thing.\necho did it\n")
    assert migrate.run_quietly(str(d)) == 0
    assert capsys.readouterr().out == ""
    log = (home / ".local/state/ai2/migrate.log").read_text()
    assert "ok    A thing." in log and "did it" in log
    # nothing pending: nothing appended
    assert migrate.run_quietly(str(d)) == 0
    assert (home / ".local/state/ai2/migrate.log").read_text() == log
    _write(d, "20260101-02-bad.sh", "# Bad thing.\nfalse\n")
    assert migrate.run_quietly(str(d)) == 1
    assert "FAIL  Bad thing." in (home / ".local/state/ai2/migrate.log").read_text()


def test_update_finishes_with_the_migrations_only_after_a_successful_upgrade(monkeypatch):
    from ai2 import cli, software
    calls = []
    monkeypatch.setattr(migrate, "run_pending", lambda *a, **k: calls.append("migrate") or ([], None))
    monkeypatch.setattr(cli, "_mention_knowledge_packs", lambda: calls.append("packs"))
    monkeypatch.setattr(software, "update", lambda: 1)
    assert cli.main(["update"]) == 1 and calls == []
    monkeypatch.setattr(software, "update", lambda: 0)
    assert cli.main(["update"]) == 0 and calls == ["migrate", "packs"]


def test_cli_migrate_lists_runs_and_is_quiet_at_login(home, tmp_path, monkeypatch, capsys):
    from ai2 import cli, sysinfo
    d = tmp_path / "migrations"
    d.mkdir()
    _write(d, "20260101-01-thing.sh", "# A thing.\n")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", str(d))
    monkeypatch.setattr(sysinfo, "is_live_session", lambda: False)
    assert cli.main(["migrate", "--pending"]) == 0
    assert capsys.readouterr().out.strip() == "20260101-01-thing.sh  A thing."
    assert cli.main(["migrate"]) == 0
    assert "ok    A thing." in capsys.readouterr().out
    assert cli.main(["migrate", "--pending"]) == 1
    assert cli.main(["migrate"]) == 0
    assert "Nothing pending" in capsys.readouterr().out
    _write(d, "20260101-02-more.sh", "# More.\n")
    assert cli.main(["migrate", "--quiet"]) == 0
    assert capsys.readouterr().out == ""
    assert "ok    More." in (home / ".local/state/ai2/migrate.log").read_text()


def test_the_live_session_runs_no_migration(home, tmp_path, monkeypatch, capsys):
    from ai2 import cli, sysinfo
    d = tmp_path / "migrations"
    d.mkdir()
    _write(d, "20260101-01-thing.sh", "# A thing.\ntouch \"$AI2_STATE_DIR/ran\"\n")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", str(d))
    monkeypatch.setattr(sysinfo, "is_live_session", lambda: True)
    assert cli.main(["migrate", "--quiet"]) == 0 and cli.main(["migrate"]) == 0
    assert "live session" in capsys.readouterr().out
    assert not (home / ".local/state/ai2/ran").exists()


def test_doctor_warns_about_pending_migrations(home, tmp_path, monkeypatch):
    from ai2 import doctor
    d = tmp_path / "migrations"
    d.mkdir()
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", str(d))
    assert doctor.check_migrations().status == doctor.OK
    _write(d, "20260101-01-thing.sh", "# A thing.\n")
    c = doctor.check_migrations()
    assert c.status == doctor.WARN and "1 pending" in c.detail and "ai-2 migrate" in c.detail


def test_login_runs_the_migrations_first_and_the_package_ships_them():
    script = pathlib.Path("branding/ai2-first-boot").read_text(encoding="utf-8")
    assert script.index("ai-2 migrate --quiet") < script.index("ai-2 guide --place-desktop")
    pkgbuild = pathlib.Path("packaging/ai-2/PKGBUILD").read_text(encoding="utf-8")
    assert 'install -m644 migrations/*.sh "$pkgdir/usr/share/ai2/migrations/"' in pkgbuild
    assert migrate.MIGRATIONS_DIR == "/usr/share/ai2/migrations"
