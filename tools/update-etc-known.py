#!/usr/bin/env python3
"""Regenerate packaging/ai-2/etc-known.sha256.

The pacman hook refreshes /etc/motd and the greeter configuration only when
what is there is byte-for-byte a copy AI-2 itself shipped at some point. That
list is what says "at some point": every version of those files that has ever
been committed, plus the ones in the tree now. A file the user edited matches
nothing in it and is left alone.

Run this after changing branding/motd or branding/lightdm-gtk-greeter.conf;
a test fails when the current files are missing from the list.
"""
from __future__ import annotations

import hashlib
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FILES = {"branding/motd": "motd",
         "branding/lightdm-gtk-greeter.conf": "lightdm-gtk-greeter.conf"}
OUT = ROOT / "packaging/ai-2/etc-known.sha256"


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout


def collect() -> list[str]:
    rows = set()
    for path, name in FILES.items():
        rows.add(f"{hashlib.sha256((ROOT / path).read_bytes()).hexdigest()}  {name}")
        for commit in _git("log", "--format=%H", "--", path).split():
            try:
                blob = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:www/ai-2/{path}"],
                                      capture_output=True, check=True).stdout
            except subprocess.CalledProcessError:
                continue
            rows.add(f"{hashlib.sha256(blob).hexdigest()}  {name}")
    return sorted(rows)


def main() -> int:
    rows = collect()
    OUT.write_text("# Every version of these files AI-2 has shipped, newest run "
                   "of tools/update-etc-known.py.\n"
                   "# The pacman hook replaces /etc only when what is there is one of these.\n"
                   + "\n".join(rows) + "\n", encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(rows)} known copies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
