"""Per-user migrations: one-shot scripts that finish an update for the account
that runs them (2026-10-12, the idea taken from Omarchy's migrations/).

A package upgrade replaces files the package owns and nothing else. What it
cannot reach is a user's own state: a cache written by old code in a format
the new code reads differently, a marker that should be cleared once, a file
AI-2 put in the home directory and now wants somewhere else. Until now each of
those became a FAQ entry ("it clears within 20 hours") or a hand-applied fix
on the two reference machines. Now it is a script in migrations/, shipped at
/usr/share/ai2/migrations/, that `ai-2 update` runs after a successful
upgrade and that every graphical login runs for the account logging in, so an
update done through Software Updates or a plain pacman is finished too, at the
next login.

The rules, also written out in migrations/README.md for whoever adds one:

- A migration touches ONLY the running user's own files. Anything system-wide
  belongs in a pacman hook (packaging/ai-2/*.hook, which run as root inside the
  transaction, see etc-refresh.sh), never here, so a migration never asks for
  a password and can run silently at login.
- It is idempotent: it checks the state before changing it, so running it
  twice is harmless and a half-run one can be rerun.
- They run in name order and stop at the first failure, which stays pending
  and blocks the later ones (a later one may depend on it). The failure is
  reported, never hidden.
- Each user has a marker per migration under ~/.local/state/ai2/migrations/,
  which is what makes it run once per account, not once per machine.
- Scripts run with `bash -euo pipefail`, no shebang needed, mode 644. The
  first line is a comment saying what the script does, in one sentence; it is
  what the user sees.
"""

from __future__ import annotations

import os
import re
import subprocess
import time

from . import __version__
from .serverstate import state_dir

MIGRATIONS_DIR = "/usr/share/ai2/migrations"
# YYYYMMDD-NN-what-it-does.sh: the date it was written, a two-digit sequence
# within that day, and a slug. Name order is run order.
NAME_RE = re.compile(r"^\d{8}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.sh$")
LOG_NAME = "migrate.log"


def marker_dir() -> str:
    return os.path.join(state_dir(), "migrations")


def log_file() -> str:
    return os.path.join(state_dir(), LOG_NAME)


def available(directory: str | None = None) -> list[str]:
    """Every migration the package ships, in run order. A file whose name does
    not follow the pattern is not a migration and is ignored (the test suite
    refuses to ship one)."""
    try:
        names = os.listdir(directory or MIGRATIONS_DIR)
    except OSError:
        return []
    return sorted(n for n in names if NAME_RE.match(n))


def done(name: str) -> bool:
    return os.path.exists(os.path.join(marker_dir(), name))


def pending(directory: str | None = None) -> list[str]:
    return [n for n in available(directory) if not done(n)]


def describe(path: str) -> str:
    """The first comment line, the one sentence the user is shown."""
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    return line.lstrip("#").strip()
                break
    except OSError:
        pass
    return ""


def _env() -> dict:
    env = dict(os.environ)
    env["AI2_STATE_DIR"] = state_dir()
    env["AI2_CONFIG_DIR"] = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    env["AI2_CONFIG_DIR"] = os.path.join(env["AI2_CONFIG_DIR"], "ai2")
    env["AI2_DATA_DIR"] = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "ai2")
    env["AI2_VERSION"] = __version__
    return env


def _mark(name: str) -> None:
    os.makedirs(marker_dir(), exist_ok=True)
    with open(os.path.join(marker_dir(), name), "w") as fh:
        fh.write(f"done {time.strftime('%Y-%m-%d %H:%M:%S')} ai-2 {__version__}\n")


def run_pending(say=print, directory: str | None = None, run=subprocess.run,
                timeout_s: int = 300) -> tuple[list[str], str | None]:
    """Run what is pending, in order. Returns the names that completed and
    the name of the one that failed, if any (the ones after it were not
    tried). `say` gets one line per migration; nothing is said when nothing
    is pending, so a login with nothing to do stays silent."""
    completed: list[str] = []
    directory = os.path.abspath(directory or MIGRATIONS_DIR)   # the scripts run from the home dir
    todo = pending(directory)
    if not todo:
        return completed, None
    say("Finishing the update for your account:")
    for name in todo:
        path = os.path.join(directory, name)
        what = describe(path) or name
        try:
            proc = run(["bash", "-euo", "pipefail", path], capture_output=True, text=True,
                       timeout=timeout_s, env=_env(), cwd=os.path.expanduser("~"))
        except (OSError, subprocess.SubprocessError) as exc:
            say(f"  FAIL  {what}\n        could not run {path}: {exc}")
            return completed, name
        output = "\n".join(s for s in (proc.stdout.strip(), proc.stderr.strip()) if s)
        if proc.returncode != 0:
            say(f"  FAIL  {what}\n        {path} stopped with code {proc.returncode}"
                + (f"\n        {output}" if output else "")
                + "\n        It stays pending, with the ones after it. Run  ai-2 migrate  to try again.")
            return completed, name
        _mark(name)
        completed.append(name)
        say(f"  ok    {what}" + (f"\n        {output}" if output else ""))
    return completed, None


def run_quietly(directory: str | None = None) -> int:
    """The login run: nothing on a terminal, a record in the state dir when
    something happened. Exit code 1 when a migration failed, so a caller
    that cares can tell."""
    lines: list[str] = []
    completed, failed = run_pending(say=lines.append, directory=directory)
    if lines:
        try:
            os.makedirs(state_dir(), exist_ok=True)
            with open(log_file(), "a", encoding="utf-8") as fh:
                fh.write(f"== {time.strftime('%Y-%m-%d %H:%M:%S')} ai-2 {__version__}\n")
                fh.write("\n".join(lines) + "\n")
        except OSError:
            pass
    return 1 if failed else 0
