"""Passive update notification (2026-08-24).

One shared check feeds two surfaces: a desktop notification (xfce4-notifyd via
notify-send) and a one-line hint in login shells (/etc/profile.d reads the
state file this module writes). Nothing here installs anything; updating stays
an explicit `sudo pacman -Syu`.

The check runs `checkupdates` (pacman-contrib): it syncs a private copy of the
sync db, so it never touches the real pacman db and needs no root. Offline or
on any failure the old state is kept and nothing is reported.
"""
import json
import os
import shutil
import subprocess
import time

from .serverstate import state_dir

PACMAN_LOCAL_DB = "/var/lib/pacman/local"


def state_file() -> str:
    return os.path.join(state_dir(), "updates.json")


def load_state() -> dict | None:
    try:
        with open(state_file()) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def state_is_fresh(max_age_h: float, now: float | None = None) -> bool:
    """True when the last check is recent enough to skip a new one, and the
    system has not been updated since (a pacman -Syu makes the count stale)."""
    st = load_state()
    if not st:
        return False
    now = now if now is not None else time.time()
    if now - st.get("checked_at", 0) > max_age_h * 3600:
        return False
    try:
        if os.path.getmtime(PACMAN_LOCAL_DB) > st.get("checked_at", 0):
            return False
    except OSError:
        pass
    return True


def check_now(timeout_s: int = 120) -> dict | None:
    """Run checkupdates and persist the result. Returns the new state, or None
    when the check could not run (offline, missing tool); old state is kept."""
    if not shutil.which("checkupdates"):
        return None
    try:
        proc = subprocess.run(["checkupdates"], capture_output=True, text=True,
                              timeout=timeout_s)
    except (OSError, subprocess.TimeoutExpired):
        return None
    # checkupdates exits 0 with a list, 2 with none; 1 is a real error
    # (offline, db sync failure) and must not overwrite a good state.
    if proc.returncode not in (0, 2):
        return None
    names = [line.split()[0] for line in proc.stdout.splitlines() if line.split()]
    st = {"checked_at": time.time(), "count": len(names), "packages": names[:10]}
    os.makedirs(state_dir(), exist_ok=True)
    with open(state_file(), "w") as fh:
        json.dump(st, fh)
    return st


def notify(count: int) -> bool:
    """Desktop notification in the user's session, mirrored to speech when a
    screen reader is running (the bubble is visual-only and expires in
    seconds; a blind daily driver must not miss updates). True if the visual
    notification was sent."""
    if count <= 0:
        return False
    s = "s" if count != 1 else ""
    title = f"{count} update{s} available"
    body = "AI-2 and the system update together. In a terminal, run:  sudo pacman -Syu"
    sent = False
    if shutil.which("notify-send"):
        try:
            subprocess.run(["notify-send", "--app-name=AI-2", "--icon=ai2", title, body],
                           timeout=10)
            sent = True
        except (OSError, subprocess.TimeoutExpired):
            pass
    from . import a11y
    if a11y.reader_active():
        a11y.speak_once(f"AI-2: {title}. Update with: sudo pacman -Syu")
    return sent
