"""The Broadcom wl trap, and the way through it for installed systems.

AI-2 ISOs up to 20260830 install `broadcom-wl` (the proprietary driver for
BCM43xx WiFi, common in 2008-2012 laptops). Artix now ships
`broadcom-wl-dkms` with `Replaces: broadcom-wl`, and libalpm looks for a
replacer BEFORE it looks for the package itself (sync.c, alpm_sync_sysupgrade),
so every such install swaps to the dkms package at its next `-Syu` whether or
not the machine has Broadcom hardware. The swap pulls dkms, gcc, make and
friends (292 MiB) and then fails to build the module because the kernel
headers (310 MiB more) are not installed. Seen on rafaminu-pc 2026-09-03.

What this module does, before `ai-2 update` runs pacman and in `ai-2 doctor`:
no Broadcom WiFi device, the wl packages go (there is nothing for them to
drive); a Broadcom device, the kernel headers join the upgrade so the dkms
build succeeds. It cannot intercept a plain `pacman -Syu` or pamac, and the
ai-2 package carrying it arrives in the same transaction as the swap, so an
existing install's FIRST update still swaps; the next `ai-2 update` or doctor
then cleans up. Bounded, and said out loud in the changelog."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field

WL_PACKAGES = ("broadcom-wl", "broadcom-wl-dkms")
KERNELS = ("linux", "linux-lts", "linux-zen", "linux-hardened")
BROADCOM_VENDOR = "14e4"


@dataclass
class Plan:
    state: str                       # clean, remove-wl, remove-dkms, needs-headers, ok-broadcom, wl-missing
    pre_commands: list[list[str]] = field(default_factory=list)   # run BEFORE pacman -Syu (no sudo prefix)
    extra_packages: list[str] = field(default_factory=list)       # added to the -Syu
    message: str = ""                # what and why, for update
    fix: str = ""                    # the doctor's one-line remedy


def broadcom_wifi_devices(lspci_output: str) -> list[str]:
    """Broadcom devices of PCI class Network controller [0280] in `lspci -nn`
    output. Broadcom Ethernet chips (class 0200) use in-kernel drivers and
    are of no interest to wl."""
    found = []
    for line in lspci_output.splitlines():
        if "Network controller [0280]" in line and f"[{BROADCOM_VENDOR}:" in line:
            found.append(line.split(":", 2)[-1].strip())
    return found


def _probe_lspci(run=subprocess.run) -> str:
    if not shutil.which("lspci"):
        return ""
    try:
        return run(["lspci", "-nn"], capture_output=True, text=True, timeout=10).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def installed(names: tuple[str, ...] | list[str], run=subprocess.run) -> dict[str, bool]:
    if not shutil.which("pacman"):
        return {n: False for n in names}
    out = {}
    for n in names:
        try:
            out[n] = run(["pacman", "-Q", n], capture_output=True, text=True, timeout=10).returncode == 0
        except (OSError, subprocess.SubprocessError):
            out[n] = False
    return out


def headers_package(run=subprocess.run) -> str:
    """The headers package for the installed kernel (linux -> linux-headers,
    linux-lts -> linux-lts-headers); linux-headers when nothing is found."""
    have = installed(KERNELS, run=run)
    kernel = next((k for k in KERNELS if have.get(k)), "linux")
    return f"{kernel}-headers"


def assess(devices: list[str], have: dict[str, bool], headers: str) -> Plan:
    wl, dkms, hdr = have.get("broadcom-wl", False), have.get("broadcom-wl-dkms", False), have.get(headers, False)
    if not devices:
        if dkms:
            return Plan("remove-dkms", pre_commands=[["pacman", "-Rns", "--noconfirm", "broadcom-wl-dkms"]],
                        message="broadcom-wl-dkms and its build tools are installed, but this computer has no "
                                "Broadcom WiFi; removing them first (they were pulled in by a package replacement).",
                        fix="sudo pacman -Rns broadcom-wl-dkms   (no Broadcom WiFi here; ai-2 update does this)")
        if wl:
            return Plan("remove-wl", pre_commands=[["pacman", "-Rns", "--noconfirm", "broadcom-wl"]],
                        message="broadcom-wl is installed, but this computer has no Broadcom WiFi; removing it "
                                "first, otherwise the update swaps it for broadcom-wl-dkms and 600 MB of build tools.",
                        fix="sudo pacman -Rns broadcom-wl   (no Broadcom WiFi here; ai-2 update does this)")
        return Plan("clean")
    # Broadcom WiFi present
    if not wl and not dkms:
        return Plan("wl-missing",
                    message=f"Broadcom WiFi found ({devices[0]}) and no wl driver installed.",
                    fix=f"sudo pacman -S --needed broadcom-wl-dkms {headers}   (if WiFi does not work)")
    if not hdr:
        return Plan("needs-headers", extra_packages=[headers],
                    message=f"Broadcom WiFi found ({devices[0]}); adding {headers} to the update so the "
                            "wl driver (broadcom-wl-dkms) can build for this kernel.",
                    fix=f"sudo pacman -S --needed {headers}   (the wl driver cannot build without it)")
    return Plan("ok-broadcom", message=f"Broadcom WiFi found ({devices[0]}); wl driver and {headers} present.")


def current_plan(run=subprocess.run) -> Plan:
    headers = headers_package(run=run)
    have = installed((*WL_PACKAGES, headers), run=run)
    return assess(broadcom_wifi_devices(_probe_lspci(run=run)), have, headers)


def preflight(say, run, sudo: list[str], plan: Plan | None = None) -> list[str] | None:
    """Run the plan's pre-commands (through `run`, with the sudo prefix) and
    return the packages to add to the upgrade; None when a pre-command failed
    and the update should not go on."""
    plan = plan or current_plan()
    if plan.message and plan.state not in ("ok-broadcom", "wl-missing"):
        say(plan.message)
    for cmd in plan.pre_commands:
        full = sudo + cmd
        say("Running:  " + " ".join(full))
        try:
            rc = run(full).returncode
        except OSError as exc:
            say(f"Could not run pacman: {exc}")
            return None
        if rc != 0:
            say(f"pacman stopped with an error (code {rc}); not continuing with the update.")
            return None
    return list(plan.extra_packages)
