#!/bin/sh
# AI-2 installer job: put the Broadcom wl WiFi driver into the freshly
# installed system, but only on a machine that has Broadcom WiFi.
#
# Why here and not in the installed package set: Artix's broadcom-wl-dkms
# declares Replaces: broadcom-wl, so an installed broadcom-wl is swapped for
# the dkms package at the first -Syu, dragging in ~600 MiB of build tools and
# kernel headers. Machines without the hardware must never carry it; machines
# with it need WiFi at first boot, before any download is possible. So the
# stick keeps the prebuilt package file (staged by stage-profile.sh) and this
# job installs it into the target when, and only when, a Broadcom WiFi device
# is present. ai-2 update (0.12.0+) then carries the machine over to the dkms
# driver with the headers it needs.
#
# Called by Calamares (shellprocess@broadcom, outside the chroot) as:
#   broadcom-install.sh <target-root-mountpoint>
# Never fails the installation: without WiFi the system still installs, and
# `ai-2 install broadcom-wifi` remains as the manual path.
# Testing without Broadcom hardware: touch /run/ai2-force-broadcom on the
# live system before installing.
root="$1"
[ -n "$root" ] && [ -d "$root/usr/lib/modules" ] || exit 0

has_broadcom_wifi() {
    [ -e /run/ai2-force-broadcom ] && return 0
    for d in /sys/bus/pci/devices/*; do
        [ -r "$d/class" ] || continue
        # class 0x028000 = Network controller (wireless); vendor 0x14e4 = Broadcom
        if [ "$(cat "$d/class")" = "0x028000" ] && [ "$(cat "$d/vendor")" = "0x14e4" ]; then
            return 0
        fi
    done
    return 1
}

has_broadcom_wifi || { echo "AI-2: no Broadcom WiFi, wl driver not installed"; exit 0; }

pkg=$(ls /usr/share/ai2/pkgs/broadcom-wl-*.pkg.tar.* 2>/dev/null | grep -v '\.sig$' | head -1)
if [ -z "$pkg" ]; then
    echo "AI-2: Broadcom WiFi found but no broadcom-wl package on this medium; install later with: ai-2 install broadcom-wifi" >&2
    exit 0
fi
echo "AI-2: Broadcom WiFi found, installing $(basename "$pkg") into the new system"
mkdir -p "$root/tmp/ai2-broadcom"
cp "$pkg" "$root/tmp/ai2-broadcom/"
[ -f "$pkg.sig" ] && cp "$pkg.sig" "$root/tmp/ai2-broadcom/"
if chroot "$root" pacman -U --noconfirm "/tmp/ai2-broadcom/$(basename "$pkg")"; then
    kver=$(ls "$root/usr/lib/modules" | head -1)
    if ls "$root/usr/lib/modules/$kver/extramodules/wl.ko"* >/dev/null 2>&1; then
        echo "AI-2: wl driver installed for kernel $kver"
    else
        echo "AI-2: broadcom-wl installed but no wl module for kernel $kver (package built for another kernel); ai-2 update will move to the dkms driver" >&2
    fi
else
    echo "AI-2: pacman -U broadcom-wl failed; install later with: ai-2 install broadcom-wifi" >&2
fi
rm -rf "$root/tmp/ai2-broadcom"
exit 0
