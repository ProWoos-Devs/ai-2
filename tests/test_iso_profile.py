"""The ISO profile's Broadcom contract (decision 2026-09-05, option 3): no
broadcom-wl anywhere (Artix's prebuilt package lags its kernel and its dkms
replacement drags in 600 MiB), and no installer job for it. Broadcom chips
the in-kernel drivers do not cover get `ai-2 install broadcom-wifi`."""
import pathlib

import yaml

ISO = pathlib.Path("iso/profiles/ai2")


def test_no_broadcom_wl_on_the_image():
    prof = yaml.safe_load((ISO / "profile.yaml").read_text())
    assert "broadcom-wl" not in prof["rootfs"]["packages"]
    assert "broadcom-wl" not in prof["livefs"]["packages"]


def test_no_broadcom_installer_job():
    for cfg in ("offline", "online"):
        settings = (ISO / f"live-overlay/etc/calamares-{cfg}/settings.conf").read_text()
        assert "broadcom" not in settings, cfg
        assert not list((ISO / f"live-overlay/etc/calamares-{cfg}/modules").glob("*broadcom*")), cfg
    assert not (ISO / "live-overlay/usr/share/ai2/broadcom-install.sh").exists()
    assert "broadcom" not in pathlib.Path("iso/stage-profile.sh").read_text()
