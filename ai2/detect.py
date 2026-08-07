"""Hardware detection for the Adaptation Engine.

Reads /proc and /sys directly instead of pulling py-cpuinfo/psutil, so the
detection path itself costs nothing on 2 GB machines.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field

# Marketing sizes in GiB used to round MemTotal (which is always below the
# installed amount because of reserved memory) up to the physical module size.
NOMINAL_GIB_STEPS = [1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256]

INTERESTING_FLAGS = ("avx", "avx2", "avx512f", "fma", "sse4_2")


@dataclass
class Gpu:
    name: str
    vram_mb: int | None = None
    vendor: str = "unknown"


@dataclass
class Hardware:
    cpu_model: str = "unknown"
    logical_cores: int = 1
    flags: set[str] = field(default_factory=set)
    ram_mib: int = 0
    ram_nominal_gib: int = 0
    gpus: list[Gpu] = field(default_factory=list)
    root_disk_rotational: bool | None = None
    init_system: str = "unknown"

    @property
    def cpu_variant(self) -> str:
        return "avx2" if "avx2" in self.flags else "noavx"


def parse_cpuinfo(text: str) -> tuple[str, set[str]]:
    model = "unknown"
    flags: set[str] = set()
    for line in text.splitlines():
        if line.startswith("model name") and model == "unknown":
            model = line.split(":", 1)[1].strip()
        elif line.startswith("flags") and not flags:
            flags = set(line.split(":", 1)[1].split()) & set(INTERESTING_FLAGS)
    return model, flags


def parse_meminfo_mib(text: str) -> int:
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) // 1024
    return 0


def nominal_gib(ram_mib: int) -> int:
    gib = ram_mib / 1024
    for step in NOMINAL_GIB_STEPS:
        if gib <= step:
            return step
    return int(gib)


def _nvidia_gpus() -> list[Gpu]:
    if not shutil.which("nvidia-smi"):
        return []
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return []
    gpus = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[1].isdigit():
            gpus.append(Gpu(name=parts[0], vram_mb=int(parts[1]), vendor="nvidia"))
    return gpus


def _lspci_gpus() -> list[Gpu]:
    if not shutil.which("lspci"):
        return []
    try:
        out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=10, check=True).stdout
    except (subprocess.SubprocessError, OSError):
        return []
    gpus = []
    for line in out.splitlines():
        if any(k in line for k in ("VGA compatible controller", "3D controller", "Display controller")):
            name = line.split(":", 2)[-1].strip()
            vendor = "unknown"
            lowered = name.lower()
            if "nvidia" in lowered:
                vendor = "nvidia"
            elif "amd" in lowered or "ati" in lowered:
                vendor = "amd"
            elif "intel" in lowered:
                vendor = "intel"
            gpus.append(Gpu(name=name, vendor=vendor))
    return gpus


def detect_gpus() -> list[Gpu]:
    nvidia = _nvidia_gpus()
    seen_nvidia = bool(nvidia)
    gpus = nvidia
    for gpu in _lspci_gpus():
        if seen_nvidia and gpu.vendor == "nvidia":
            continue
        gpus.append(gpu)
    return gpus


def detect_init_system() -> str:
    if os.path.isdir("/run/runit"):
        return "runit"
    if os.path.isdir("/run/systemd/system"):
        return "systemd"
    if os.path.isdir("/run/openrc"):
        return "openrc"
    return "unknown"


def detect_root_disk_rotational() -> bool | None:
    try:
        dev = os.stat("/").st_dev
        major, minor = os.major(dev), os.minor(dev)
        sys_path = os.path.realpath(f"/sys/dev/block/{major}:{minor}")
        # Walk up from a partition to its parent block device.
        while sys_path and not os.path.exists(os.path.join(sys_path, "queue", "rotational")):
            parent = os.path.dirname(sys_path)
            if parent == sys_path or os.path.basename(parent) == "block":
                return None
            sys_path = parent
        with open(os.path.join(sys_path, "queue", "rotational")) as fh:
            return fh.read().strip() == "1"
    except OSError:
        return None


def detect() -> Hardware:
    hw = Hardware()
    try:
        with open("/proc/cpuinfo") as fh:
            hw.cpu_model, hw.flags = parse_cpuinfo(fh.read())
    except OSError:
        pass
    hw.logical_cores = os.cpu_count() or 1
    try:
        with open("/proc/meminfo") as fh:
            hw.ram_mib = parse_meminfo_mib(fh.read())
    except OSError:
        pass
    hw.ram_nominal_gib = nominal_gib(hw.ram_mib)
    hw.gpus = detect_gpus()
    hw.root_disk_rotational = detect_root_disk_rotational()
    hw.init_system = detect_init_system()
    return hw
