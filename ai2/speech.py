"""Speech to text (`ai-2 transcribe`): a recording, a voice note or a video's
audio into a text file, with whisper.cpp, on the CPU.

The shape decided in the 2026-09-14 review, item 5. File transcription only:
no live dictation, no voice assistant, no Speaches or Piper. The engine is the
`ai2-whisper-cpp-<variant>` package (one per CPU class, like the llama.cpp
runtime), built without ffmpeg so a world ffmpeg bump can never break a signed
package; anything that is not already a 16 kHz mono 16-bit WAV is converted
with the ffmpeg command first, which the speech workflow installs.

The models are whisper.cpp's own ggml files in `ai2/data/speech-models.yml`,
a catalog of their own on purpose: everything that reads models.yml treats an
entry as a chat model. The multilingual tiny/base/small q8_0 files; q8_0
because on the pure-SSE2 baseline build q4_0's SIMD path needs SSSE3.

No speed is stated anywhere. The one measured old-CPU report the review found
counts full 30-second windows, not seconds of audio, and was made on a CPU
stronger than both reference laptops; whisper-bench per window on those
machines is the honest gate and is not implemented yet.
"""

from __future__ import annotations

import importlib.resources
import os
import shutil
import struct
import subprocess
import tempfile

import yaml

RUNTIME_ENV = "AI2_WHISPER_DIR"
RUNTIME_PACKAGES = {
    "baseline": "ai2-whisper-cpp-baseline",
    "noavx": "ai2-whisper-cpp-noavx",
    "avx2": "ai2-whisper-cpp-avx2",
}
WAIT_NOTE = ("Transcribing. This takes a while on an old computer, the engine works in 30-second "
             "windows and each one costs the same; leave it running.")


def load_catalog() -> list[dict]:
    data = yaml.safe_load(importlib.resources.files("ai2").joinpath("data/speech-models.yml").read_text())
    return list(data["models"])


def default_model_id(catalog: list[dict] | None = None) -> str:
    catalog = catalog or load_catalog()
    return next(m["id"] for m in catalog if m.get("default"))


def speech_model(model_id: str | None, catalog: list[dict] | None = None) -> dict | None:
    catalog = catalog or load_catalog()
    model_id = model_id or default_model_id(catalog)
    return next((m for m in catalog if m["id"] == model_id), None)


def _runtime_candidates(variant: str) -> list[str]:
    return [
        os.environ.get(RUNTIME_ENV, ""),
        f"/usr/lib/ai2/runtimes/whisper.cpp-{variant}",
        "/opt/ai2/whisper",
        os.path.expanduser("~/whisper"),
    ]


def find_runtime(variant: str) -> str | None:
    for d in _runtime_candidates(variant):
        if d and os.path.isfile(os.path.join(d, "whisper-cli")):
            return d
    return None


def runtime_package(variant: str) -> str | None:
    return RUNTIME_PACKAGES.get(variant)


def is_wav16k_mono(path: str) -> bool:
    """A RIFF/WAVE file whose fmt chunk says PCM, 1 channel, 16000 Hz, 16 bit,
    what whisper.cpp reads without conversion. Anything else: False."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
            if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
                return False
            while True:
                chunk = fh.read(8)
                if len(chunk) < 8:
                    return False
                cid, size = chunk[:4], struct.unpack("<I", chunk[4:])[0]
                if cid == b"fmt ":
                    fmt = fh.read(16)
                    if len(fmt) < 16:
                        return False
                    tag, channels, rate, _, _, bits = struct.unpack("<HHIIHH", fmt)
                    return tag == 1 and channels == 1 and rate == 16000 and bits == 16
                fh.seek(size + (size & 1), os.SEEK_CUR)
    except OSError:
        return False


def ffmpeg_cmd(src: str, dst: str) -> list[str]:
    return ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", src,
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", dst]


def whisper_cmd(runtime_dir: str, model_path: str, wav: str, lang: str, threads: int,
                out_base: str) -> list[str]:
    """whisper-cli flags at v1.9.4 (examples/cli/cli.cpp): -m model, -f file,
    -l language ('auto' detects), -t threads, -np no extra prints, -nt no
    timestamps, -otxt -of BASE writes BASE.txt."""
    return [os.path.join(runtime_dir, "whisper-cli"), "-m", model_path, "-f", wav, "-l", lang,
            "-t", str(threads), "-np", "-nt", "-otxt", "-of", out_base]


def transcribe(runtime_dir: str, model_path: str, audio: str, lang: str, threads: int,
               out_txt: str, run=subprocess.run) -> str:
    """Convert if needed, run whisper-cli, return the text (also in out_txt).
    Raises RuntimeError with the reason (ffmpeg missing, engine failed)."""
    out_base = out_txt[:-4] if out_txt.endswith(".txt") else out_txt
    out_txt = out_base + ".txt"
    tmpdir = None
    try:
        wav = audio
        if not is_wav16k_mono(audio):
            if not shutil.which("ffmpeg"):
                raise RuntimeError("ffmpeg is needed to read this file (package ffmpeg; ai-2 workflow "
                                   "install speech names it), or give a 16 kHz mono WAV")
            tmpdir = tempfile.mkdtemp(prefix="ai2-transcribe-")
            wav = os.path.join(tmpdir, "audio.wav")
            proc = run(ffmpeg_cmd(audio, wav), capture_output=True, text=True)
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg could not convert {audio}: {proc.stderr.strip()[-300:]}")
        env = dict(os.environ, LD_LIBRARY_PATH=runtime_dir)
        proc = run(whisper_cmd(runtime_dir, model_path, wav, lang, threads, out_base),
                   capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            raise RuntimeError(f"whisper-cli failed (exit {proc.returncode}): {proc.stderr.strip()[-300:]}")
        try:
            with open(out_txt, encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError as exc:
            raise RuntimeError(f"whisper-cli wrote no text file at {out_txt}: {exc}")
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
