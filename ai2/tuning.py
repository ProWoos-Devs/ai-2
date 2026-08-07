"""The tuning engine. Builds a declarative action plan from a tier config,
prints it (dry run) or applies it (root). Never mutates anything while
planning."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Callable

from .detect import Hardware
from .tiers import Tier

SYSCTL_PATH = "/etc/sysctl.d/90-ai2.conf"
STATE_DIR = "/etc/ai2"


@dataclass
class Action:
    description: str
    run: Callable[[], None]
    commands: list[list[str]] = field(default_factory=list)


def _write_file_action(path: str, content: str, description: str) -> Action:
    def run():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(content)
    return Action(description=description, run=run)


def _cmd_action(cmd: list[str], description: str) -> Action:
    def run():
        subprocess.run(cmd, check=True)
    return Action(description=description, run=run, commands=[cmd])


def build_plan(hw: Hardware, tier: Tier, config: dict, backend) -> list[Action]:
    actions: list[Action] = []

    kernel = config.get("kernel") or {}
    if kernel:
        lines = "".join(f"{key} = {value}\n" for key, value in sorted(kernel.items()))
        content = f"# Managed by AI-2, tier {tier.label}. Manual edits will be overwritten.\n{lines}"
        actions.append(_write_file_action(
            SYSCTL_PATH, content,
            f"write {SYSCTL_PATH} ({', '.join(f'{k}={v}' for k, v in sorted(kernel.items()))})",
        ))
        actions.append(_cmd_action(["sysctl", "--load", SYSCTL_PATH], "reload sysctl settings"))

    memory = config.get("memory") or {}
    if memory:
        mechanism = memory.get("mechanism")
        algorithm = memory.get("algorithm", "zstd")
        content = "".join(f"{key} = {value}\n" for key, value in sorted(memory.items()))
        actions.append(_write_file_action(
            os.path.join(STATE_DIR, "memory.conf"), content,
            f"write {STATE_DIR}/memory.conf (mechanism {mechanism}, {algorithm})",
        ))

    services = (config.get("services") or {}).get("never") or []
    for service in services:
        enabled = backend.is_enabled(service)
        if enabled:
            actions.append(_cmd_action(
                backend.disable_cmd(service),
                f"disable service {service} ({backend.name})",
            ))
        elif enabled is None:
            actions.append(Action(
                description=f"service {service} not found on this system, nothing to do",
                run=lambda: None,
            ))

    guard = config.get("oom_guard")
    if guard:
        if backend.is_enabled(guard) is False or backend.is_enabled(guard) is None:
            actions.append(_cmd_action(
                backend.enable_cmd(guard),
                f"enable OOM guard {guard} ({backend.name}), requires package '{guard}'",
            ))

    runtime = config.get("runtime") or {}
    if runtime:
        content = "".join(f"{key} = {value}\n" for key, value in sorted(runtime.items()))
        actions.append(_write_file_action(
            os.path.join(STATE_DIR, "runtime.conf"), content,
            f"write {STATE_DIR}/runtime.conf (provider {runtime.get('provider')}, "
            f"service {runtime.get('service')})",
        ))

    session = config.get("session") or {}
    if session:
        content = "".join(f"{key} = {value}\n" for key, value in sorted(session.items()))
        actions.append(_write_file_action(
            os.path.join(STATE_DIR, "session.conf"), content,
            f"write {STATE_DIR}/session.conf (desktop {session.get('desktop')}, "
            f"login {session.get('login')})",
        ))

    actions.append(_write_file_action(
        os.path.join(STATE_DIR, "tier"), tier.id + "\n",
        f"record assigned tier '{tier.id}' in {STATE_DIR}/tier",
    ))
    return actions


def render_plan(actions: list[Action]) -> str:
    lines = []
    for i, action in enumerate(actions, 1):
        lines.append(f"  {i:2d}. {action.description}")
        for cmd in action.commands:
            lines.append(f"        $ {' '.join(cmd)}")
    return "\n".join(lines)


def apply_plan(actions: list[Action]) -> None:
    if os.geteuid() != 0:
        raise PermissionError("applying the plan requires root, re-run with sudo")
    for action in actions:
        action.run()
