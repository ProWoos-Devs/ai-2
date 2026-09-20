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
# The community catalog of Knowledge Packs. A literal, not an import of
# ai2.pack, because About must open even when something else is broken; a
# test holds the two equal.
CATALOG_URL = "https://github.com/ProWoos-Devs/ai2-knowledge"
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


def packs_text(titles: list[str] | None) -> str:
    """The Knowledge Packs line: how many, which, and where to ask them. They
    are a headline of AI-2, so About names them beside the version and the
    score rather than leaving them to be found."""
    if titles is None:
        try:
            from . import pack
            titles = [str(m.get("title") or name) for name, m in pack.installed_packs()]
        except Exception:                                   # noqa: BLE001 - About must always open
            titles = []
    if not titles:
        return tr("none yet (run: ai-2 knowledge available)")
    return tr("{n} installed ({titles}); ask them: Search Knowledge").format(n=len(titles), titles=", ".join(titles))


def about_lines(os_release: dict[str, str] | None = None, init_system: str | None = None,
                score=_LOAD, packs: list[str] | None = None) -> list[tuple[str, str]]:
    """The seven lines. Each argument is read from this computer when not
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
        (tr("Knowledge Packs"), packs_text(packs)),
        (tr("Pack catalog"), CATALOG_URL),
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


def terminal_window(title: str, geometry: str, run: list[str], which=None) -> list[str] | None:
    """A command that opens `run` in a titled terminal window of a given size:
    the same terminals, in the same order, as the first-login wizard. A plain
    `Terminal=true` menu entry gets whatever size the terminal defaults to,
    which is 80x24 and too small for a window that shows a list."""
    which = which or shutil.which          # looked up now, so a test (or a changed PATH) is seen
    if which("xfce4-terminal"):
        # --disable-server: without it the second xfce4-terminal on a desktop
        # is only a client, and the window it asks for is opened by the
        # instance that is already running, whose stdin the child inherits.
        # The setup window IS such an instance, so a window it opened got the
        # setup's own stdin, read EOF at once and closed before anything could
        # be read (QEMU install, 2026-09-21). Its own process, its own pty.
        return ["xfce4-terminal", f"--title={title}", f"--geometry={geometry}", "--hide-menubar",
                "--disable-server", "-x", *run]
    if which("x-terminal-emulator"):
        return ["x-terminal-emulator", "-e", *run]
    if which("xterm"):
        return ["xterm", "-T", title, "-geometry", geometry, "-e", *run]
    return None


def window_command(which=None) -> list[str] | None:
    """The terminal command for the About menu entry. 96x16 fits the logo, the
    seven lines (the Knowledge Packs one wraps with three titles) and the
    prompt in English, Spanish and German."""
    return terminal_window(tr("About AI-2"), "96x16", ["ai-2", "about", "--wait"], which)


def open_window(cmd: list[str] | None = _LOAD) -> bool:
    if cmd is _LOAD:
        cmd = window_command()
    if cmd is None:
        return False
    subprocess.Popen(cmd, start_new_session=True)
    return True
