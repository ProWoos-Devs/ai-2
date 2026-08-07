"""systemd backend. Secondary; exists so the engine runs on dev machines and
keeps the Debian/Ubuntu institutional path reachable."""

from __future__ import annotations

import shutil
import subprocess

SERVICE_ALIASES = {
    "cupsd": "cups",
    "bluetoothd": "bluetooth",
}


class SystemdBackend:
    name = "systemd"

    def _unit(self, service: str) -> str:
        return SERVICE_ALIASES.get(service, service)

    def available_services(self) -> list[str]:
        return []

    def is_enabled(self, service: str) -> bool | None:
        if not shutil.which("systemctl"):
            return None
        try:
            out = subprocess.run(
                ["systemctl", "is-enabled", self._unit(service)],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
        except (subprocess.SubprocessError, OSError):
            return None
        if out in ("enabled", "enabled-runtime", "static"):
            return True
        if out in ("disabled", "masked"):
            return False
        return None

    def enable_cmd(self, service: str) -> list[str]:
        return ["systemctl", "enable", "--now", self._unit(service)]

    def disable_cmd(self, service: str) -> list[str]:
        return ["systemctl", "disable", "--now", self._unit(service)]
