"""runit backend (Artix layout).

Artix ships service directories in /etc/runit/sv and enables them by symlink
into the active runsvdir. The exact persistent-enable path must be verified on
a real Artix runit install before Phase 0 is called done; VERIFY_ON_ARTIX
marks the assumption.
"""

from __future__ import annotations

import os

SV_DIR = "/etc/runit/sv"
ENABLED_DIR = "/etc/runit/runsvdir/default"  # VERIFY_ON_ARTIX


class RunitBackend:
    name = "runit"

    def available_services(self) -> list[str]:
        try:
            return sorted(os.listdir(SV_DIR))
        except OSError:
            return []

    def is_enabled(self, service: str) -> bool | None:
        if not os.path.isdir(SV_DIR):
            return None
        return os.path.islink(os.path.join(ENABLED_DIR, service))

    def enable_cmd(self, service: str) -> list[str]:
        return ["ln", "-s", os.path.join(SV_DIR, service), ENABLED_DIR]

    def disable_cmd(self, service: str) -> list[str]:
        return ["rm", os.path.join(ENABLED_DIR, service)]
