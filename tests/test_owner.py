"""Install for another owner (ai2/owner.py): what the install leaves in the
target, what the first boot asks, and that the second half undoes the first."""
import os
import pathlib
import subprocess

import yaml

from ai2 import cli, owner

ISO = pathlib.Path("iso/profiles/ai2")


class Proc:
    def __init__(self, rc=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = rc, stdout, stderr


def _root(tmp_path):
    root = tmp_path / "root"
    (root / "etc/lightdm").mkdir(parents=True)
    (root / "etc/lightdm/lightdm.conf").write_text("[LightDM]\nrun-directory=/run/lightdm\n[Seat:*]\ngreeter-session=lightdm-gtk-greeter\n")
    (root / "etc/hosts").write_text("127.0.0.1  localhost\n::1        localhost\n127.0.1.1  ai2-live\n")
    return root


def test_prepare_leaves_the_first_boot_asking(tmp_path):
    root = _root(tmp_path)
    calls = []
    said = []
    rc = owner.prepare(str(root), run=lambda cmd, **kw: calls.append(cmd) or Proc(), say=said.append)
    assert rc == 0
    assert calls[0] == ["groupadd", "-f", "autologin"]
    assert calls[1][0] == "useradd" and calls[1][-1] == owner.TEMP_USER and "autologin" in calls[1]
    assert (root / "etc/hostname").read_text() == "ai2-pc\n"
    hosts = (root / "etc/hosts").read_text()
    assert "127.0.1.1  ai2-pc" in hosts and "ai2-live" not in hosts
    sudoers = root / "etc/sudoers.d/ai2-owner-setup"
    assert sudoers.read_text().splitlines()[-1] == f"{owner.TEMP_USER} ALL=(root) NOPASSWD: /usr/bin/ai-2 owner-setup"
    assert oct(sudoers.stat().st_mode & 0o777) == "0o440"
    conf = (root / "etc/lightdm/lightdm.conf").read_text()
    assert conf.startswith("[LightDM]\n") and f"autologin-user={owner.TEMP_USER}" in conf
    assert f"autologin-session={owner.SESSION}" in conf and owner.BLOCK_END in conf
    assert owner.pending(str(root))


def test_prepare_opens_the_copied_live_connections(tmp_path):
    root = _root(tmp_path)
    nm = root / "etc/NetworkManager/system-connections"
    nm.mkdir(parents=True)
    (nm / "home.nmconnection").write_text("[connection]\nid=home\npermissions=user:None:;\n\n[wifi]\nssid=home\n")
    (nm / "office.nmconnection").write_text("[connection]\nid=office\npermissions=user:maria:;\n")
    assert owner.prepare(str(root), run=lambda cmd, **kw: Proc(), say=lambda *a: None) == 0
    assert (nm / "home.nmconnection").read_text() == "[connection]\nid=home\npermissions=\n\n[wifi]\nssid=home\n"
    assert "user:maria" in (nm / "office.nmconnection").read_text()


def test_prepare_reports_a_failed_useradd(tmp_path):
    root = _root(tmp_path)
    said = []
    rc = owner.prepare(str(root), run=lambda cmd, **kw: Proc(1, stderr="boom") if cmd[0] == "useradd" else Proc(),
                       say=said.append)
    assert rc == 1 and "useradd" in said[-1] and "boom" in said[-1]
    assert not owner.pending(str(root))


def test_finish_undoes_everything_prepare_did(tmp_path):
    root = _root(tmp_path)
    before = (root / "etc/lightdm/lightdm.conf").read_text()
    owner.prepare(str(root), run=lambda cmd, **kw: Proc(), say=lambda *a: None)
    calls = []
    owner.finish(str(root), run=lambda cmd, **kw: calls.append(cmd) or Proc())
    assert (root / "etc/lightdm/lightdm.conf").read_text() == before
    assert not (root / "etc/sudoers.d/ai2-owner-setup").exists() and not owner.pending(str(root))
    assert calls == [["userdel", "-r", "-f", owner.TEMP_USER]]


def test_suggestions():
    assert owner.suggest_login("María José Pérez") == "maria"
    assert owner.suggest_login("  ") == "user"
    assert owner.suggest_login("42 Dogs") == "user42"
    assert owner.suggest_login("Jürgen") == "jurgen"
    assert owner.suggest_hostname("maria") == "maria-pc"


def test_setup_refuses_a_computer_not_installed_for_another_owner(tmp_path):
    said = []
    assert owner.run_setup(say=said.append, root=str(tmp_path)) == 1
    assert "useradd" in said[-1]


def test_setup_asks_checks_creates_and_cleans_up(tmp_path):
    root = _root(tmp_path)
    owner.prepare(str(root), run=lambda cmd, **kw: Proc(), say=lambda *a: None)
    answers = iter(["", "María José", "Root", "taken", "", "", ""])   # name twice, logins, host
    secrets = iter(["abc", "secret1", "other", "secret1", "secret1"])
    said, calls, slept = [], [], []

    def run(cmd, **kw):
        calls.append((cmd, kw.get("input")))
        if cmd[:2] == ["getent", "passwd"]:
            return Proc(0 if cmd[2] == "taken" else 2)
        if cmd[:2] == ["getent", "group"]:
            return Proc(0, "users:x:982:\nwheel:x:998:\naudio:x:995:\n")
        return Proc()

    rc = owner.run_setup(ask=lambda q: next(answers), secret=lambda q: next(secrets), say=said.append,
                         run=run, root=str(root), reboot=True, sleep=slept.append)
    assert rc == 0
    text = "\n".join(said)
    assert "only lowercase" in text and "already taken" in text
    assert "At least 4" in text and "do not match" in text
    useradd = next(c for c, _ in calls if c[0] == "useradd" and c[-1] != owner.TEMP_USER)
    assert useradd == ["useradd", "-m", "-U", "-s", "/bin/bash", "-c", "María José", "-G", "users,wheel,audio", "maria"]
    chpasswd = next(i for c, i in calls if c == ["chpasswd"])
    assert chpasswd == "maria:secret1\nroot:secret1\n"
    assert (root / "etc/hostname").read_text() == "maria-pc\n"
    assert "127.0.1.1  maria-pc" in (root / "etc/hosts").read_text()
    assert ["userdel", "-r", "-f", owner.TEMP_USER] in [c for c, _ in calls]
    assert not owner.pending(str(root))
    assert calls[-1][0] == ["reboot"] and slept == [6]
    assert "Done, María José" in said[-1]


def test_command_needs_root_and_prepare_is_a_flag(monkeypatch, capsys):
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    assert cli.main(["owner-setup"]) == 1 and cli.main(["owner-setup", "--prepare"]) == 1
    assert "sudo ai-2 owner-setup" in capsys.readouterr().out
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(owner, "prepare", lambda: 7)
    assert cli.main(["owner-setup", "--prepare"]) == 7
    monkeypatch.setattr(owner, "run_setup", lambda reboot: 0 if reboot else 5)
    assert cli.main(["owner-setup", "--no-reboot"]) == 5 and cli.main(["owner-setup"]) == 0


def test_the_package_ships_the_session_and_the_script():
    pkgbuild = pathlib.Path("packaging/ai-2/PKGBUILD").read_text(encoding="utf-8")
    assert 'install -Dm755 packaging/ai-2/owner-setup-session.sh "$pkgdir/usr/lib/ai2/owner-setup-session"' in pkgbuild
    assert f'install -Dm644 branding/desktop/ai2-owner-setup.desktop "$pkgdir/usr/share/xsessions/{owner.SESSION}.desktop"' in pkgbuild
    session = pathlib.Path("packaging/ai-2/owner-setup-session.sh").read_text(encoding="utf-8")
    assert subprocess.run(["sh", "-n", "packaging/ai-2/owner-setup-session.sh"]).returncode == 0
    assert "sudo -n /usr/bin/ai-2 owner-setup" in session
    # the session loops while the owner is owed: lightdm shows its greeter
    # after an automatic session ends, and the temporary account cannot log in
    assert f"while [ -e {owner.PENDING} ]" in session and "exec xfce4-terminal" not in session
    xsession = pathlib.Path("branding/desktop/ai2-owner-setup.desktop").read_text(encoding="utf-8")
    assert "Exec=/usr/lib/ai2/owner-setup-session" in xsession and "NoDisplay=true" in xsession


def test_the_stick_offers_the_owner_install():
    settings = yaml.safe_load((ISO / "live-overlay/etc/calamares-owner/settings.conf").read_text())
    show = settings["sequence"][0]["show"]
    execs = settings["sequence"][1]["exec"]
    assert "users" not in show and "users" not in execs
    assert "postcfg" not in execs           # builds a path from the Users page's name
    assert execs.index("shellprocess@owner") == execs.index("networkcfg") + 1 > execs.index("displaymanager")
    assert {i["id"] for i in settings["instances"]} >= {"owner", "keyring", "label"}
    job = yaml.safe_load((ISO / "live-overlay/etc/calamares-owner/modules/shellprocess@owner.conf").read_text())
    assert job["dontChroot"] is False and job["script"] == ["/usr/bin/ai-2 owner-setup --prepare"]
    offline = yaml.safe_load((ISO / "live-overlay/etc/calamares-offline/settings.conf").read_text())
    # the same install otherwise: every other step in the same order
    assert [s for s in offline["sequence"][1]["exec"] if s not in ("users", "postcfg")] == \
           [s for s in execs if s != "shellprocess@owner"]
    launcher = (ISO / "live-overlay/usr/bin/ai2-install").read_text()
    assert "--for-another-owner" in launcher and "/etc/calamares-owner" in launcher
    entry = (ISO / "live-overlay/usr/share/applications/ai2-install-owner.desktop").read_text()
    assert "Exec=ai2-install --for-another-owner" in entry
    items = (ISO / "live-overlay/usr/bin/desktop-items").read_text()
    assert "ai2-install-owner.desktop" in items
    assert items.index("ai2-install-owner.desktop") < items.index("calamares-config-switcher.desktop")
    stage = pathlib.Path("iso/stage-profile.sh").read_text()
    assert 'calamares-offline/modules/." "$DST/live-overlay/etc/calamares-owner/modules/"' in stage


def test_every_live_guide_mentions_it():
    import json
    for info in json.load(open("ai2/data/languages.json")).values():
        text = pathlib.Path("branding", info["start_here"]).read_text(encoding="utf-8")
        assert "Install for someone else" in text, info["start_here"]
