"""Packaging invariants that no build can catch by itself."""
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
