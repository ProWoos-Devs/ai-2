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


def test_bundled_packs_match_the_catalog():
    """The knowledge packs staged into /etc/skel are the files the catalog
    describes. A stale pack file in git would otherwise ship silently and
    disagree with the checksum every other install path verifies."""
    import hashlib
    import pathlib
    import yaml
    root = pathlib.Path(__file__).resolve().parent.parent
    catalog = yaml.safe_load((root / "ai2/data/packs.yml").read_text())
    entries = {p["id"]: p for p in catalog["packs"]}
    files = sorted((root / "iso/packs").glob("*.ai2pack"))
    assert {f.stem for f in files} == set(entries), "iso/packs and the catalog list different packs"
    for f in files:
        data = f.read_bytes()
        entry = entries[f.stem]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], f"{f.name}: sha256"
        assert len(data) == entry["size_bytes"], f"{f.name}: size"
