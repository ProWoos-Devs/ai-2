"""Adding software and updating: the name-to-package mapping, the service a
daemon needs enabled, and the fact that nothing runs without printing the
command first."""
import pytest

from ai2 import software


class FakeProc:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def _runner(calls, returncode=0):
    def run(cmd, *a, **kw):
        calls.append(cmd)
        return FakeProc(returncode)
    return run


def test_catalog_entries_are_well_formed():
    ids = set()
    for item in software.CATALOG:
        assert item["id"] not in ids
        ids.add(item["id"])
        assert item["id"] == item["id"].lower()
        assert item["what"] and not item["what"].endswith(".")
        assert item["packages"], item["id"]
        # a daemon needs the service name and the package that ships it, both
        # per init system, and they must cover the same init systems
        services = item.get("services") or {}
        if services:
            assert set(services) == set(item.get("service_packages") or {}), item["id"]
            assert "runit" in services, item["id"]


def test_resolve_maps_short_names_and_passes_the_rest_through():
    packages, services, matched = software.resolve(["office", "htop"], "runit")
    assert packages == ["libreoffice-still", "htop"]
    assert services == []
    assert matched == ["office"]


def test_resolve_adds_the_init_specific_service_package():
    packages, services, _ = software.resolve(["printing"], "runit")
    assert "cups" in packages and "cups-runit" in packages
    assert services == ["cupsd"]
    # another init system must not get runit's package
    packages, _, _ = software.resolve(["printing"], "systemd")
    assert "cups-runit" not in packages


def test_resolve_does_not_repeat_a_package():
    packages, _, _ = software.resolve(["office", "office", "libreoffice-still"], "runit")
    assert packages == ["libreoffice-still"]


def test_install_prints_the_command_before_running_it(monkeypatch, capsys):
    monkeypatch.setattr(software.os, "geteuid", lambda: 0)
    calls = []
    assert software.install(["office"], "runit", run=_runner(calls)) == 0
    assert calls == [["pacman", "-S", "--needed", "libreoffice-still"]]
    out = capsys.readouterr().out
    assert "pacman -S --needed libreoffice-still" in out
    assert "LibreOffice" in out


def test_install_uses_sudo_when_not_root(monkeypatch):
    monkeypatch.setattr(software.os, "geteuid", lambda: 1000)
    calls = []
    software.install(["htop"], "runit", say=lambda *a: None, run=_runner(calls))
    assert calls[0][0] == "sudo"


def test_install_with_no_names_lists_the_catalog(capsys):
    assert software.install([], "runit") == 0
    out = capsys.readouterr().out
    assert "office" in out and "printing" in out


def test_failed_install_never_touches_services(monkeypatch):
    monkeypatch.setattr(software.os, "geteuid", lambda: 0)
    calls = []
    rc = software.install(["printing"], "runit", say=lambda *a: None,
                          run=_runner(calls, returncode=1))
    assert rc == 1
    assert len(calls) == 1, "the service was enabled after a failed install"


def test_install_enables_the_service_it_needs(monkeypatch):
    monkeypatch.setattr(software.os, "geteuid", lambda: 0)

    class Backend:
        def is_enabled(self, service):
            return False

        def available_services(self):
            return ["cupsd"]

        def enable_cmd(self, service):
            return ["ln", "-sfn", f"/etc/runit/sv/{service}", f"/enabled/{service}"]

    monkeypatch.setattr("ai2.backends.get_service_backend", lambda init: Backend())
    calls = []
    assert software.install(["printing"], "runit", say=lambda *a: None,
                            run=_runner(calls)) == 0
    assert calls[-1] == ["ln", "-sfn", "/etc/runit/sv/cupsd", "/enabled/cupsd"]


def test_update_runs_one_full_upgrade(monkeypatch, capsys):
    monkeypatch.setattr(software.os, "geteuid", lambda: 0)
    calls = []
    assert software.update(run=_runner(calls)) == 0
    assert calls == [["pacman", "-Syu"]]
    assert "pacman -Syu" in capsys.readouterr().out


def test_update_reports_a_failure(monkeypatch, capsys):
    monkeypatch.setattr(software.os, "geteuid", lambda: 0)
    assert software.update(run=_runner([], returncode=1)) == 1
    assert "keyring" in capsys.readouterr().out


def test_gui_is_optional(monkeypatch):
    monkeypatch.setattr(software.shutil, "which", lambda name: None)
    assert software.gui_available() is False
    assert software.open_gui() is False


def test_cli_install_and_update_reach_the_module(monkeypatch):
    from ai2 import cli
    seen = {}

    def fake_install(names, init_system="", **kw):
        seen["install"] = names
        return 0

    def fake_update(*a, **kw):
        seen["update"] = True
        return 0

    monkeypatch.setattr(software, "install", fake_install)
    monkeypatch.setattr(software, "update", fake_update)
    assert cli.main(["install", "office"]) == 0
    assert cli.main(["update"]) == 0
    assert seen["install"] == ["office"]
    assert seen["update"] is True
