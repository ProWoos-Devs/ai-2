"""pacman package backend (Artix/Arch). The tuning engine installs tooling
(zramen, earlyoom, ...) through this rather than shelling out directly, so the
apt backend can slot in for the Debian/Ubuntu path later."""

from __future__ import annotations

import shutil
import subprocess


class PacmanBackend:
    name = "pacman"

    def available(self) -> bool:
        return shutil.which("pacman") is not None

    def is_installed(self, pkg: str) -> bool | None:
        if not self.available():
            return None
        try:
            return subprocess.run(
                ["pacman", "-Q", pkg], capture_output=True, text=True, timeout=10
            ).returncode == 0
        except subprocess.TimeoutExpired:
            return None      # a stalled local-db read is "unknown", not "missing"

    def install_cmd(self, pkgs: list[str]) -> list[str]:
        return ["pacman", "-S", "--noconfirm", "--needed", *pkgs]
