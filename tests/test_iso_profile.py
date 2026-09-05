"""The ISO profile's Broadcom contract (2026-09-05): broadcom-wl lives on the
live stick only, and the installer job that copies it to a Broadcom machine
is wired into both Calamares configurations."""
import pathlib
import subprocess

import yaml

ISO = pathlib.Path("iso/profiles/ai2")


def test_broadcom_wl_is_live_only():
    prof = yaml.safe_load((ISO / "profile.yaml").read_text())
    assert "broadcom-wl" not in prof["rootfs"]["packages"]
    assert "broadcom-wl" in prof["livefs"]["packages"]


def test_broadcom_installer_job_is_wired_after_the_keyring():
    for cfg in ("offline", "online"):
        settings = yaml.safe_load((ISO / "live-overlay/etc/calamares-{}/settings.conf".format(cfg)).read_text())
        ids = {i["id"]: i for i in settings["instances"]}
        assert ids["broadcom"]["config"] == "shellprocess@broadcom.conf", cfg
        execs = next(step["exec"] for step in settings["sequence"] if "exec" in step)
        assert execs.index("shellprocess@broadcom") == execs.index("shellprocess@keyring") + 1, cfg
        conf = yaml.safe_load((ISO / "live-overlay/etc/calamares-{}/modules/shellprocess@broadcom.conf".format(cfg)).read_text())
        assert conf["dontChroot"] is True and conf["script"] == ["/usr/share/ai2/broadcom-install.sh ${ROOT}"]


def test_installer_job_script_parses_and_is_executable():
    script = ISO / "live-overlay/usr/share/ai2/broadcom-install.sh"
    assert script.stat().st_mode & 0o111
    assert subprocess.run(["sh", "-n", str(script)]).returncode == 0
    text = script.read_text()
    assert "0x028000" in text and "0x14e4" in text and "exit 0" in text
