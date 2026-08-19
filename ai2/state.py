"""Where AI-2 keeps its small pieces of state (the AI Score).

System-wide when writable (root): /etc/ai2/score.json. Otherwise per user:
~/.config/ai2/score.json. Readers try the user file first, then the system
one, so a user who ran the benchmark without root still gets recommendations.
"""

from __future__ import annotations

import json
import os

SYSTEM_SCORE = "/etc/ai2/score.json"


def user_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "ai2")


def score_paths() -> list[str]:
    """Candidate score files, most specific first."""
    return [os.path.join(user_dir(), "score.json"), SYSTEM_SCORE]


def load_score() -> dict | None:
    for path in score_paths():
        try:
            with open(path) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            continue
    return None


def write_score(data: dict) -> str | None:
    """Persist the score system-wide if possible, else for this user.
    Returns the path written, or None if neither location was writable."""
    targets = [SYSTEM_SCORE] if (os.geteuid() == 0 or os.access(os.path.dirname(SYSTEM_SCORE), os.W_OK)) else []
    targets.append(os.path.join(user_dir(), "score.json"))
    for path in targets:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                json.dump(data, fh, indent=2)
            return path
        except OSError:
            continue
    return None


def setup_done_path() -> str:
    return os.path.join(user_dir(), "setup-done")


def mark_setup_done() -> None:
    os.makedirs(user_dir(), exist_ok=True)
    with open(setup_done_path(), "w") as fh:
        fh.write("AI-2 first-run setup completed. Delete this file to run it again at login.\n")
