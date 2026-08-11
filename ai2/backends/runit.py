"""runit backend (Artix layout).

Artix ships service directories in /etc/runit/sv and enables them by symlink
into the active runsvdir. Verified on a real Artix runit install 2026-08-11
(RMM-PC, the AI-2 test machine): the layout is /etc/runit/runsvdir/{current
-> default, default, single}. We target `default` (the real runlevel dir) so
services are enabled for normal boot regardless of what `current` points to.
"""

from __future__ import annotations

import os

SV_DIR = "/etc/runit/sv"
ENABLED_DIR = "/etc/runit/runsvdir/default"  # verified on real Artix 2026-08-11


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
        # -sfn makes re-enabling idempotent (runsvdir auto-starts within ~5s).
        return ["ln", "-sfn", os.path.join(SV_DIR, service), os.path.join(ENABLED_DIR, service)]

    def disable_cmd(self, service: str) -> list[str]:
        return ["rm", os.path.join(ENABLED_DIR, service)]
