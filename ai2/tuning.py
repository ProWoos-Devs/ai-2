"""The tuning engine. Builds a declarative action plan from a tier config,
prints it (dry run) or applies it (root). Never mutates anything while
planning."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Callable

from .detect import Hardware
from .runtime import runtime_package
from .tiers import Tier

SYSCTL_PATH = "/etc/sysctl.d/90-ai2.conf"
STATE_DIR = "/etc/ai2"
BOOT_TUNING = "/usr/lib/ai2/boot-tuning.sh"

# Concrete tooling for an abstract mechanism, keyed by service-backend name.
# This is where the Debian/systemd variants slot in later (e.g. zram-generator).
ZRAM_PROVIDERS = {
    "runit": {
        "packages": ["zramen", "zramen-runit"],
        "service": "zramen",
        "conf_path": "/etc/runit/sv/zramen/conf",
    },
}
OOM_PROVIDERS = {
    "runit": {"packages": ["earlyoom", "earlyoom-runit"], "service": "earlyoom"},
}


def _zramen_conf(algorithm: str, size_percent: int) -> str:
    return (
        "# Managed by AI-2. Manual edits will be overwritten.\n"
        f"export ZRAM_COMP_ALGORITHM='{algorithm}'\n"
        f"export ZRAM_SIZE={size_percent}\n"
        "export ZRAM_PRIORITY=100\n"
    )


MANIFEST_PATH = os.path.join(STATE_DIR, "manifest.json")
BACKUP_SUFFIX = ".ai2-orig"


@dataclass
class Action:
    description: str
    run: Callable[[], None]
    commands: list[list[str]] = field(default_factory=list)
    writes: str | None = None          # file this action writes (for the manifest / revert)
    service: str | None = None         # service whose state this action changes
    service_target: bool | None = None # desired enabled state for that service


def _write_file_action(path: str, content: str, description: str) -> Action:
    def run():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mode = 0o644
        owner = None
        try:
            current = os.stat(path)
            mode = stat.S_IMODE(current.st_mode)
            owner = (current.st_uid, current.st_gid)
        except OSError:
            pass
        fd, tmp = tempfile.mkstemp(prefix=".ai2-", dir=os.path.dirname(path), text=True)
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, mode)
            if owner is not None:
                os.chown(tmp, *owner)
            os.replace(tmp, path)
        finally:
            try:
                os.remove(tmp)
            except FileNotFoundError:
                pass
    return Action(description=description, run=run, writes=path)


def _cmd_action(cmd: list[str], description: str, service: str | None = None,
                service_target: bool | None = None) -> Action:
    def run():
        subprocess.run(cmd, check=True)
    return Action(description=description, run=run, commands=[cmd], service=service,
                  service_target=service_target)


def _service_action(backend, service: str, enabled: bool, description: str) -> Action | None:
    """Return an action only when a service transition is actually required."""
    if backend.is_enabled(service) is enabled:
        return None
    cmd = backend.enable_cmd(service) if enabled else backend.disable_cmd(service)
    return _cmd_action(cmd, description, service=service, service_target=enabled)


def _missing(pkg_backend, pkgs: list[str]) -> list[str]:
    """Packages not known to be installed (unknown counts as missing), so an
    ISO install, which already carries zramen/earlyoom/the runtime, needs no
    package database and no network to apply its tuning."""
    return [p for p in pkgs if pkg_backend.is_installed(p) is not True]


def build_plan(hw: Hardware, tier: Tier, config: dict, backend, pkg_backend) -> list[Action]:
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

    # An AI workstation must never input-idle-suspend. The desktop defines
    # "idle" as no keyboard/mouse, NOT no CPU work, so a machine pegged running
    # inference gets suspended mid-generation (verified on RMM-PC 2026-08-13,
    # froze a benchmark repeatedly). Disable it at the login-manager level via
    # an elogind drop-in, which is desktop-agnostic. The DE power manager
    # (e.g. xfce4-power-manager inactivity-on-ac=0) should also be set by the
    # session config, but this is the backstop that always applies.
    logind_dir = "/etc/systemd/logind.conf.d" if backend.name == "systemd" else "/etc/elogind/logind.conf.d"
    actions.append(_write_file_action(
        os.path.join(logind_dir, "10-ai2-no-suspend.conf"),
        "# Managed by AI-2. An AI workstation must not idle-suspend.\n"
        "[Login]\nIdleAction=ignore\n",
        f"disable idle-suspend ({'systemd-logind' if backend.name == 'systemd' else 'elogind'} IdleAction=ignore drop-in)",
    ))

    memory = config.get("memory") or {}
    mechanism = memory.get("mechanism")
    if mechanism == "zram":
        algorithm = memory.get("algorithm", "zstd")
        # A pre-SSE4.1 CPU (baseline build) pays too much for zstd; the tier
        # may name a cheaper algorithm for it.
        if hw.cpu_variant == "baseline" and memory.get("weak_cpu_algorithm"):
            algorithm = memory["weak_cpu_algorithm"]
        size_percent = int(memory.get("size_percent", 100))
        provider = ZRAM_PROVIDERS.get(backend.name)
        if provider is None:
            actions.append(Action(
                description=f"no zram provider for backend '{backend.name}', skipping",
                run=lambda: None,
            ))
        else:
            missing = _missing(pkg_backend, provider["packages"])
            if missing:
                actions.append(_cmd_action(
                    pkg_backend.install_cmd(missing),
                    f"install zram tooling: {' '.join(missing)} ({pkg_backend.name})",
                ))
            actions.append(_write_file_action(
                provider["conf_path"], _zramen_conf(algorithm, size_percent),
                f"configure zram ({algorithm}, {size_percent}% of RAM) in {provider['conf_path']}",
            ))
            action = _service_action(
                backend, provider["service"], True,
                f"enable zram swap service '{provider['service']}' ({backend.name})")
            if action:
                actions.append(action)
    elif backend.name in ZRAM_PROVIDERS:
        # Reconcile a previous Tiny/Light configuration when moving to zswap.
        provider = ZRAM_PROVIDERS[backend.name]
        action = _service_action(
            backend, provider["service"], False,
            f"disable zram swap service '{provider['service']}' ({backend.name}); "
            f"tier uses {mechanism or 'no compressed swap'}")
        if action:
            actions.append(action)

    # Settings that live in sysfs (zswap parameters, MGLRU) are applied by
    # /usr/lib/ai2/boot-tuning.sh from /etc/ai2/memory.conf, at every boot via
    # the ai2-boot one-shot service and once right now.
    boot_conf = {}
    if mechanism in ("zram", "zswap"):
        # The boot helper also disables stale zswap when switching back to zram.
        boot_conf["mechanism"] = mechanism
    if mechanism == "zswap":
        boot_conf["compressor"] = memory.get("compressor", "zstd")
        boot_conf["zpool"] = memory.get("allocator", "zsmalloc")
    if memory.get("mglru_min_ttl_ms"):
        boot_conf["mglru_min_ttl_ms"] = int(memory["mglru_min_ttl_ms"])
    if boot_conf:
        content = "# Managed by AI-2, read by /usr/lib/ai2/boot-tuning.sh at boot.\n" + "".join(
            f"{k} = {v}\n" for k, v in boot_conf.items())
        what = ", ".join(f"{k}={v}" for k, v in boot_conf.items())
        actions.append(_write_file_action(
            os.path.join(STATE_DIR, "memory.conf"), content,
            f"write {STATE_DIR}/memory.conf ({what})",
        ))
        if os.path.isfile(BOOT_TUNING):
            action = _service_action(
                backend, "ai2-boot", True,
                f"enable boot-time memory tuning service 'ai2-boot' ({backend.name})")
            if action:
                actions.append(action)
            actions.append(_cmd_action([BOOT_TUNING], "apply the memory settings now"))
        else:
            actions.append(Action(description=f"{BOOT_TUNING} not installed (ai-2 package too old), "
                                              "memory.conf written but not applied", run=lambda: None))
    elif mechanism and mechanism != "zram":
        actions.append(Action(description=f"memory mechanism '{mechanism}' is not supported, skipping",
                              run=lambda: None))

    services = (config.get("services") or {}).get("never") or []
    for service in services:
        enabled = backend.is_enabled(service)
        if enabled:
            actions.append(_cmd_action(
                backend.disable_cmd(service),
                f"disable service {service} ({backend.name})",
                service=service, service_target=False,
            ))
        elif enabled is None:
            actions.append(Action(
                description=f"service {service} not found on this system, nothing to do",
                run=lambda: None,
            ))

    guard = config.get("oom_guard")
    if guard:
        provider = OOM_PROVIDERS.get(backend.name)
        if provider:
            missing = _missing(pkg_backend, provider["packages"])
            if missing:
                actions.append(_cmd_action(
                    pkg_backend.install_cmd(missing),
                    f"install OOM guard: {' '.join(missing)} ({pkg_backend.name})",
                ))
            action = _service_action(
                backend, provider["service"], True,
                f"enable OOM guard service '{provider['service']}' ({backend.name})")
            if action:
                actions.append(action)

    runtime = config.get("runtime") or {}
    if runtime.get("provider") == "llama.cpp":
        # The CPU-variant runtime package from the signed [ai2] repo. Installing
        # the wrong variant is worse than none (SIGILL), so this follows
        # hw.cpu_variant, never the tier.
        pkg = runtime_package(hw.cpu_variant)
        if pkg and pkg_backend.is_installed(pkg) is False:
            actions.append(_cmd_action(
                pkg_backend.install_cmd([pkg]),
                f"install llama.cpp runtime for this CPU: {pkg} ({pkg_backend.name})",
            ))
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


def _load_manifest() -> dict:
    import json
    try:
        with open(MANIFEST_PATH) as fh:
            manifest = json.load(fh)
            # v1 recorded only services AI-2 enabled, whose original state was
            # therefore disabled. Disabled services could not be recovered.
            states = manifest.setdefault("service_states", {})
            for service in manifest.pop("services", []):
                states.setdefault(service, False)
            manifest.setdefault("files", [])
            return manifest
    except (OSError, ValueError):
        return {"version": 2, "files": [], "service_states": {}}


def _save_manifest(m: dict) -> None:
    import json
    os.makedirs(STATE_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".manifest-", dir=STATE_DIR, text=True)
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(m, fh, indent=1)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, MANIFEST_PATH)
    finally:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass


def _prepare_file(path: str) -> None:
    """Preserve the first pre-AI-2 version before the manifest claims a file."""
    backup = path + BACKUP_SUFFIX
    if not os.path.isfile(path) or os.path.exists(backup):
        return
    with open(path) as src:
        managed = "Managed by AI-2" in src.read()
    if not managed:
        shutil.copy2(path, backup)


def revert(backend) -> list[str]:
    """Undo what `init --apply` recorded in the manifest: restore backed-up
    originals or remove files AI-2 created, disable the services it enabled.
    Never removes packages. Returns the list of things done."""
    if os.geteuid() != 0:
        raise PermissionError("reverting requires root, re-run with sudo")
    m = _load_manifest()
    done = []
    for svc, originally_enabled in m.get("service_states", {}).items():
        current = backend.is_enabled(svc)
        if current is None or current is originally_enabled:
            continue
        cmd = backend.enable_cmd(svc) if originally_enabled else backend.disable_cmd(svc)
        result = subprocess.run(cmd, check=False)
        if result.returncode == 0:
            done.append(f"{'enabled' if originally_enabled else 'disabled'} service {svc}")
    for path in m.get("files", []):
        backup = path + BACKUP_SUFFIX
        if os.path.exists(backup):
            os.replace(backup, path)
            done.append(f"restored {path} from {backup}")
        elif os.path.exists(path):
            os.remove(path)
            done.append(f"removed {path}")
    try:
        os.remove(MANIFEST_PATH)
    except OSError:
        pass
    return done


def apply_plan(actions: list[Action], backend=None) -> None:
    if os.geteuid() != 0:
        raise PermissionError("applying the plan requires root, re-run with sudo")
    manifest = _load_manifest()
    for i, action in enumerate(actions, 1):
        try:
            # Record recoverability before mutation: SIGTERM or power loss after
            # action.run() must not leave an untracked root-level change.
            if action.writes and action.writes not in manifest["files"]:
                _prepare_file(action.writes)
                manifest["files"].append(action.writes)
                _save_manifest(manifest)
            if action.service and action.service not in manifest["service_states"]:
                before = backend.is_enabled(action.service) if backend else None
                if before is not None:
                    manifest["service_states"][action.service] = before
                    _save_manifest(manifest)
            action.run()
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"step {i} failed ({action.description}): command "
                               f"'{' '.join(str(c) for c in exc.cmd)}' exited {exc.returncode}; "
                               f"steps 1-{i - 1} were applied") from exc
        except OSError as exc:
            raise RuntimeError(f"step {i} failed ({action.description}): {exc}; "
                               f"steps 1-{i - 1} were applied") from exc
