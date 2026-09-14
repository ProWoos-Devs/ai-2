"""Passive update notification (2026-08-24).

One shared check feeds two surfaces: a desktop notification (xfce4-notifyd via
notify-send) and a one-line hint in login shells (/etc/profile.d reads the
state file this module writes). Nothing here installs anything; updating stays
an explicit `sudo pacman -Syu`.

The check runs `pamac-checkupdates` (libpamac), the program pamac's own tray
icon runs hourly. It asks pamac's daemon to refresh the system databases when
they are older than pamac.conf's RefreshPeriod (6 hours; the daemon does that
for any user, no password) and then lists what is pending against those same
databases. That is what makes the bubble and Software Updates agree: until
2026-09-14 the check used pacman-contrib's `checkupdates`, which syncs a
private copy, so the bubble knew about a release minutes after it was
published while Software Updates, which reads the system databases and does
not refresh them when it opens, said there was nothing (rafaminu-pc). AI-2
hides pamac's tray, so nothing else refreshes those databases between
updates. Offline or on any failure the old state is kept and nothing is
reported.
"""
import json
import os
import shutil
import signal
import subprocess
import time

from .serverstate import state_dir

PACMAN_LOCAL_DB = "/var/lib/pacman/local"
PACMAN_LOCK = "/var/lib/pacman/db.lck"
POLL_S = 15            # how often a held bubble looks for a finished update
RECHECK_S = 300        # after a failed check (offline), try again this much later


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


CHECK_CMD = "pamac-checkupdates"   # libpamac; see the module docstring
# pamac's daemon touches this after it refreshed the system databases.
PAMAC_REFRESH_STAMP = "/var/lib/pacman/sync/refresh_timestamp"
PAMAC_CONF = "/etc/pamac.conf"
DEFAULT_REFRESH_PERIOD_H = 6


def _stamp_mtime() -> float | None:
    try:
        return os.path.getmtime(PAMAC_REFRESH_STAMP)
    except OSError:
        return None


def refresh_period_h() -> float:
    """pamac.conf's RefreshPeriod, hours between database refreshes."""
    try:
        with open(PAMAC_CONF) as fh:
            for line in fh:
                key, _, value = line.partition("=")
                if key.strip() == "RefreshPeriod":
                    return float(value.strip())
    except (OSError, ValueError):
        pass
    return DEFAULT_REFRESH_PERIOD_H


def refresh_due(now: float | None = None) -> bool:
    """pamac's own rule (libpamac Database.need_refresh): refresh when the
    last one is at least an hour old and at least RefreshPeriod hours old; a
    missing stamp (fresh offline install) means refresh."""
    mtime = _stamp_mtime()
    if mtime is None:
        return True
    age = (now if now is not None else time.time()) - mtime
    if age < 3600:
        return False
    return age / 3600 >= refresh_period_h()


def _run_check(timeout_s: int):
    """One pamac-checkupdates run: (names, ok). ok is False on a failure that
    must not overwrite a good state. pamac-checkupdates exits 100 with a
    list, 0 with none (libpamac src/checkupdates.vala); lines are
    "name  old -> new" (a replacer has no arrow), the first word is the name."""
    try:
        proc = subprocess.run([CHECK_CMD], capture_output=True, text=True, timeout=timeout_s)
    except (OSError, subprocess.TimeoutExpired):
        return [], False
    if proc.returncode not in (0, 100):
        return [], False
    return [line.split()[0] for line in proc.stdout.splitlines() if line.split()], True


def check_now(timeout_s: int = 600, wait_refresh_s: int = 300, sleep=time.sleep) -> dict | None:
    """Run pamac-checkupdates and persist the result. Returns the new state,
    or None when the check could not run (missing tool, timeout, failure, a
    due refresh that did not happen); old state is kept.

    When a refresh is due, pamac-checkupdates asks the daemon for it and
    lists BEFORE the daemon is done (measured in the QEMU install
    2026-09-14: the check returned "0 updates" at 23:22:39, the daemon wrote
    the databases and the stamp at 23:22:40; the run after it listed 49). A
    fresh AI-2 install is exactly that case, the offline installer leaves the
    sync directory empty. So when a refresh is due this waits for the stamp
    to change, up to wait_refresh_s, and lists again; a stamp that never
    changes means the refresh failed (offline, no daemon) and the honest
    answer is "could not check", never "the system is current"."""
    if not shutil.which(CHECK_CMD):
        return None
    before = _stamp_mtime()
    due = refresh_due()
    names, ok = _run_check(timeout_s)
    if not ok:
        return None
    if due:
        deadline = time.monotonic() + wait_refresh_s
        while _stamp_mtime() == before and time.monotonic() < deadline:
            sleep(1)
        if _stamp_mtime() == before:
            return None
        names, ok = _run_check(timeout_s)
        if not ok:
            return None
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


def show(title: str, body: str, action: str | None, run=None, popen=None) -> bool:
    """Send one notification. Without a button notify-send returns at once.

    With a button notify-send implies --wait, so this blocks for the life of
    the bubble; there is deliberately no timeout, because any cap would turn a
    still-visible bubble into a dead one whose button does nothing. While it
    waits it watches for the updates being installed and then closes the
    bubble (see hold), so "19 updates available" does not stay on screen over
    an up-to-date system (seen in a VM, 2026-09-11). --print-id makes
    notify-send print the bubble's id before it starts waiting (flushed,
    libnotify 0.8.8 tools/notify-send.c); no id means no bubble."""
    run = run or subprocess.run
    cmd = ["notify-send", "--app-name=AI-2", "--icon=ai2", *STICKY]
    if not action:
        try:
            return run(cmd + [title, body], capture_output=True, text=True).returncode == 0
        except OSError:
            return False
    popen = popen or subprocess.Popen
    try:
        proc = popen(cmd + ["--print-id", "--action=open=" + action, title, body],
                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except OSError:
        return False
    if proc.stdout.readline().strip() in ("", "0"):
        # No bubble. An older libnotify rejects --action (nothing printed),
        # and a failed show prints id 0 but would still wait forever. The
        # plain bubble is the point, the button was the extra.
        if proc.poll() is None:
            proc.terminate()
        proc.wait()
        return show(title, body, None, run=run)
    closed_by_us = hold(proc)
    clicked = proc.stdout.read().split()
    proc.wait()
    if not closed_by_us and "open" in clicked:
        from . import software
        software.open_gui(updates=True)
    return True


def _db_mtime() -> float | None:
    try:
        return os.path.getmtime(PACMAN_LOCAL_DB)
    except OSError:
        return None


def hold(proc, clock=time.time) -> bool:
    """Wait until the bubble is clicked or dismissed. If a package
    transaction finishes first (pacman's local db changed and its lock is
    gone) and a fresh check finds nothing pending, close the bubble. That
    covers Software Updates, `ai-2 update` and a plain pacman alike.

    The close is a SIGINT: notify-send's own handler then closes its bubble
    (on_sigint in tools/notify-send.c). Any other signal would leave a bubble
    whose button does nothing. Offline, the check cannot say, so the bubble
    stays and the check is retried later. True when this closed the bubble."""
    seen = _db_mtime()
    retry_at = 0.0
    while True:
        try:
            proc.wait(timeout=POLL_S)
            return False
        except subprocess.TimeoutExpired:
            pass
        mtime = _db_mtime()
        if mtime == seen or os.path.exists(PACMAN_LOCK) or clock() < retry_at:
            continue
        st = check_now()
        if st is None:
            retry_at = clock() + RECHECK_S
            continue
        seen = mtime
        if st["count"] == 0:
            proc.send_signal(signal.SIGINT)
            return True
