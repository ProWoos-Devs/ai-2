"""Screen-reader support: sentence grouping, the Speaker queue, spoken update
notifications, and the accessibility command's user-level wiring."""
import os
import time

from ai2 import a11y, chatterm, updates


# --- sentence grouping (the terminal chat default) ---------------------------

def test_sentences_group_and_keep_decimals():
    pieces = ["Hel", "lo. Wor", "ld! Pi is 3.", "14 exactly"]
    assert list(chatterm.sentences(iter(pieces))) == [
        "Hello.", "World!", "Pi is 3.14 exactly"]


def test_sentences_split_on_newline_and_flush_tail():
    assert list(chatterm.sentences(iter(["line one\nline two"]))) == [
        "line one", "line two"]


def test_sentences_flush_runon_at_word_break():
    runon = "word " * 120   # 600 chars, no terminator
    out = list(chatterm.sentences(iter([runon])))
    assert len(out) >= 2 and "".join(p + " " for p in out).split() == runon.split()


def test_repl_default_says_whole_sentences_and_speaks_them():
    def stream(url, messages):
        yield "One. "
        yield "Two."

    said, spoken = [], []
    it = iter(["hi"])

    def ask(prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    rc = chatterm.repl("http://x/", stream=stream, ask=ask,
                       say=lambda t="", **kw: said.append((t, kw)),
                       speak=spoken.append)
    assert rc == 0
    texts = [t for t, kw in said]
    assert "One." in texts and "Two." in texts
    # no token-by-token writes in sentence mode
    assert not any(kw.get("end") == "" for t, kw in said if t in ("One. ", "Two."))
    assert spoken[-2:] == ["One.", "Two."]


def test_repl_streaming_flag_restores_tokens():
    def stream(url, messages):
        yield "a"
        yield "b"

    said = []
    it = iter(["hi"])

    def ask(prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    chatterm.repl("http://x/", stream=stream, ask=ask,
                  say=lambda t="", **kw: said.append((t, kw)), streaming=True)
    assert ("a", {"end": "", "flush": True}) in said


# --- Speaker -----------------------------------------------------------------

def test_speaker_orders_and_survives_runner_errors():
    got = []

    def runner(text):
        if text == "boom":
            raise RuntimeError("no speech today")
        got.append(text)

    sp = a11y.Speaker(runner=runner)
    for t in ("one", "boom", "two"):
        sp.speak(t)
    sp.close(wait_s=5)
    assert got == ["one", "two"]


def test_speech_cmd_prefers_spd_when_usable(monkeypatch):
    monkeypatch.setenv("LC_ALL", "de_DE.UTF-8")
    monkeypatch.setattr(a11y, "_spd_usable", lambda: True)
    assert a11y._speech_cmd("hi", wait=True) == ["spd-say", "-w", "-l", "de", "hi"]
    monkeypatch.setenv("LC_ALL", "C")
    assert a11y._speech_cmd("hi") == ["spd-say", "hi"]
    assert a11y._safe_text("-rf everything") == " -rf everything"


def test_speech_cmd_falls_back_to_espeak_without_audio_server(monkeypatch):
    """spd-say exits 0 even when its audio goes nowhere (found in the 0.7.0
    QEMU speech test: no PipeWire/Pulse on a lean install), so without a
    server or the setup-written config, speak directly via espeak-ng."""
    monkeypatch.setenv("LC_ALL", "es_ES.UTF-8")
    monkeypatch.setattr(a11y, "_spd_usable", lambda: False)
    monkeypatch.setattr(a11y.shutil, "which", lambda name: "/usr/bin/espeak-ng"
                        if name == "espeak-ng" else None)
    assert a11y._speech_cmd("hola") == ["espeak-ng", "-v", "es", "hola"]
    monkeypatch.setattr(a11y.shutil, "which", lambda name: None)
    assert a11y._speech_cmd("hola") is None


def test_spd_usable_needs_server_or_config(monkeypatch, tmp_path):
    monkeypatch.setattr(a11y, "spd_available", lambda: True)
    monkeypatch.setattr(a11y, "audio_server_running", lambda: False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert a11y._spd_usable() is False
    conf = tmp_path / "speech-dispatcher" / "speechd.conf"
    conf.parent.mkdir(parents=True)
    conf.write_text('AudioOutputMethod "alsa"\n')
    assert a11y._spd_usable() is True


def test_setup_writes_speechd_alsa_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(a11y, "_pkg_missing", lambda: [])
    monkeypatch.setattr(a11y, "_xfconf", lambda *a, **kw: True)
    monkeypatch.setattr(a11y, "audio_server_running", lambda: False)
    monkeypatch.setattr(a11y.subprocess, "run",
                        lambda *a, **kw: type("P", (), {"returncode": 0})())
    assert a11y.setup() == 0
    conf = tmp_path / "speech-dispatcher" / "speechd.conf"
    assert conf.exists() and 'AudioOutputMethod "alsa"' in conf.read_text()


# --- spoken update notification ----------------------------------------------

def test_notify_speaks_when_reader_active(monkeypatch):
    spoken = []
    monkeypatch.setattr(a11y, "reader_active", lambda: True)
    monkeypatch.setattr(a11y, "speak_once", lambda text: spoken.append(text) or True)
    monkeypatch.setattr(updates.shutil, "which", lambda name: None)   # no notify-send
    assert updates.notify(3) is False   # visual not sent
    assert spoken and "3 updates available" in spoken[0]


def test_notify_silent_without_reader(monkeypatch):
    spoken = []
    monkeypatch.setattr(a11y, "reader_active", lambda: False)
    monkeypatch.setattr(a11y, "speak_once", lambda text: spoken.append(text) or True)
    monkeypatch.setattr(updates.shutil, "which", lambda name: None)
    updates.notify(2)
    assert spoken == []


# --- ai-2 accessibility ------------------------------------------------------

def test_setup_writes_autostart_and_reports(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(a11y, "_pkg_missing", lambda: [])
    monkeypatch.setattr(a11y, "_xfconf", lambda *a, **kw: True)
    assert a11y.setup() == 0
    path = tmp_path / "autostart" / "ai2-orca.desktop"
    assert path.exists() and "Exec=orca" in path.read_text()
    out = capsys.readouterr().out
    assert "Super+Alt+S" in out and "ai-2 chat --terminal --speak" in out


def test_setup_stops_when_package_install_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(a11y, "_pkg_missing", lambda: ["orca"])

    class Proc:
        returncode = 1

    assert a11y.setup(run=lambda cmd: Proc()) == 1
    assert not (tmp_path / "autostart" / "ai2-orca.desktop").exists()


def test_status_mentions_setup_when_incomplete(monkeypatch, capsys):
    monkeypatch.setattr(a11y, "_pkg_missing", lambda: ["orca"])
    monkeypatch.setattr(a11y, "reader_active", lambda: False)
    monkeypatch.setattr(a11y, "spd_available", lambda: False)
    assert a11y.status() == 0
    assert "ai-2 accessibility setup" in capsys.readouterr().out
