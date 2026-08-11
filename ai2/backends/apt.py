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
        return subprocess.run(
            ["dpkg", "-s", pkg], capture_output=True, text=True
        ).returncode == 0

    def install_cmd(self, pkgs: list[str]) -> list[str]:
        return ["apt-get", "install", "-y", *pkgs]
