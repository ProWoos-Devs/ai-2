"""apt package backend (Debian/Ubuntu). Stub for the institutional path; the
zram/oom provider tables in tuning.py don't have a Debian mapping yet, so this
exists to keep the engine backend-agnostic, not to be exercised on Artix."""

from __future__ import annotations

import shutil
import subprocess


class AptBackend:
    name = "apt"

    def available(self) -> bool:
        return shutil.which("apt-get") is not None

    def is_installed(self, pkg: str) -> bool | None:
        if not self.available():
            return None
        try:
            return subprocess.run(
                ["dpkg", "-s", pkg], capture_output=True, text=True, timeout=10
            ).returncode == 0
        except subprocess.TimeoutExpired:
            return None      # a stalled local-db read is "unknown", not "missing"

    def install_cmd(self, pkgs: list[str]) -> list[str]:
        return ["apt-get", "install", "-y", *pkgs]
