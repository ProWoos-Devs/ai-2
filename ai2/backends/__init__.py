"""Service backends. The tuning engine never talks to an init system directly."""

from __future__ import annotations

from .runit import RunitBackend
from .systemd import SystemdBackend


def get_service_backend(init_system: str):
    if init_system == "runit":
        return RunitBackend()
    if init_system == "systemd":
        return SystemdBackend()
    raise ValueError(f"no service backend for init system '{init_system}'")
