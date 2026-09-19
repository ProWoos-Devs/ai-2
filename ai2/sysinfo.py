"""Small live-system readings the preflight checks need (free disk, free RAM).
Kept apart from detect.py, which describes the machine, not its current load."""

from __future__ import annotations

import os
import shutil


def free_disk_mb(path: str) -> int | None:
    """Free space on the filesystem holding `path` (nearest existing parent)."""
    p = os.path.abspath(path)
    while not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent
    try:
        return shutil.disk_usage(p).free // (1024 * 1024)
    except OSError:
        return None


def mem_available_mib(meminfo_path: str = "/proc/meminfo") -> int | None:
    """MemAvailable right now, in MiB (what a new process can really use)."""
    try:
        with open(meminfo_path) as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def is_live_session(cmdline_path: str = "/proc/cmdline", marker: str = "/run/artix") -> bool:
    """True when this is the session booted from the USB stick, not an
    installed system. Artix's live kernel command line carries
    `overlay=livefs` and the live init leaves /run/artix behind; an installed
    AI-2 has neither (read off a live session on the 2011 laptop, 2026-09-19).
    Things that only make sense on an installed system ask this first."""
    try:
        with open(cmdline_path) as fh:
            if "overlay=livefs" in fh.read():
                return True
    except OSError:
        pass
    return os.path.isdir(marker)
