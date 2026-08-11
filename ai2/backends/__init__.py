"""Backends. The tuning engine never talks to an init system or package
manager directly; it goes through a service backend and a package backend so
the Debian/Ubuntu path can slot in without touching the engine."""

from __future__ import annotations

from .apt import AptBackend
from .pacman import PacmanBackend
from .runit import RunitBackend
from .systemd import SystemdBackend


def get_service_backend(init_system: str):
    if init_system == "runit":
        return RunitBackend()
    if init_system == "systemd":
        return SystemdBackend()
    raise ValueError(f"no service backend for init system '{init_system}'")


def get_package_backend():
    """Pick the package backend from what's on the system."""
    for backend in (PacmanBackend(), AptBackend()):
        if backend.available():
            return backend
    raise ValueError("no supported package manager found (pacman/apt)")
