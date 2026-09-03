"""`ai-2 doctor`: read-only health checks composed from what the other
modules already know, and `ai-2 report`: the same plus the raw facts, as one
text file a user can attach to a bug report (no prompts, no chat content)."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

from . import __version__, serverstate, updates
from .detect import Hardware
from .models import load_catalog, recommend
from .runtime import find_model_file, find_runtime, model_dir, runtime_package
from .state import load_score, score_paths
from .sysinfo import free_disk_mb, mem_available_mib
from .tiers import installed_tier_id, load_tiers, resolve_config
from .tuning import STATE_DIR, SYSCTL_PATH

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"


@dataclass
class Check:
    status: str
    name: str
    detail: str


def _run(cmd: list[str], timeout: int = 10) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def check_runtime(hw: Hardware) -> Check:
    pkg = runtime_package(hw.cpu_variant)
    rt = find_runtime(hw.cpu_variant)
    if rt:
        return Check(OK, "AI engine", f"{hw.cpu_variant} build at {rt}")
    return Check(FAIL, "AI engine", f"no llama.cpp build for this CPU ({hw.cpu_variant}); "
                                    f"run: ai-2 runtime install --apply  (package {pkg})")


def check_other_runtimes(hw: Hardware) -> Check:
    """The ISO installs all three CPU builds; two are dead weight on any one machine."""
    extra = [v for v in ("baseline", "noavx", "avx2") if v != hw.cpu_variant and find_runtime(v)]
    if extra:
        return Check(INFO, "Unused engines", f"{', '.join(extra)} build(s) also installed, about 25 MB each; "
                                             f"remove with: sudo pacman -R " + " ".join(runtime_package(v) for v in extra))
    return Check(OK, "Unused engines", "none")


def check_score() -> Check:
    score = load_score()
    if not score:
        return Check(WARN, "AI Score", "not measured yet; run: ai-2 benchmark")
    where = next((p for p in score_paths() if os.path.isfile(p)), "?")
    age = ""
    try:
        import time
        days = (time.time() - os.path.getmtime(where)) / 86400
        age = f", {days:.0f} days old" if days >= 1 else ""
    except OSError:
        pass
    return Check(OK, "AI Score", f"{score.get('ai_score')}/100, {score.get('tg_tps')} tok/s ({where}{age})")


def check_models(hw: Hardware) -> list[Check]:
    out = []
    catalog = load_catalog()
    present = [(m, find_model_file(m["file"])) for m in catalog]
    present = [(m, p) for m, p in present if p]
    if not present:
        out.append(Check(WARN, "Models", "no model downloaded; run: ai-2 model pull"))
    for m, p in present:
        size = os.path.getsize(p) // (1024 * 1024)
        if abs(size - m["file_mb"]) > 5:
            out.append(Check(FAIL, "Model " + m["id"], f"{p} is {size} MB, catalog says {m['file_mb']} MB; "
                                                     f"delete it and run: ai-2 model pull {m['id']}"))
        else:
            out.append(Check(OK, "Model " + m["id"], f"{p} ({size} MB)"))
    score = load_score()
    if score:
        rec = recommend(hw.ram_mib, score.get("tg_tps", 0.0), score.get("bench_params_b", 0.5), catalog)
        local = rec["local"]
        if local and not find_model_file(local["file"]):
            out.append(Check(WARN, "Recommended model", f"{local['label']} not downloaded; run: ai-2 model pull"))
        if local:
            avail = mem_available_mib()
            if avail is not None and avail < local["ram_peak_mb"]:
                out.append(Check(WARN, "Free RAM", f"{avail} MiB available now, {local['label']} peaks at "
                                                   f"about {local['ram_peak_mb']} MiB"))
    return out


def check_disk() -> Check:
    d = model_dir()
    free = free_disk_mb(d)
    if free is None:
        return Check(INFO, "Disk", f"could not read free space for {d}")
    status = OK if free > 2000 else (WARN if free > 500 else FAIL)
    return Check(status, "Disk", f"{free} MB free in {d}")


def check_tier() -> Check:
    tid = installed_tier_id()
    if not tid:
        return Check(WARN, "Tuning", "ai-2 init --apply has not been run (no /etc/ai2/tier)")
    return Check(OK, "Tuning", f"tier '{tid}' applied")


def check_sysctl() -> Check:
    if not os.path.isfile(SYSCTL_PATH):
        return Check(INFO, "Kernel settings", f"{SYSCTL_PATH} not present (tuning not applied)")
    wrong = []
    with open(SYSCTL_PATH) as fh:
        for line in fh:
            if "=" not in line or line.startswith("#"):
                continue
            key, value = [x.strip() for x in line.split("=", 1)]
            path = "/proc/sys/" + key.replace(".", "/")
            try:
                with open(path) as p:
                    live = p.read().split()[0]
            except (OSError, IndexError):
                continue
            if live != value:
                wrong.append(f"{key} is {live}, expected {value}")
    if wrong:
        return Check(WARN, "Kernel settings", "; ".join(wrong) + f"  (sudo sysctl --load {SYSCTL_PATH})")
    return Check(OK, "Kernel settings", f"{SYSCTL_PATH} in effect")


def check_zram() -> Check:
    try:
        with open("/proc/swaps") as fh:
            swaps = [l.split()[0] for l in fh.read().splitlines()[1:] if l.strip()]
    except OSError:
        return Check(INFO, "Swap", "cannot read /proc/swaps")
    zram = [s for s in swaps if "zram" in s]
    if zram:
        return Check(OK, "Swap", f"zram active ({', '.join(zram)})")
    if swaps:
        return Check(INFO, "Swap", f"disk swap only ({', '.join(swaps)})")
    tid = installed_tier_id()
    if tid in ("tiny", "light"):
        return Check(WARN, "Swap", "no zram swap although the tier asks for it; reboot or: sudo ai-2 init --apply")
    return Check(INFO, "Swap", "none")


def check_mglru() -> Check:
    base = "/sys/kernel/mm/lru_gen"
    if not os.path.isdir(base):
        return Check(INFO, "MGLRU", "kernel built without multi-gen LRU")
    try:
        enabled = open(f"{base}/enabled").read().strip()
        ttl = open(f"{base}/min_ttl_ms").read().strip()
    except OSError:
        return Check(INFO, "MGLRU", "present, not readable")
    if enabled.endswith("7") or enabled.lower().startswith("y") or enabled == "0x0007":
        return Check(OK if ttl != "0" else INFO, "MGLRU", f"enabled ({enabled}), min_ttl_ms {ttl}")
    return Check(INFO, "MGLRU", f"disabled ({enabled})")


def check_service(backend, name: str, expected: bool) -> Check:
    enabled = backend.is_enabled(name)
    if enabled is None:
        return Check(INFO, f"Service {name}", "not present on this system")
    if enabled == expected:
        return Check(OK, f"Service {name}", "enabled" if enabled else "disabled")
    return Check(WARN, f"Service {name}", f"{'disabled' if expected else 'enabled'}, expected "
                                          f"{'enabled' if expected else 'disabled'}; sudo ai-2 init --apply")


def check_server() -> Check:
    running = serverstate.read_server()
    if running:
        return Check(INFO, "AI server", f"running (pid {running['pid']}, model {running.get('model') or '?'}, "
                                        f"port {running['port']}); ai-2 stop frees its RAM")
    return Check(OK, "AI server", "not running (starts on demand with ai-2 chat)")


def check_keyring() -> Check:
    if not shutil.which("pacman-key"):
        return Check(INFO, "Package signing", "not a pacman system")
    out = _run(["pacman-key", "--list-keys", "F1889E37B4E5FEC8"])
    if "F1889E37B4E5FEC8" in out.replace(" ", ""):
        return Check(OK, "Package signing", "AI-2 repository key trusted")
    return Check(FAIL, "Package signing", "AI-2 key missing; updates from [ai2] will fail. "
                                          "Run: sudo pacman-key --populate ai2")


def check_updates() -> Check:
    if not shutil.which("checkupdates"):
        return Check(INFO, "Updates", "checkupdates not installed (pacman-contrib)")
    # Shared with the login hint and the desktop bubble: reads checkupdates'
    # exit code (1 is a failure, not "nothing to do") and warms their cache.
    st = updates.load_state() if updates.state_is_fresh(1) else updates.check_now(timeout_s=60)
    if st is None:
        return Check(INFO, "Updates", "could not check (offline, or the mirror did not answer); later: ai-2 update")
    n = st.get("count", 0)
    return Check(INFO, "Updates", f"{n} package update(s) available; run: ai-2 update" if n else "system is current")


def run_checks(hw: Hardware, backend=None) -> list[Check]:
    checks = [check_tier(), check_runtime(hw), check_other_runtimes(hw), check_score()]
    checks += check_models(hw)
    checks += [check_disk(), check_sysctl(), check_zram(), check_mglru()]
    if backend is not None:
        checks.append(check_service(backend, "earlyoom", True))
        tid = installed_tier_id()
        if tid:
            tiers = load_tiers()
            never = (resolve_config(tiers[tid], tiers).get("services") or {}).get("never") or []
            for svc in never:
                checks.append(check_service(backend, svc, False))
    checks += [check_server(), check_keyring(), check_updates()]
    return checks


def render(checks: list[Check]) -> str:
    mark = {OK: "ok  ", WARN: "WARN", FAIL: "FAIL", INFO: "    "}
    return "\n".join(f"  {mark[c.status]}  {c.name:<20} {c.detail}" for c in checks)


def verdict(checks: list[Check]) -> int:
    if any(c.status == FAIL for c in checks):
        return 2
    if any(c.status == WARN for c in checks):
        return 1
    return 0


def report_text(hw: Hardware, checks: list[Check]) -> str:
    """Everything a bug report needs, nothing personal: no hostname, no user
    name, no prompts. Paths under the home directory are shortened."""
    import json
    import platform
    from dataclasses import asdict

    home = os.path.expanduser("~")
    lines = [f"AI-2 report, ai-2 {__version__}, kernel {platform.release()}", ""]
    lines.append("== Hardware")
    lines.append(json.dumps(asdict(hw) | {"cpu_variant": hw.cpu_variant}, default=list, indent=1))
    lines.append("\n== Checks")
    lines.append(render(checks))
    lines.append("\n== Packages")
    for pkg in ["ai-2", "ai2-keyring", "ai2-llama-cpp-baseline", "ai2-llama-cpp-noavx", "ai2-llama-cpp-avx2",
                "zramen", "earlyoom", "linux"]:
        out = _run(["pacman", "-Q", pkg]).strip()
        if out:
            lines.append("  " + out)
    lines.append("\n== State files")
    for path in [os.path.join(STATE_DIR, "tier"), os.path.join(STATE_DIR, "runtime.conf"),
                 os.path.join(STATE_DIR, "memory.conf"), SYSCTL_PATH] + score_paths():
        if os.path.isfile(path):
            try:
                body = open(path).read().strip()
            except OSError:
                continue
            lines.append(f"--- {path.replace(home, '~')}")
            lines.append(body)
    log = serverstate.log_file()
    if os.path.isfile(log):
        lines.append(f"\n== Last lines of {log.replace(home, '~')}")
        try:
            with open(log, "rb") as fh:
                fh.seek(0, 2)
                fh.seek(max(0, fh.tell() - 4000))
                tail = fh.read().decode("utf-8", "replace")
            lines.append(tail.replace(home, "~"))
        except OSError:
            pass
    return "\n".join(lines) + "\n"
