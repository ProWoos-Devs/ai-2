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
