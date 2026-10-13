"""Crash records: what stopped unexpectedly on this computer, and what to do.

The kernel hands every core-dumping crash to /usr/lib/ai2/crash-handler
(kernel.core_pattern, set by /usr/lib/sysctl.d/60-ai2-crashes.conf in the
package), which keeps no dump and appends one line to LOG:

    <epoch> <uid> <pid> <signal> <comm> <path with ! for />

This module reads that file. The desktop says once, at the login round of the
update check, what crashed since the last time it said so (one bubble, no
button, the mark in the state dir); `ai-2 doctor` has a check; `ai-2 crashes`
lists them; `ai-2 report` carries the raw lines. Only the user's own
processes are reported to the user: another account's crashes are not theirs
to act on.

The one crash AI-2 can explain on its own is the AI engine dying with an
illegal instruction: that is a build that does not fit this CPU (the first
real bug of this project, a pre-SSE4.1 machine running an SSE4.1 build), and
the message says so. Everything else is named and counted, with doctor as the
next step; the Knowledge Packs are mentioned when they are installed."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from .serverstate import state_dir

LOG = "/var/lib/ai2/crashes.log"
HANDLER = "/usr/lib/ai2/crash-handler"
SEEN_NAME = "crashes-seen"
WINDOW_S = 7 * 24 * 3600          # doctor and the listing look this far back
ENGINE_DIR = "/usr/lib/ai2/runtimes/"

SIGNAL_NAMES = {
    3: "SIGQUIT", 4: "SIGILL", 5: "SIGTRAP", 6: "SIGABRT", 7: "SIGBUS", 8: "SIGFPE",
    11: "SIGSEGV", 24: "SIGXCPU", 25: "SIGXFSZ", 31: "SIGSYS",
}
SIGNAL_WORDS = {
    4: "an illegal instruction", 6: "an abort", 7: "a bus error", 8: "an arithmetic error",
    11: "a memory access error", 31: "a forbidden system call",
}


@dataclass
class Crash:
    time: int
    uid: int
    pid: int
    signal: int
    comm: str
    path: str

    @property
    def is_engine(self) -> bool:
        return self.path.startswith(ENGINE_DIR)

    @property
    def program(self) -> str:
        """What to call it: the AI engine for our runtimes, else the name."""
        return "the AI engine" if self.is_engine else self.comm

    @property
    def signal_name(self) -> str:
        return SIGNAL_NAMES.get(self.signal, f"signal {self.signal}")

    @property
    def when(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.time))


def parse_line(line: str) -> Crash | None:
    parts = line.split()
    if len(parts) < 5:
        return None
    try:
        t, uid, pid, sig = (int(parts[i]) for i in range(4))
    except ValueError:
        return None
    path = parts[5].replace("!", "/") if len(parts) > 5 else ""
    return Crash(t, uid, pid, sig, parts[4], path)


def read(path: str | None = None) -> list[Crash]:
    """Every record in the log, oldest first. An unreadable or absent log is
    an empty list: nothing crashed, or nothing was recorded."""
    try:
        with open(path or LOG, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    return [c for c in (parse_line(l) for l in lines) if c is not None]


def mine(since: float | None = None, path: str | None = None, uid: int | None = None) -> list[Crash]:
    """This account's crashes, newest last, from `since` (default: the window)."""
    uid = os.getuid() if uid is None else uid
    cutoff = (time.time() - WINDOW_S) if since is None else since
    return [c for c in read(path) if c.uid == uid and c.time >= cutoff]


def recording() -> bool:
    """True when the kernel is set to call our handler (sysctl applied)."""
    try:
        with open("/proc/sys/kernel/core_pattern") as fh:
            return fh.read().strip().startswith("|" + HANDLER)
    except OSError:
        return False


def summarize(crashes: list[Crash]) -> list[dict]:
    """One entry per program: count, the last time, the signal of the last
    one, and whether it is the engine. Most recent program first."""
    by: dict[str, dict] = {}
    for c in crashes:
        key = c.program
        entry = by.setdefault(key, {"program": key, "count": 0, "last": c, "engine": c.is_engine})
        entry["count"] += 1
        if c.time >= entry["last"].time:
            entry["last"] = c
    return sorted(by.values(), key=lambda e: -e["last"].time)


def hint(entry: dict) -> str:
    """The sentence after the fact, for doctor and the listing."""
    last = entry["last"]
    if entry["engine"] and last.signal == 4:
        return ("its build does not fit this CPU (illegal instruction). Run  ai-2 doctor ; "
                "if it finds nothing wrong, send  ai-2 report")
    if entry["engine"]:
        return "run  ai-2 doctor ; if it finds nothing wrong, send  ai-2 report"
    return "if it keeps happening, run  ai-2 doctor  or ask Search Knowledge about it"


def describe(entry: dict) -> str:
    last = entry["last"]
    how = SIGNAL_WORDS.get(last.signal)
    what = f"stopped with {how}" if how else f"stopped unexpectedly ({last.signal_name})"
    times = "once" if entry["count"] == 1 else f"{entry['count']} times"
    return f"{entry['program']} {what}, {times}, last {last.when}"


# --- telling the user once -------------------------------------------------

def seen_file() -> str:
    return os.path.join(state_dir(), SEEN_NAME)


def last_seen() -> int:
    try:
        with open(seen_file()) as fh:
            return int(fh.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def mark_seen(t: int) -> None:
    try:
        os.makedirs(state_dir(), exist_ok=True)
        with open(seen_file(), "w") as fh:
            fh.write(f"{t}\n")
    except OSError:
        pass


def unseen(path: str | None = None, uid: int | None = None) -> list[Crash]:
    """This account's crashes newer than the last ones it was told about.
    The first run on a machine tells only about the last day, not the whole
    log of a computer that was used for weeks without this version."""
    since = max(last_seen() + 1, int(time.time()) - 24 * 3600)
    return mine(since=since, path=path, uid=uid)


def build_notice(crashes: list[Crash]) -> tuple[str, str]:
    """Title and body of the bubble, kept apart from the sending."""
    from .i18n import tr
    entries = summarize(crashes)
    first = entries[0]
    name = first["program"][:1].upper() + first["program"][1:]   # a title starts with a capital
    if len(entries) == 1:
        title = tr("{program} stopped unexpectedly").format(program=name)
    elif len(entries) == 2:
        title = tr("{program} and one other program stopped unexpectedly").format(program=name)
    else:
        title = tr("{program} and {n} other programs stopped unexpectedly").format(
            program=name, n=len(entries) - 1)
    if first["engine"] and first["last"].signal == 4:
        body = tr("The AI engine's build does not fit this CPU. In a terminal, run:  ai-2 doctor")
    else:
        body = tr("Nothing was sent anywhere. For what to do, run:  ai-2 doctor  (or  ai-2 crashes  for the list)")
    return title, body


def notify_new(show=None) -> bool:
    """Say once what crashed since the last notice, then remember it. Returns
    True when a bubble was shown. No bubble means nothing new, or no
    notification daemon; in the latter case nothing is marked seen, so a
    desktop that comes later still gets told."""
    crashes = unseen()
    if not crashes:
        return False
    title, body = build_notice(crashes)
    from . import a11y, updates
    if a11y.reader_active():
        a11y.speak_once(f"AI-2: {title}. {body}")
    show = show or updates.show
    shown = bool(show(title, body, None))
    if shown:
        mark_seen(max(c.time for c in crashes))
    return shown


# --- doctor and the listing -------------------------------------------------

def check() -> tuple[str, str]:
    """(status, detail) for `ai-2 doctor`; the Check class stays in doctor."""
    if not recording():
        return ("info", "not recorded (kernel.core_pattern is not AI-2's handler; "
                        "sudo sysctl --system  turns it on)")
    entries = summarize(mine())
    if not entries:
        return ("ok", "none recorded for this account in the last 7 days")
    worst = "warn"
    parts = []
    for e in entries:
        if e["engine"]:
            worst = "fail"
        parts.append(describe(e) + "; " + hint(e))
    return (worst, " | ".join(parts))


def listing(say=print) -> int:
    """`ai-2 crashes`: this account's records of the last 7 days, newest first."""
    if not recording():
        say("Crashes are not being recorded: kernel.core_pattern is not AI-2's handler.")
        say("Turn it on with:  sudo sysctl --system   (the next boot does it by itself)")
        return 1
    crashes = mine()
    if not crashes:
        say("Nothing stopped unexpectedly for this account in the last 7 days.")
        return 0
    say("Programs that stopped unexpectedly in the last 7 days (this account; no dump was kept):")
    for c in reversed(crashes):
        how = SIGNAL_WORDS.get(c.signal, c.signal_name)
        say(f"  {c.when}  {c.program:<24} {how}")
    say("")
    for e in summarize(crashes):
        say(f"{e['program']}: {hint(e)}")
    try:
        from .pack import installed_packs
        if installed_packs():
            say("The Knowledge Packs may know the program: Applications > AI-2 > Search Knowledge, "
                "or  ai-2 doc search \"<program name> stopped\"")
    except Exception:  # noqa: BLE001 - the listing must not fail over an optional hint
        pass
    return 0
