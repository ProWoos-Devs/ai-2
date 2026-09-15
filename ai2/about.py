"""About AI-2: the version, the Linux it runs on, this machine's AI Score,
the project page and the license, in one short view. `ai-2 about` prints it;
the menu entry Applications > AI-2 > About AI-2 runs `ai-2 about --window`,
which opens a small terminal window titled About AI-2 that stays until Enter.

A terminal window on purpose: the first-login wizard opens the same way
(branding/ai2-first-boot, same terminal fallbacks), and a dialog would need
a program the image does not carry."""

from __future__ import annotations

import shutil
import subprocess

from . import __version__
from .detect import detect_init_system
from .i18n import tr
from .state import load_score

PROJECT_PAGE = "https://prowoos.com/software-development/linux/ai-2/"
LICENSE = "MIT"
OS_RELEASE = "/etc/os-release"


def read_os_release(path: str = OS_RELEASE) -> dict[str, str]:
    values = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                key, sep, value = line.strip().partition("=")
                if sep and key and not key.startswith("#"):
                    values[key] = value.strip().strip('"')
    except OSError:
        pass
    return values


def base_system(os_release: dict[str, str], init_system: str) -> str:
    """"Artix Linux (runit)" on AI-2's own image, whose os-release names AI-2
    and lists artix in ID_LIKE, and on an Artix install that added the ai-2
    package. Anything else shows its own name, so the line never claims Artix
    where it is not."""
    ids = [os_release.get("ID", "")] + os_release.get("ID_LIKE", "").split()
    if "artix" in ids:
        name = "Artix Linux"
    else:
        name = os_release.get("PRETTY_NAME") or os_release.get("NAME") or tr("unknown")
    if init_system and init_system != "unknown":
        return f"{name} ({init_system})"
    return name


def score_text(score: dict | None) -> str:
    if not score or score.get("ai_score") is None:
        return tr("not measured yet (run: ai-2 benchmark)")
    return f"{score['ai_score']}/100"


_LOAD = object()


def about_lines(os_release: dict[str, str] | None = None, init_system: str | None = None,
                score=_LOAD) -> list[tuple[str, str]]:
    """The five lines. Each argument is read from this computer when not
    given; score=None means no AI Score has been measured."""
    if os_release is None:
        os_release = read_os_release()
    if init_system is None:
        init_system = detect_init_system()
    if score is _LOAD:
        score = load_score()
    return [
        (tr("Version"), __version__),
        (tr("Based on"), base_system(os_release, init_system)),
        (tr("AI Score"), score_text(score)),
        (tr("Website"), PROJECT_PAGE),
        (tr("License"), LICENSE),
    ]


def render(lines: list[tuple[str, str]]) -> str:
    width = max(len(label) for label, _ in lines)
    return "\n".join(f"{label.ljust(width)}  {value}" for label, value in lines)


def wait_for_enter() -> None:
    try:
        input(tr("Press Enter to close this window."))
    except (EOFError, KeyboardInterrupt):
        pass


def window_command(which=shutil.which) -> list[str] | None:
    """The terminal command for the menu entry: the same terminals, in the
    same order, as the first-login wizard. 70x13 fits the logo, the five
    lines and the prompt in English, Spanish and German."""
    title = tr("About AI-2")
    run = ["ai-2", "about", "--wait"]
    if which("xfce4-terminal"):
        return ["xfce4-terminal", f"--title={title}", "--geometry=70x13", "--hide-menubar", "-x", *run]
    if which("x-terminal-emulator"):
        return ["x-terminal-emulator", "-e", *run]
    if which("xterm"):
        return ["xterm", "-T", title, "-geometry", "70x13", "-e", *run]
    return None


def open_window() -> bool:
    cmd = window_command()
    if cmd is None:
        return False
    subprocess.Popen(cmd, start_new_session=True)
    return True
