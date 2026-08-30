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


# The bubble does not expire. Measured on the shipped image (xfce4-notifyd,
# 2026-08-30): the default bubble was gone within 45 s, `-t 0` and urgency
# critical both survived. `-t 0` is the spec's "never expire" and is the honest
# one, since a pending update is not a critical alert and critical urgency also
# overrides Do Not Disturb.
STICKY = ["-t", "0"]


def build(count: int) -> tuple[str, str, str | None]:
    """Title, body, and the action button's label when there is a graphical
    package manager to open. Separated from the sending so the wording can be
    tested without a notification daemon."""
    from .i18n import tr
    from . import software
    title = (tr("{n} update available") if count == 1
             else tr("{n} updates available")).format(n=count)
    if software.gui_available():
        return (title,
                tr("AI-2 and the system update together. Open Software Updates, "
                   "or run  ai-2 update  in a terminal."),
                tr("Open Software Updates"))
    return (title,
            tr("AI-2 and the system update together. In a terminal, run:  ai-2 update"),
            None)


def notify(count: int, fork=os.fork) -> bool:
    """Desktop notification in the user's session, mirrored to speech when a
    screen reader is running (the bubble is visual-only; a blind daily driver
    must not miss updates).

    The bubble stays until it is dismissed. That matters because it now carries
    a button that opens the package manager on its updates page, and a bubble
    that expires after ten seconds throws away the one click that does the job
    (one fired unseen on a real machine on 2026-08-26).

    A button needs a client alive behind it for as long as the bubble: verified
    on the shipped image, killing notify-send leaves a bubble whose button does
    nothing and which simply vanishes when clicked. So the holding process is
    forked off and the caller returns at once, which keeps `ai-2 update-check`
    usable from a terminal. Without a button there is nothing to wait for and
    notify-send returns on its own.

    True when the bubble was handed over or shown."""
    if count <= 0:
        return False
    title, body, action = build(count)
    from . import a11y
    if a11y.reader_active():
        from .i18n import tr
        a11y.speak_once(f"AI-2: {title}. " + tr("Update with:  ai-2 update"))
    if not shutil.which("notify-send"):
        return False
    if action is None:
        return show(title, body, None)
    try:
        pid = fork()
    except OSError:
        # No fork, so no one can hold the button: a plain sticky bubble is
        # still worth more than nothing.
        return show(title, body, None)
    if pid == 0:                      # child: holds the bubble, then goes away
        try:
            os.setsid()               # survive a Ctrl-C in the parent's terminal
        except OSError:
            pass
        try:
            show(title, body, action)
        finally:
            os._exit(0)
    return True


def show(title: str, body: str, action: str | None, run=None) -> bool:
    """Send one notification. With an action button notify-send implies
    --wait, so this blocks for the life of the bubble and returns the clicked
    action on stdout; there is deliberately no timeout, because any cap would
    turn a still-visible bubble into a dead one whose button does nothing. The
    process costs nothing while it waits and ends with the session."""
    run = run or subprocess.run
    cmd = ["notify-send", "--app-name=AI-2", "--icon=ai2", *STICKY]
    if action:
        cmd.append("--action=open=" + action)
    cmd += [title, body]
    try:
        proc = run(cmd, capture_output=True, text=True)
    except OSError:
        return False
    if proc.returncode != 0:
        # An older libnotify rejects --action; the plain bubble is the point,
        # the button was the extra.
        return show(title, body, None, run=run) if action else False
    if action and proc.stdout.strip() == "open":
        from . import software
        software.open_gui(updates=True)
    return True
