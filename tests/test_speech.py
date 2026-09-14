"""`ai-2 transcribe` and ai2/speech.py, with fake whisper-cli and ffmpeg."""
import datetime
import os
import re
import stat
import wave

import pytest

from ai2 import speech


def _wav16k(path, seconds=0.1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))


def _fake_bin(dirpath, name, script):
    p = dirpath / name
    p.write_text(script)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


def test_speech_catalog_shape_and_default():
    cat = speech.load_catalog()
    assert [m["id"] for m in cat] == ["tiny", "base", "small"]
    assert speech.default_model_id(cat) == "base"
    for m in cat:
        assert m["repo"] == "ggerganov/whisper.cpp" and m["file"].endswith("-q8_0.bin"), m["id"]
        assert ".en" not in m["file"], "multilingual files only"
        assert re.fullmatch(r"[0-9a-f]{64}", m["sha256"]) and m["file_mb"] > 0 and m["memory_mb"] > m["file_mb"]
        assert isinstance(m["verified"], datetime.date) and m["license"] == "mit"
    assert speech.speech_model(None)["id"] == "base"
    assert speech.speech_model("small")["id"] == "small"
    assert speech.speech_model("large") is None
    assert speech.runtime_package("baseline") == "ai2-whisper-cpp-baseline"


def test_wav_detection(tmp_path):
    good = tmp_path / "ok.wav"
    _wav16k(good)
    assert speech.is_wav16k_mono(str(good))
    with wave.open(str(tmp_path / "stereo.wav"), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\x00" * 64)
    assert not speech.is_wav16k_mono(str(tmp_path / "stereo.wav"))
    with wave.open(str(tmp_path / "44k.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100); w.writeframes(b"\x00" * 64)
    assert not speech.is_wav16k_mono(str(tmp_path / "44k.wav"))
    (tmp_path / "x.mp3").write_bytes(b"ID3\x03\x00")
    assert not speech.is_wav16k_mono(str(tmp_path / "x.mp3"))
    assert not speech.is_wav16k_mono(str(tmp_path / "missing.wav"))


def test_command_builders():
    assert speech.ffmpeg_cmd("in.ogg", "/tmp/a.wav") == ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", "in.ogg",
                                                        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", "/tmp/a.wav"]
    cmd = speech.whisper_cmd("/rt", "/m/base.bin", "/tmp/a.wav", "es", 2, "/out/note")
    assert cmd[0] == "/rt/whisper-cli"
    assert cmd[1:] == ["-m", "/m/base.bin", "-f", "/tmp/a.wav", "-l", "es", "-t", "2", "-np", "-nt", "-otxt", "-of", "/out/note"]


def test_transcribe_direct_wav_and_through_ffmpeg(tmp_path, monkeypatch):
    rt = tmp_path / "rt"; rt.mkdir()
    # whisper-cli stand-in: writes BASE.txt from -of, notes the input in it
    _fake_bin(rt, "whisper-cli", "#!/bin/sh\nwhile [ $# -gt 0 ]; do case $1 in -of) of=$2; shift;; -f) f=$2; shift;; esac; shift; done\n"
                                 "echo \"hola desde $(basename $f)\" > \"$of.txt\"\n")
    wav = tmp_path / "a.wav"; _wav16k(wav)
    out = tmp_path / "a.txt"
    monkeypatch.setattr(speech.shutil, "which", lambda n: None)     # no ffmpeg: a real WAV needs none
    assert speech.transcribe(str(rt), "/m/base.bin", str(wav), "auto", 2, str(out)) == "hola desde a.wav"
    assert out.read_text().strip() == "hola desde a.wav"
    # a non-WAV file without ffmpeg names the package and stops
    mp3 = tmp_path / "b.mp3"; mp3.write_bytes(b"ID3")
    with pytest.raises(RuntimeError, match="ffmpeg"):
        speech.transcribe(str(rt), "/m/base.bin", str(mp3), "auto", 2, str(tmp_path / "b.txt"))
    # with a (fake) ffmpeg the file is converted and the WAV is what whisper reads
    bindir = tmp_path / "bin"; bindir.mkdir()
    _fake_bin(bindir, "ffmpeg", "#!/bin/sh\nfor a in \"$@\"; do dst=$a; done\nprintf 'RIFF' > \"$dst\"\n")
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setattr(speech.shutil, "which", lambda n: str(bindir / n) if n == "ffmpeg" else None)
    text = speech.transcribe(str(rt), "/m/base.bin", str(mp3), "es", 2, str(tmp_path / "b"))
    assert text == "hola desde audio.wav"
    assert (tmp_path / "b.txt").exists()


def test_cmd_transcribe_end_to_end(tmp_path, monkeypatch, capsys):
    from ai2 import cli
    from ai2.detect import Hardware
    rt = tmp_path / "rt"; rt.mkdir()
    _fake_bin(rt, "whisper-cli", "#!/bin/sh\nwhile [ $# -gt 0 ]; do case $1 in -of) of=$2; shift;; esac; shift; done\n"
                                 "echo 'texto transcrito' > \"$of.txt\"\n")
    monkeypatch.setenv(speech.RUNTIME_ENV, str(rt))
    models = tmp_path / "models"; models.mkdir()
    monkeypatch.setenv("AI2_MODEL_DIR", str(models))
    monkeypatch.setattr(cli, "detect", lambda: Hardware(cpu_model="t", logical_cores=2, flags={"avx2"}, ram_mib=7800, ram_nominal_gib=8))
    wav = tmp_path / "note.wav"; _wav16k(wav)
    # model missing: the download path is taken (stubbed), then whisper runs
    pulled = []
    def fake_pull(model, force=False):
        pulled.append(model["id"]); (models / model["file"]).write_bytes(b"m"); return 0
    monkeypatch.setattr(cli, "_pull_model", fake_pull)
    assert cli.main(["transcribe", str(wav)]) == 0
    out = capsys.readouterr().out
    assert pulled == ["base"] and "texto transcrito" in out and f"Written to {tmp_path / 'note.txt'}" in out
    assert "leave it running" in out
    # an unknown model, a missing file, and no runtime: clear errors
    assert cli.main(["transcribe", str(wav), "--model", "huge"]) == 1
    assert cli.main(["transcribe", str(tmp_path / "nope.wav")]) == 1
    monkeypatch.setenv(speech.RUNTIME_ENV, str(tmp_path / "nowhere"))
    assert cli.main(["transcribe", str(wav)]) == 1
    assert "sudo pacman -S ai2-whisper-cpp-avx2" in capsys.readouterr().err
