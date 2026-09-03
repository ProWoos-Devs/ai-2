"""Adding software, and updating the system.

AI-2 ships lean on purpose, so "how do I install X" and "how do I update" are
the first two questions a new user has. There are two answers and they are the
same underneath. The graphical one is pamac (Artix's package of Manjaro's
Add/Remove Software), which the desktop menu carries. This module is the
terminal one, and the one a screen reader can follow: `ai-2 install <thing>`
and `ai-2 update`, thin wrappers that print the exact pacman command before
running it, so nothing here is a black box the user cannot reproduce by hand.

The catalog maps a plain-language name ("printing", "office") to what Artix
actually calls those packages, including the init-specific service package a
daemon needs: installing cups is not enough on runit, cupsd has to be enabled
too, which is exactly the kind of step this project exists to take off the
user. Anything not in the catalog is passed straight through, so
`ai-2 install htop` behaves like `pacman -S htop`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

# Every package name here was checked against the Artix system/world/galaxy
# repositories (2026-08-30). A daemon needs two more things named per init
# system, because Artix splits them out and ships no systemd units of its own:
# "service_packages" is the package carrying the service directory, "services"
# the name to enable. Only what has been verified is listed, so an init system
# that is not named simply gets no automatic enabling.
CATALOG = [
    {"id": "office",
     "what": "LibreOffice: documents, spreadsheets, presentations",
     "packages": ["libreoffice-still"]},
    {"id": "pdf",
     "what": "Atril: read PDF files",
     "packages": ["atril"]},
    {"id": "media",
     "what": "VLC: play video and music",
     "packages": ["vlc"]},
    {"id": "photos",
     "what": "Ristretto: look at photos",
     "packages": ["ristretto"]},
    {"id": "image-editor",
     "what": "GIMP: edit images (heavy on a small machine)",
     "packages": ["gimp"]},
    {"id": "browser",
     "what": "Firefox (AI-2 ships the lighter Epiphany)",
     "packages": ["firefox"]},
    {"id": "archives",
     "what": "Open and make zip, rar and 7z files",
     "packages": ["xarchiver", "unzip", "unrar", "7zip"]},
    {"id": "printing",
     "what": "Printing: the CUPS service and a printer setup tool",
     "packages": ["cups", "system-config-printer"],
     "services": {"runit": "cupsd"},          # the directory cups-runit ships
     "service_packages": {"runit": ["cups-runit"]}},
    {"id": "scanner",
     "what": "Simple Scan: use a scanner",
     "packages": ["simple-scan"]},
    {"id": "usb-disks",
     "what": "Read phones, USB sticks and Windows disks in the file manager",
     "packages": ["gvfs", "gvfs-mtp", "ntfs-3g", "exfatprogs"]},
]

GUI_PACKAGE = "pamac"
GUI_MANAGER = "pamac-manager"


def entry(name: str) -> dict | None:
    for item in CATALOG:
        if item["id"] == name:
            return item
    return None


def gui_available() -> bool:
    """True when the graphical Add/Remove Software is installed."""
    return shutil.which(GUI_MANAGER) is not None


def open_gui(updates: bool = False) -> bool:
    """Open the graphical package manager, on its updates page when asked.
    Returns False when it is not installed. Only --updates is passed, the one
    option read straight out of the shipped binary's option table."""
    if not gui_available():
        return False
    cmd = [GUI_MANAGER] + (["--updates"] if updates else [])
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return True
    except OSError:
        return False


def resolve(names: list[str], init_system: str = "") -> tuple[list[str], list[str], list[str]]:
    """Turn user-typed names into (packages, services to enable, catalog ids
    that matched). Names with no catalog entry stay as they are: they are
    package names and pacman will say so if they are not."""
    packages: list[str] = []
    services: list[str] = []
    matched: list[str] = []
    for name in names:
        item = entry(name)
        if item is None:
            packages.append(name)
            continue
        matched.append(name)
        packages.extend(item["packages"])
        packages.extend((item.get("service_packages") or {}).get(init_system, []))
        service = (item.get("services") or {}).get(init_system)
        if service:
            services.append(service)
    seen: set[str] = set()
    packages = [p for p in packages if not (p in seen or seen.add(p))]
    return packages, services, matched


def _sudo() -> list[str]:
    return [] if os.geteuid() == 0 else ["sudo"]


def _flush() -> None:
    """pacman writes straight to the terminal, so our own buffered output has
    to be out of the way first, or a piped log shows them in the wrong order."""
    try:
        sys.stdout.flush()
    except (OSError, ValueError):
        pass


def render_catalog() -> str:
    """The shortcut names, for `ai-2 install` with nothing to install."""
    width = max(len(item["id"]) for item in CATALOG)
    lines = ["Things AI-2 leaves out, and the short name to install them:", ""]
    for item in CATALOG:
        lines.append(f"  {item['id']:<{width}}  {item['what']}")
    lines += [
        "",
        "  ai-2 install office pdf     install by short name",
        "  ai-2 install htop           any other package name works too",
        "",
        "The same thing with a window and a search box: Applications > "
        "System > Add/Remove Software.",
    ]
    return "\n".join(lines)


def update(say=print, run=subprocess.run) -> int:
    """Update AI-2, the AI engine, the model catalog and the whole system.
    One command, because on a rolling release they are one thing."""
    cmd = _sudo() + ["pacman", "-Syu"]
    say("Updating AI-2 and the rest of the system. This is the only update there is.")
    say("Running:  " + " ".join(cmd))
    if _sudo():
        say("(sudo asks for your password)")
    _flush()
    try:
        rc = run(cmd).returncode
    except OSError as exc:
        say(f"Could not run pacman: {exc}")
        return 1
    if rc == 0:
        say("\nThe system is up to date.")
    else:
        say(f"\npacman stopped with an error (code {rc}). Nothing was left half done: "
            "pacman applies an update or it does not. If it mentions keys or signatures, "
            "run  sudo pacman -Sy artix-keyring ai2-keyring  and try again.")
    return rc


def install(names: list[str], init_system: str = "", say=print,
            run=subprocess.run) -> int:
    """Install software by short name or by package name, and enable the
    service it needs (printing is useless with cupsd disabled)."""
    if not names:
        say(render_catalog())
        return 0
    packages, services, matched = resolve(names, init_system)
    unknown = [n for n in names if n not in matched]
    for name in matched:
        item = entry(name)
        say(f"{name}: {item['what']}")
    if unknown:
        say("Passing straight to pacman: " + " ".join(unknown))
    cmd = _sudo() + ["pacman", "-S", "--needed", *packages]
    say("Running:  " + " ".join(cmd))
    if _sudo():
        say("(sudo asks for your password)")
    _flush()
    try:
        rc = run(cmd).returncode
    except OSError as exc:
        say(f"Could not run pacman: {exc}")
        return 1
    if rc != 0:
        say(f"\npacman stopped with an error (code {rc}); nothing was installed.")
        return rc
    for service in services:
        _enable(service, init_system, say, run)
    for name in matched:
        item = entry(name)
        if item.get("services") and not (item["services"]).get(init_system):
            say(f"{name} runs a service, and AI-2 does not know its name on "
                f"{init_system or 'this init system'}. Enable it yourself, or it "
                "will not work.")
    say("\nDone. New programs appear in the Applications menu.")
    return 0


def _enable(service: str, init_system: str, say, run) -> None:
    """Enable a freshly installed service. A daemon package on Artix installs
    the service directory but never starts it."""
    from .backends import get_service_backend
    try:
        backend = get_service_backend(init_system)
    except ValueError:
        say(f"Enable the {service} service yourself; AI-2 does not know this init system.")
        return
    if backend.is_enabled(service):
        return
    if service not in backend.available_services():
        say(f"The {service} service is not installed, so nothing to enable.")
        return
    cmd = _sudo() + backend.enable_cmd(service)
    say("Enabling the service:  " + " ".join(cmd))
    _flush()
    try:
        if run(cmd).returncode != 0:
            say(f"Could not enable {service}. Run the command above by hand.")
    except OSError as exc:
        say(f"Could not enable {service}: {exc}")
