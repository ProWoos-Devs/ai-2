"""Screen-reader support: detection, spoken output, and the opt-in setup.

AI-2's accessible path on an installed system (accessibility plan, section 12,
000/20260826-accessibility-plan.md in the workspace): the terminal chat and
wizard print whole lines a screen reader can follow, `ai-2 chat --terminal
--speak` speaks its answers through speech-dispatcher, and `ai-2 accessibility
setup` installs and wires the reader stack for the current user. Nothing here
runs unless asked; sighted installs are untouched.
"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading

from .i18n import _lang

READER_PROCESSES = ("orca", "espeakup")
SPEECH_PACKAGES = ("orca", "speech-dispatcher", "espeak-ng")


def reader_active() -> bool:
    """A screen reader is running on THIS machine (Orca on the desktop or
    espeakup on the console). Over SSH the reader runs on the user's own
    computer and cannot be detected, which is why reader-friendly output is
    the default everywhere, not gated on this."""
    for name in READER_PROCESSES:
        try:
            if subprocess.run(["pgrep", "-x", name], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=5).returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            return False
    return False


def spd_available() -> bool:
    return shutil.which("spd-say") is not None


def speak_once(text: str, timeout_s: int = 10) -> bool:
    """Fire-and-forget one utterance (used by the update notification).
    Never raises; returns whether spd-say was invoked."""
    if not spd_available():
        return False
    try:
        subprocess.run(_spd_cmd() + [_safe_text(text)], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=timeout_s)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def _spd_cmd(wait: bool = False) -> list[str]:
    cmd = ["spd-say"]
    if wait:
        cmd.append("-w")
    lang = _lang()
    # a real language code only; LANG=C would make spd-say choke on -l c
    if len(lang) == 2 and lang.isalpha() and lang != "c":
        cmd += ["-l", lang]
    return cmd


def _safe_text(text: str) -> str:
    # spd-say takes the text as an argument; a leading dash would parse as an
    # option, a space neutralizes it without changing the speech.
    return " " + text if text.startswith("-") else text


class Speaker:
    """Sequential speech for the terminal chat: a worker thread drains a queue
    and runs `spd-say -w` per sentence, so slow speech never blocks the token
    stream and sentences keep their order. `runner` is injectable for tests."""

    def __init__(self, runner=None):
        self._runner = runner if runner is not None else self._run
        self._q: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _run(self, text: str) -> None:
        subprocess.run(_spd_cmd(wait=True) + [_safe_text(text)],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=300)

    def _loop(self) -> None:
        while True:
            text = self._q.get()
            if text is None:
                return
            try:
                self._runner(text)
            except Exception:
                pass   # a lost sentence must never kill the chat

    def speak(self, text: str) -> None:
        if text.strip():
            self._q.put(text)

    def close(self, wait_s: float = 0) -> None:
        self._q.put(None)
        if wait_s:
            self._thread.join(timeout=wait_s)


# --- ai-2 accessibility -------------------------------------------------------

ORCA_AUTOSTART = """[Desktop Entry]
Type=Application
Name=Orca screen reader
Comment=Started at login (set up by ai-2 accessibility setup)
Exec=orca
Icon=orca
NoDisplay=true
"""


def _autostart_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(base, "autostart", "ai2-orca.desktop")


def _xfconf(channel: str, prop: str, value: str, kind: str = "string") -> bool:
    if not shutil.which("xfconf-query"):
        return False
    try:
        return subprocess.run(["xfconf-query", "-c", channel, "-p", prop, "-n",
                               "-t", kind, "-s", value], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _pkg_missing() -> list[str]:
    missing = []
    for pkg in SPEECH_PACKAGES:
        try:
            if subprocess.run(["pacman", "-Q", pkg], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=10).returncode != 0:
                missing.append(pkg)
        except (OSError, subprocess.TimeoutExpired):
            missing.append(pkg)
    return missing


def status(say=print) -> int:
    missing = _pkg_missing()
    say("Screen-reader stack: " + ("installed" if not missing
        else "missing " + " ".join(missing)))
    say("Orca autostart:      " + ("set for this user" if os.path.exists(_autostart_path())
        else "not set"))
    say("Reader running now:  " + ("yes" if reader_active() else "no"))
    say("Spoken chat:         " + ("available (ai-2 chat --terminal --speak)"
        if spd_available() else "needs the stack (ai-2 accessibility setup)"))
    if missing or not os.path.exists(_autostart_path()):
        say("")
        say("Set everything up for this user with:  ai-2 accessibility setup")
    return 0


def setup(say=print, run=subprocess.run) -> int:
    """Install the reader stack and wire it for the current user. Interactive
    (sudo prompts for the package install); everything else is user-level."""
    missing = _pkg_missing()
    if missing:
        say("Installing: " + " ".join(missing) + "  (sudo asks for your password)")
        try:
            proc = run(["sudo", "pacman", "-S", "--needed"] + missing)
        except OSError as exc:
            say(f"Could not run pacman ({exc}).")
            return 1
        if proc.returncode != 0:
            say("Package install failed; nothing else was changed.")
            return 1
    else:
        say("Screen-reader packages already installed.")

    ok_at = _xfconf("xfce4-session", "/general/StartAssistiveTechnologies", "true", "bool")
    say("Assistive technologies flag: " + ("set" if ok_at
        else "could not set (not in an XFCE session? set it in Session settings)"))

    path = _autostart_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(ORCA_AUTOSTART)
    say(f"Orca autostart: {path}")

    ok_key = _xfconf("xfce4-keyboard-shortcuts", "/commands/custom/<Super><Alt>s",
                     "orca --replace")
    if ok_key:
        say("Shortcut: Super+Alt+S starts or restarts Orca.")

    say("")
    say("Done. Orca starts at your next login; start it now with:  orca &")
    say("Spoken chat:  ai-2 chat --terminal --speak")
    return 0
