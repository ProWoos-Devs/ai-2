"""The health of the computer itself, for `ai-2 doctor`: the disk's own record
of damage (SMART), the battery's remaining capacity and the processor's
temperature. AI-2 is made for old and donated computers, where a worn disk or
a dead battery is more likely than anything wrong with the software, and
nothing in doctor looked at the machine.

Everything here only reads. The functions take their paths as arguments so the
tests can point them at a made-up /sys.

The disk is the one part an ordinary account cannot read. `smartctl` needs
root, so /usr/lib/ai2/disk-health.sh asks it once at every boot (the ai2-boot
service) and leaves the answers in /run/ai2/disk-health/, which anyone may
read. `sudo ai-2 doctor` asks the disk directly. The record holds no serial
number: `smartctl -H -A` prints none."""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess

DISK_CACHE = "/run/ai2/disk-health"
HWMON = "/sys/class/hwmon"
THERMAL = "/sys/class/thermal"

CPU_GUARD = "/run/ai2/cpu-guard/status"

# How close to the limit counts as too close, in degrees.
NEAR_LIMIT = 5
POWER_SUPPLY = "/sys/class/power_supply"
CHASSIS_TYPE = "/sys/class/dmi/id/chassis_type"

# SMBIOS chassis types that carry their own battery: portable, laptop,
# notebook, hand held, sub notebook, tablet, convertible, detachable.
PORTABLE_CHASSIS = {8, 9, 10, 11, 14, 30, 31, 32}

# The drivers that report the processor itself, best first. acpitz is the
# mainboard's own zone: on the 2011 HP it read 37 while k10temp read 50.
CPU_SENSORS = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz")

# The ATA attributes that count damaged places on the disk. A healthy disk
# has 0 in each, and any of them above 0 is how a failing disk starts.
ATA_DAMAGE = {5: "{n} sectors moved away from damaged places", 197: "{n} sectors waiting to be moved",
              198: "{n} sectors that could not be read", 187: "{n} read errors it could not correct"}


def _read(path: str) -> str | None:
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return None


def _read_int(path: str) -> int | None:
    try:
        return int(_read(path) or "")
    except ValueError:
        return None


# --- processor temperature

def firmware_limit(thermal: str = THERMAL) -> tuple[int, str] | None:
    """The lowest temperature at which this computer's own firmware steps in,
    in whole degrees, and what it does there: "passive" (it slows the
    processor down) before "hot" and "critical" (it switches off). None when
    the firmware names no such point."""
    best = None
    for kind in ("passive", "hot", "critical"):
        for path in sorted(glob.glob(os.path.join(thermal, "thermal_zone*", "trip_point_*_type"))):
            if _read(path) != kind:
                continue
            temp = _read_int(path[:-len("_type")] + "_temp")
            if temp and temp > 0 and (best is None or temp < best[0]):
                best = (temp, kind)
        if best:
            return round(best[0] / 1000), best[1]
    return None


def cpu_temperature(hwmon: str = HWMON, thermal: str = THERMAL) -> dict | None:
    """The processor's temperature now and the limit to hold it against, in
    whole degrees Celsius: {"sensor", "now", "limit", "limit_kind"}. None
    when no known sensor answers.

    The limit is the firmware's own (firmware_limit), and only without one
    the sensor's: Intel's "high" value is where that processor starts to
    slow down, but k10temp's is not a limit at all. On the 2011 HP it reads
    70, the processor passes it within a minute of starting any work, and
    the firmware acts at 95."""
    found = {}
    for d in sorted(glob.glob(os.path.join(hwmon, "hwmon*"))):
        name = _read(os.path.join(d, "name"))
        if name in CPU_SENSORS and name not in found:
            found[name] = d
    for name in CPU_SENSORS:
        d = found.get(name)
        if not d:
            continue
        best = None
        for inp in sorted(glob.glob(os.path.join(d, "temp*_input"))):
            now = _read_int(inp)
            if now is None or now <= 0:
                continue
            stem = inp[:-len("_input")]
            own = None
            if name == "coretemp":
                own = _read_int(stem + "_max") or _read_int(stem + "_crit")
            # several cores each have a reading: the hottest one counts
            if best is None or now > best[0]:
                best = (now, own)
        if best:
            limit, kind = None, None
            fw = firmware_limit(thermal)
            if fw:
                limit, kind = fw
            elif best[1]:
                limit, kind = round(best[1] / 1000), "passive"
            return {"sensor": name, "now": round(best[0] / 1000), "limit": limit, "limit_kind": kind}
    return None


def cpu_guard(path: str = CPU_GUARD) -> dict | None:
    """What the processor guard (/usr/lib/ai2/cpu-guard.sh) is doing now:
    {"ceiling", "held", "boost", "max_khz"}. None when it is not running."""
    text = _read(path)
    if not text:
        return None
    raw = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    try:
        return {"ceiling": int(raw["ceiling"]), "held": raw.get("held") == "1", "boost": raw.get("boost"),
                "max_khz": int(raw["max_khz"]) if raw.get("max_khz") else None}
    except (KeyError, ValueError):
        return None


# --- battery

def is_portable(chassis_path: str = CHASSIS_TYPE) -> bool:
    return (_read_int(chassis_path) or 0) in PORTABLE_CHASSIS


def batteries(power_supply: str = POWER_SUPPLY) -> list[dict]:
    """Every battery that is present: {"name", "percent_of_new", "charge",
    "cycles"}. percent_of_new is what a full charge holds now against what it
    held when new, None when the battery does not say."""
    out = []
    for d in sorted(glob.glob(os.path.join(power_supply, "*"))):
        if _read(os.path.join(d, "type")) != "Battery":
            continue
        # a mouse or a headset reports a battery too; theirs has a scope of Device
        if _read(os.path.join(d, "scope")) == "Device":
            continue
        if _read(os.path.join(d, "present")) == "0":
            continue
        percent = None
        for kind in ("energy", "charge"):
            full = _read_int(os.path.join(d, f"{kind}_full"))
            design = _read_int(os.path.join(d, f"{kind}_full_design"))
            if full is not None and design:
                percent = round(100 * full / design)
                break
        out.append({"name": os.path.basename(d), "percent_of_new": percent,
                    "charge": _read_int(os.path.join(d, "capacity")),
                    "cycles": _read_int(os.path.join(d, "cycle_count"))})
    return out


# --- disk

def summarize_smart(data: dict) -> dict:
    """What matters in one `smartctl -j -H -A` answer:
    {"state": "ok" | "worn" | "failing" | "unknown", "detail", "hours"}."""
    hours = (data.get("power_on_time") or {}).get("hours")
    passed = (data.get("smart_status") or {}).get("passed")
    notes = []
    state = "ok"
    nvme = data.get("nvme_smart_health_information_log")
    if isinstance(nvme, dict):
        if nvme.get("critical_warning"):
            state = "failing"
            notes.append("it raises a critical warning")
        if nvme.get("media_errors"):
            state = "failing" if state == "failing" else "worn"
            notes.append(f"{nvme['media_errors']} errors reading or writing its own memory")
        used = nvme.get("percentage_used")
        if isinstance(used, int) and used >= 90:
            state = "failing" if state == "failing" else "worn"
            notes.append(f"{used}% of its designed life is used")
    table = (data.get("ata_smart_attributes") or {}).get("table") or []
    for row in table:
        what = ATA_DAMAGE.get(row.get("id"))
        count = (row.get("raw") or {}).get("value")
        if what and isinstance(count, int) and count > 0:
            state = "worn"
            notes.append(what.format(n=count))
    if passed is False:
        state = "failing"
        notes.insert(0, "the disk says it is about to fail")
    elif passed is None and not notes and not table and not isinstance(nvme, dict):
        # USB bridges and very old disks answer without a health record
        state = "unknown"
    return {"state": state, "detail": "; ".join(notes), "hours": hours if isinstance(hours, int) else None}


def _parse(text: str) -> dict | None:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def internal_disks(sys_block: str = "/sys/block") -> list[str]:
    """Whole disks built into the computer: sdX and nvmeXnY that are not
    removable and not on USB. A stick or an external disk is somebody's
    luggage, not this computer's health."""
    out = []
    for d in sorted(glob.glob(os.path.join(sys_block, "*"))):
        name = os.path.basename(d)
        if not (name.startswith("sd") or name.startswith("nvme") or name.startswith("mmcblk")):
            continue
        if name.startswith("mmcblk") and ("boot" in name or "rpmb" in name):
            continue
        if _read(os.path.join(d, "removable")) == "1":
            continue
        if "/usb" in os.path.realpath(d):
            continue
        out.append(name)
    return out


def read_disks(cache: str = DISK_CACHE, sys_block: str = "/sys/block") -> list[tuple[str, dict | None]]:
    """(disk name, smartctl answer or None) for every internal disk. As root
    the disk is asked now; otherwise the answer left at boot is read. mmc
    cards have no SMART record and always come back None."""
    out = []
    for name in internal_disks(sys_block):
        data = None
        if os.geteuid() == 0 and shutil.which("smartctl") and not name.startswith("mmcblk"):
            try:
                # the exit status is a set of flags about the disk, not a failure to run
                res = subprocess.run(["smartctl", "-j", "-H", "-A", f"/dev/{name}"],
                                     capture_output=True, text=True, timeout=30)
                data = _parse(res.stdout)
            except (OSError, subprocess.SubprocessError):
                data = None
        if data is None:
            data = _parse(_read(os.path.join(cache, f"{name}.json")) or "")
        out.append((name, data))
    return out
