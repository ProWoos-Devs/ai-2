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


def test_the_image_installs_the_packs_as_packages():
    """Until 0.19.0 the packs were unpacked into /etc/skel, which gave every
    account its own copy that no update could refresh. They are packages
    now, so an update refreshes them and pacman can remove one."""
    prof = yaml.safe_load((ISO / "profile.yaml").read_text())
    for pkg in ("ai2-help", "ai2-everyday", "ai2-linux-essentials"):
        assert pkg in prof["rootfs"]["packages"], pkg
    stage = pathlib.Path("iso/stage-profile.sh").read_text()
    assert "etc/skel/.local/share/ai2/doc" not in stage, "the image still copies packs into /etc/skel"
    assert "usr/share/ai2/doc" in pathlib.Path("tools/iso-layer-check.sh").read_text()


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


def test_the_layer_check_is_committed_and_the_vm_dir_is_not_a_scratch_path():
    """The checks that catch a stale overlay copy or a candidate repository in
    an image lived in one developer's notes; they are a script now, and the
    staging script says to run it after every build."""
    import os
    import stat
    check = pathlib.Path("tools/iso-layer-check.sh")
    assert check.exists() and stat.S_IMODE(os.stat(check).st_mode) & 0o111, "not executable"
    body = check.read_text()
    for must in ("ai2-candidate", "rootfs.img", "branding/motd", "VERSION_ID", "origin.yml"):
        assert must in body, f"the layer check no longer looks at {must}"
    assert "iso-layer-check.sh" in pathlib.Path("iso/stage-profile.sh").read_text()
    vm = pathlib.Path("iso/qemu-vm.py").read_text()
    assert "/tmp/claude" not in vm and "AI2_VM_DIR" in vm


def test_the_build_refuses_a_stale_pack_catalog():
    """A release whose packaged catalog is behind, or whose bundled pack files
    do not match it, ships packs nobody can install by name, and nothing said
    so until somebody tried."""
    build = pathlib.Path("packaging/build-packages.sh").read_text()
    assert "sync-pack-catalog.py\" --check" in build
    assert 'refusing to build ai-2 with a stale pack catalog' in build
    workflow = pathlib.Path(".github/workflows/tests.yml").read_text()
    assert "packs.yml" in workflow, "the catalog job no longer runs when the packaged copy changes"


def test_the_iso_checksum_can_be_signed_and_the_readme_says_how():
    """The ISO and its checksum sit on the same page, so the checksum alone
    proves nothing about who built the image. The signature ties it to the
    key that signs every AI-2 package."""
    import os
    import stat
    script = pathlib.Path("iso/sign-iso.sh")
    assert script.exists() and stat.S_IMODE(os.stat(script).st_mode) & 0o111
    body = script.read_text()
    assert "F1889E37B4E5FEC8" in body and "--detach-sign" in body and "gpg --verify" in body
    readme = pathlib.Path("README.md").read_text()
    assert "iso.sha256.sig" in readme and "gpg --verify" in readme


def test_the_installer_slide_names_the_packs_the_image_ships():
    """Rafael, 2026-09-20, reading the slide during an install: it should say
    which packs are on board, by name. A pack added to or dropped from the
    image has to reach this slide too."""
    import yaml
    catalog = {p["id"]: p for p in yaml.safe_load(
        pathlib.Path("ai2/data/packs.yml").read_text())["packs"]}
    prof = yaml.safe_load((ISO / "profile.yaml").read_text())
    shipped = [p for p in prof["rootfs"]["packages"] if p in ("ai2-help", "ai2-everyday",
                                                              "ai2-linux-essentials")]
    slide = (ISO / "live-overlay/usr/share/calamares/branding/ai2/show.qml").read_text()
    words = {1: "one", 2: "two", 3: "three", 4: "four"}
    assert f"{words[len(shipped)]} Knowledge Packs" in slide, "the slide miscounts the packs"
    for pkg in shipped:
        pack_id = pkg[4:] if not pkg.startswith("ai2-help") else "ai2-help"
        title = catalog[pack_id]["title"]
        assert title in slide, f"the slide does not name {title}"
        for lang in ("es", "de"):
            ts = (ISO / f"live-overlay/usr/share/calamares/branding/ai2/lang/calamares-ai2_{lang}.ts").read_text()
            assert title in ts, f"{lang}: the slide translation does not name {title}"
