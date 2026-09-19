"""Packaging invariants that no build can catch by itself."""
import hashlib
import pathlib

PKG = pathlib.Path("packaging")


def test_gate_copies_are_identical():
    """makepkg sources must sit next to their PKGBUILD, so the ISA gate lives
    twice. Both engines rely on the same per-file and constructors gate; a
    fix in one copy that never reaches the other would silently weaken it."""
    llama = (PKG / "ai2-llama-cpp" / "isa-check.sh").read_bytes()
    whisper = (PKG / "ai2-whisper-cpp" / "isa-check.sh").read_bytes()
    assert llama == whisper


def test_whisper_package_is_one_package_with_dispatch():
    text = (PKG / "ai2-whisper-cpp" / "PKGBUILD").read_text()
    assert "pkgname=ai2-whisper-cpp\n" in text and "pkgbase=" not in text
    for flag in ("-DGGML_BACKEND_DL=ON", "-DGGML_CPU_ALL_VARIANTS=ON", "-DGGML_NATIVE=OFF",
                 "-DWHISPER_COMMON_FFMPEG=OFF", "-DWHISPER_SDL2=OFF", "-DWHISPER_USE_SYSTEM_GGML=OFF"):
        assert flag in text, flag
    assert "isa-check.sh ctors" in text and "libggml-cpu-x64.so) bash ../../isa-check.sh baseline" in text


def _etc_refresh_case(tmp_path, etc_motd: bytes | None, also_known: bytes | None = None):
    """Run etc-refresh.sh against a fake root: the script with its absolute
    paths rewritten to tmp_path, so nothing on this machine is touched.
    `also_known` is a copy the list should call one of ours (an older shipped
    motd, which is the case that matters; the real list is built from git by
    tools/update-etc-known.py)."""
    import shutil
    import subprocess
    root = pathlib.Path(tmp_path)
    (root / "usr/share/ai2").mkdir(parents=True)
    (root / "etc/lightdm").mkdir(parents=True)
    shutil.copy("branding/motd", root / "usr/share/ai2/motd")
    shutil.copy("branding/lightdm-gtk-greeter.conf", root / "usr/share/ai2/lightdm-gtk-greeter.conf")
    known = pathlib.Path("packaging/ai-2/etc-known.sha256").read_text()
    if also_known is not None:
        known += f"{hashlib.sha256(also_known).hexdigest()}  motd\n"
    (root / "usr/share/ai2/etc-known.sha256").write_text(known)
    if etc_motd is not None:
        (root / "etc/motd").write_bytes(etc_motd)
    script = pathlib.Path("packaging/ai-2/etc-refresh.sh").read_text()
    run = root / "etc-refresh.sh"
    run.write_text(script.replace("/usr/share/ai2/", f"{root}/usr/share/ai2/")
                         .replace("/etc/motd", f"{root}/etc/motd")
                         .replace("/etc/lightdm/", f"{root}/etc/lightdm/"))
    out = subprocess.run(["sh", str(run)], capture_output=True, text=True, check=True).stdout
    return root, out


def test_the_etc_hook_updates_an_untouched_file_and_never_a_changed_one(tmp_path):
    """/etc/motd and the greeter arrive from the ISO overlay and were never
    refreshed by an upgrade, so an old machine kept the login message of its
    image. Replaced only when it is still a copy AI-2 shipped."""
    current = pathlib.Path("branding/motd").read_bytes()
    older = b"AI-2\n\nthe login message of an older image\n"
    # an /etc/motd from an older AI-2: brought up to date
    root, out = _etc_refresh_case(tmp_path / "old", older, also_known=older)
    assert (root / "etc/motd").read_bytes() == current and "brought up to date" in out
    assert (root / "etc/lightdm/lightdm-gtk-greeter.conf").exists(), "a missing file is installed"
    # one the user edited: kept, with the new version beside it
    mine = current + b"\n# my own line\n"
    root, out = _etc_refresh_case(tmp_path / "mine", mine)
    assert (root / "etc/motd").read_bytes() == mine and "was changed on this computer" in out
    assert (root / "etc/motd.ai2new").read_bytes() == current
    # already current: nothing said, nothing written beside it
    root, out = _etc_refresh_case(tmp_path / "same", current)
    assert out == "" and not (root / "etc/motd.ai2new").exists()


def test_the_known_list_has_the_files_as_they_are_now():
    """tools/update-etc-known.py must be re-run when either file changes, or
    the hook would treat the new text as somebody's local edit."""
    known = pathlib.Path("packaging/ai-2/etc-known.sha256").read_text()
    for path, name in (("branding/motd", "motd"),
                       ("branding/lightdm-gtk-greeter.conf", "lightdm-gtk-greeter.conf")):
        digest = hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
        assert f"{digest}  {name}" in known, f"run tools/update-etc-known.py after changing {path}"
