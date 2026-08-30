"""The guide for the installed system.

START-HERE.txt is written for the live stick: what AI-2 is, and how to install
it. Once the machine is installed and rebooted, that document is the wrong one
to hand somebody, and until now nothing pointed at any document at all. This
module owns the second guide, the one about the computer the user now has:
talking to the AI, adding software, updating, getting help.

Three languages, chosen from the locale the installer set, with English as the
fallback. Plain text on purpose: it opens in the one text editor AI-2 ships, it
reads correctly through a screen reader, and it works over SSH with `ai-2
guide`.
"""

from __future__ import annotations

import os
import shutil
import subprocess

FILES = {
    "en": "AI-2-GUIDE.txt",
    "es": "AI-2-GUIA.txt",
    "de": "AI-2-ANLEITUNG.txt",
}

DOC_DIR = "/usr/share/doc/ai2"


def _source_dir() -> str:
    """The branding/ directory of a source checkout, so the command works from
    the repository as well as from the installed package."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "branding")


def language(lang: str | None = None) -> str:
    """The guide language: what was asked for, else the process locale, else
    English. An unknown locale (fr, pl) gets the English guide, not nothing."""
    if lang:
        return lang if lang in FILES else "en"
    from .i18n import _lang
    return _lang() if _lang() in FILES else "en"


def guide_path(lang: str | None = None) -> str | None:
    """Where the guide for this language actually is, or None when the
    documentation is not installed."""
    wanted = language(lang)
    for name in (FILES[wanted], FILES["en"]):
        for directory in (DOC_DIR, _source_dir()):
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
    return None


def read(lang: str | None = None) -> str | None:
    path = guide_path(lang)
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def open_in_editor(lang: str | None = None) -> bool:
    """Open the guide in the desktop text editor. False when there is no way
    to (no display, no opener), so the caller can print it instead."""
    path = guide_path(lang)
    if path is None:
        return False
    for cmd in (["xdg-open", path], ["mousepad", path]):
        if not shutil.which(cmd[0]):
            continue
        try:
            subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return True
        except OSError:
            continue
    return False


def _desktop_dir(home: str) -> str:
    try:
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True,
                             text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    if out and os.path.isdir(out):
        return out
    return os.path.join(home, "Desktop")


def marker_path(home: str) -> str:
    config = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return os.path.join(config, "ai2", "guide-placed")


def place_on_desktop(home: str | None = None, lang: str | None = None) -> str | None:
    """Put the guide on the desktop at the user's first login, once. The
    marker is written even when the copy fails or the desktop directory does
    not exist, so a user who deletes the icon does not get it back at every
    login. Returns the path written, or None."""
    home = home or os.path.expanduser("~")
    marker = marker_path(home)
    if os.path.exists(marker):
        return None
    source = guide_path(lang)
    written = None
    desktop = _desktop_dir(home)
    if source and os.path.isdir(desktop):
        target = os.path.join(desktop, os.path.basename(source))
        if not os.path.exists(target):
            try:
                shutil.copyfile(source, target)
                written = target
            except OSError:
                written = None
    try:
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w") as fh:
            fh.write(written or "")
    except OSError:
        pass
    return written
