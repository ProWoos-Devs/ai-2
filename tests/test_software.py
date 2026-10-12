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
    assert software.update(run=_runner(calls), preflight=lambda say, run, sudo: []) == 0
    assert calls == [["/usr/bin/pacman", "-Syu"]]
    assert "/usr/bin/pacman -Syu" in capsys.readouterr().out


def test_update_reports_a_failure(monkeypatch, capsys):
    monkeypatch.setattr(software.os, "geteuid", lambda: 0)
    assert software.update(run=_runner([], returncode=1), preflight=lambda say, run, sudo: []) == 1
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


def test_pamac_restart_button_gets_a_reboot_the_user_may_run():
    """pamac's Restart runs plain `reboot` as the user; runit's reboot is
    root-only, so the button did nothing (reproduced in a VM 2026-09-11). The
    package puts a wrapper ahead of /usr/bin in PATH. Checked statically on
    purpose: executing it on a systemd dev machine would reboot that machine."""
    import pathlib
    import subprocess
    pkgbuild = pathlib.Path("packaging/ai-2/PKGBUILD").read_text(encoding="utf-8")
    assert ('install -Dm755 packaging/ai-2/reboot-wrapper.sh "$pkgdir/usr/local/bin/reboot"'
            in pkgbuild)
    script = pathlib.Path("packaging/ai-2/reboot-wrapper.sh")
    text = script.read_text(encoding="utf-8")
    root_branch = text.index('if [ "$(id -u)" -eq 0 ]; then')
    assert text.index('exec /usr/bin/reboot "$@"', root_branch) < text.index("loginctl reboot")
    assert subprocess.run(["sh", "-n", str(script)]).returncode == 0


def _pacman_shim(tmp_path, broadcom: bool):
    """The wrapper with /usr/bin/pacman rewritten to a fake that records its
    arguments and answers -Qq broadcom-wl the way the test says."""
    import pathlib
    import shutil
    fake = tmp_path / "pacman"
    fake.write_text("#!/bin/sh\necho \"$@\" >> \"$0.log\"\n"
                    + ("[ \"$1\" = -Qq ] && exit 0\n" if broadcom else "[ \"$1\" = -Qq ] && exit 1\n")
                    + "exit 0\n")
    fake.chmod(0o755)
    shim = tmp_path / "shim"
    shim.write_text(pathlib.Path("packaging/ai-2/pacman-wrapper.sh").read_text()
                    .replace("real=/usr/bin/pacman", f"real={fake}"))
    shim.chmod(0o755)
    return shim, fake


def _run_shim(shim, args, answer=None):
    """On a pseudo-terminal, since the shim asks only when stdin and stdout
    are terminals; `answer` is what the person types, None for nothing."""
    import os
    import pty
    import subprocess
    master, slave = pty.openpty()
    proc = subprocess.Popen([str(shim), *args], stdin=slave, stdout=slave, stderr=slave)
    os.close(slave)
    out = b""
    if answer is not None:
        import time
        time.sleep(0.3)
        os.write(master, (answer + "\n").encode())
    while True:
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    rc = proc.wait()
    os.close(master)
    return rc, out.decode(errors="replace")


def test_a_direct_upgrade_passes_through_on_a_machine_without_a_broadcom_package(tmp_path):
    shim, fake = _pacman_shim(tmp_path, broadcom=False)
    rc, out = _run_shim(shim, ["-Syu"])
    assert rc == 0 and "Broadcom" not in out
    assert (tmp_path / "pacman.log").read_text().splitlines()[-1] == "-Syu"


def test_a_direct_upgrade_on_a_broadcom_machine_asks_and_stops_by_default(tmp_path):
    shim, fake = _pacman_shim(tmp_path, broadcom=True)
    rc, out = _run_shim(shim, ["-Syu"], answer="")
    assert rc == 1 and "Broadcom" in out and "ai-2 update" in out
    assert "-Syu" not in (tmp_path / "pacman.log").read_text().splitlines()
    rc, out = _run_shim(shim, ["--sync", "--sysupgrade"], answer="y")
    assert rc == 0
    assert (tmp_path / "pacman.log").read_text().splitlines()[-1] == "--sync --sysupgrade"


def test_everything_that_is_not_an_upgrade_never_asks(tmp_path):
    import subprocess
    shim, fake = _pacman_shim(tmp_path, broadcom=True)
    for args in (["-Ss", "htop"], ["-S", "htop"], ["-Qu"], ["-Rns", "broadcom-wl"], ["-Q"], ["-Sy"],
                 ["--query", "--upgrades"], ["-U", "x.pkg.tar.zst"]):
        rc, out = _run_shim(shim, args)
        assert rc == 0 and "Broadcom" not in out, args
        assert (tmp_path / "pacman.log").read_text().splitlines()[-1] == " ".join(args)
    # an upgrade with no terminal (a script, a cron job) goes straight through
    rc = subprocess.run([str(shim), "-Syu"], stdin=subprocess.DEVNULL, capture_output=True).returncode
    assert rc == 0 and (tmp_path / "pacman.log").read_text().splitlines()[-1] == "-Syu"


def test_the_package_puts_the_pacman_wrapper_ahead_of_usr_bin_and_update_avoids_it():
    import pathlib
    import subprocess
    pkgbuild = pathlib.Path("packaging/ai-2/PKGBUILD").read_text(encoding="utf-8")
    assert 'install -Dm755 packaging/ai-2/pacman-wrapper.sh "$pkgdir/usr/local/bin/pacman"' in pkgbuild
    assert subprocess.run(["sh", "-n", "packaging/ai-2/pacman-wrapper.sh"]).returncode == 0
    assert '"/usr/bin/pacman", "-Syu"' in pathlib.Path("ai2/software.py").read_text(encoding="utf-8")
