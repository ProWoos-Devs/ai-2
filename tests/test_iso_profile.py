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


def test_the_image_never_shadows_a_file_the_ai2_package_installs():
    """The root overlay is copied over the installed packages, so a file that
    exists in both places silently wins over the package's. Three stale copies
    of START-HERE sat there from 2026-09-03 to 2026-09-19 and no edit to the
    real ones reached a stick: the Knowledge Packs text Rafael was told was on
    his test image was not. Whatever the PKGBUILD installs must not also be in
    the overlay."""
    import re
    root = pathlib.Path(__file__).resolve().parent.parent
    pkgbuild = (root / "packaging/ai-2/PKGBUILD").read_text(encoding="utf-8")
    installed = set(re.findall(r'"\$pkgdir(/[^"]+)"', pkgbuild))
    assert installed, "found no install targets in the PKGBUILD"
    overlay = root / "iso/profiles/ai2/root-overlay"
    shadowed = sorted(p for p in installed if (overlay / p.lstrip("/")).is_file())
    assert not shadowed, f"the root overlay shadows files the ai-2 package installs: {shadowed}"


# Overlay files that share a name with a source file on purpose and are meant
# to differ from it.
DELIBERATE_VARIANTS = {
    # the first-login setup is for installed systems, so the live session hides it
    "live-overlay/etc/xdg/autostart/ai2-setup.desktop",
    # another runit service altogether; every runit service's script is called `run`
    "live-overlay/etc/runit/sv/pacman-init/run",
}


def test_overlay_copies_of_our_own_files_have_not_drifted():
    """Some files live twice, once where the package or the branding keeps them
    and once in an image overlay, because the image needs them in a place the
    package does not write to (/etc/motd, the greeter configuration, the GRUB
    theme). A copy nobody remembers goes stale: /etc/motd on the image was the
    2026-09-03 text until 2026-09-19 and never gained the Knowledge Packs line
    the real one had. So a copy is byte-identical to its source, or it is
    listed above with the reason it differs."""
    root = pathlib.Path(__file__).resolve().parent.parent
    sources = {}
    for base in (root / "branding", root / "packaging/ai-2"):
        for p in base.rglob("*"):
            if p.is_file():
                sources.setdefault(p.name, []).append(p)
    profile = root / "iso/profiles/ai2"
    drifted = []
    for overlay in ("root-overlay", "live-overlay"):
        for p in (profile / overlay).rglob("*"):
            rel = p.relative_to(profile).as_posix()
            if not p.is_file() or p.is_symlink() or p.name not in sources or rel in DELIBERATE_VARIANTS:
                continue
            if not any(p.read_bytes() == s.read_bytes() for s in sources[p.name]):
                drifted.append(f"{rel} differs from {sources[p.name][0].relative_to(root).as_posix()}")
    assert not drifted, "stale copies in the image overlays, copy the source over them: " + "; ".join(drifted)
    for rel in DELIBERATE_VARIANTS:
        assert (profile / rel).is_file(), f"{rel} is listed as a deliberate variant but is gone"


def test_every_installer_job_has_its_config_and_script():
    """A job left in the sequence after its config or script is deleted fails
    the install, and a config with no job runs nothing: both are silent."""
    import re
    for cfg in ("offline", "online"):
        base = ISO / f"live-overlay/etc/calamares-{cfg}"
        if not (base / "settings.conf").exists():
            continue
        settings = yaml.safe_load((base / "settings.conf").read_text())
        declared = {i["id"]: i for i in settings.get("instances") or []}
        used = {step.split("@", 1)[1] for group in settings["sequence"]
                for step in (group.get("exec") or []) if "@" in step}
        assert used == set(declared), f"{cfg}: instances and sequence disagree"
        for name, inst in declared.items():
            conf = base / "modules" / inst["config"]
            assert conf.exists(), f"{cfg}: {conf} is missing"
            for line in yaml.safe_load(conf.read_text())["script"]:
                cmd = line["command"] if isinstance(line, dict) else line
                script = re.search(r"(/usr/share/ai2/[\w.-]+)", cmd)
                if script:
                    path = script.group(1).lstrip("/")
                    assert (ISO / f"root-overlay/{path}").exists() or (ISO / f"live-overlay/{path}").exists(), \
                        f"{cfg}: {name} runs {script.group(1)}, which no overlay ships"


def test_the_installed_desktop_never_idle_suspends():
    """The desktop calls a machine idle when nobody types, even while it is
    generating an answer (reproduced on RMM-PC 2026-08-13). The elogind
    drop-in from `ai-2 init --apply` only lands after the first login, so the
    image carries the desktop defaults too."""
    import xml.etree.ElementTree as ET
    conf = ISO / "root-overlay/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/xfce4-power-manager.xml"
    props = {p.get("name"): p.get("value") for p in ET.parse(conf).getroot().iter("property")}
    assert props["inactivity-on-ac"] == "0" and props["inactivity-on-battery"] == "0"
    assert props["lock-screen-suspend-hibernate"] == "false"
