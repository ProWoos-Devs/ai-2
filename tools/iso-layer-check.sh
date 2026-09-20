#!/bin/bash
# What is actually inside an AI-2 ISO, checked against what should be.
#
# Every image is built from layers (the artools profile, the root overlay, the
# live overlay, the packages) and the failures that got through were always the
# same shape: a file that is right in git and wrong in the image. Three stale
# copies of START-HERE.txt hid every edit for two weeks; a test image once
# carried the candidate package repository into /etc/pacman.conf, which would
# have pointed installed machines at an unsigned repo. Both were found by hand
# greps that lived in a memory file. This is those greps, committed.
#
# Usage:  sudo tools/iso-layer-check.sh path/to.iso [expected-ai-2-version]
# Needs: mount (root), unsquashfs. Prints one line per check; exits non-zero
# if any failed.
set -uo pipefail

ISO=${1:-}
WANT_VERSION=${2:-}
SRC=$(cd "$(dirname "$0")/.." && pwd)
[ -f "$ISO" ] || { echo "usage: $0 path/to.iso [expected-ai-2-version]"; exit 2; }
command -v unsquashfs >/dev/null || { echo "unsquashfs is not installed (squashfs-tools)"; exit 2; }

WORK=$(mktemp -d)
MNT="$WORK/iso"
mkdir -p "$MNT"
cleanup() { umount "$MNT" 2>/dev/null; rm -rf "$WORK"; }
trap cleanup EXIT

mount -o loop,ro "$ISO" "$MNT" || { echo "could not mount $ISO (run with sudo)"; exit 2; }

fails=0
ok()   { echo "  ok    $1"; }
bad()  { echo "  FAIL  $1"; fails=$((fails + 1)); }

# The installed system's files live in the squashfs; LiveOS/rootfs.img is the
# name artools gives it (not squashfs.img, learned 2026-08-14).
ROOTFS=$(find "$MNT" -name "rootfs.img" | head -1)
[ -n "$ROOTFS" ] || { echo "no rootfs.img in the image"; exit 2; }
EXTRACT="$WORK/rootfs"
# /etc/os-release is a symlink into /usr/lib on Artix, so both are taken; the
# tool's own file is found in the listing because where it lands is the
# PKGBUILD's business (/usr/lib/ai2/ai2/__init__.py today).
INIT=$(unsquashfs -l "$ROOTFS" 2>/dev/null |
       sed -n 's|^squashfs-root/\(.*/ai2/__init__.py\)$|\1|p' | head -1)
unsquashfs -q -f -d "$EXTRACT" "$ROOTFS" \
    etc/pacman.conf etc/motd etc/os-release usr/lib/os-release \
    usr/share/ai2/doc ${INIT:+"$INIT"} >/dev/null 2>&1

# 1. No candidate repository on an installed system. A test image builds one
#    to install an unsigned package; it must never reach the root overlay.
if grep -q 'ai2-candidate' "$EXTRACT/etc/pacman.conf" 2>/dev/null; then
    bad "/etc/pacman.conf points at the candidate repository"
else
    ok "no candidate repository in /etc/pacman.conf"
fi

# 2. The login message is the one in git, not a copy that stopped being updated.
if cmp -s "$EXTRACT/etc/motd" "$SRC/branding/motd"; then
    ok "/etc/motd is branding/motd"
else
    bad "/etc/motd differs from branding/motd"
fi

# 3. No invented OS version (it said 0.1 on every image up to 0.18).
OSREL="$EXTRACT/etc/os-release"
[ -s "$OSREL" ] || OSREL="$EXTRACT/usr/lib/os-release"
if [ ! -s "$OSREL" ]; then
    bad "no os-release in the image"
elif grep -q '^VERSION_ID' "$OSREL"; then
    bad "os-release carries a VERSION_ID ($(grep '^VERSION_ID' "$OSREL"))"
else
    ok "os-release states no OS version"
fi

# 4. The packs the image ships are there, each with its manifest and the
#    record that says where it came from (without it a fresh install says
#    "unknown source"). They are packages now, under /usr/share/ai2/doc.
SKEL="$EXTRACT/usr/share/ai2/doc"
packs=0
missing=0
for d in "$SKEL"/*/; do
    [ -d "$d" ] || continue
    packs=$((packs + 1))
    { [ -f "$d/origin.yml" ] && [ -f "$d/manifest.yml" ] && [ -f "$d/index.sqlite" ]; } \
        || missing=$((missing + 1))
done
if [ "$packs" -gt 0 ] && [ "$missing" = 0 ]; then
    ok "$packs knowledge pack(s) in /usr/share/ai2/doc, each complete"
else
    bad "knowledge packs in /usr/share/ai2/doc: $packs found, $missing incomplete"
fi

# 5. The ai-2 version on the image, when the caller says which one to expect.
got=""
[ -n "$INIT" ] && got=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$EXTRACT/$INIT" 2>/dev/null | head -1)
if [ -z "$WANT_VERSION" ]; then
    echo "        ai-2 on the image: ${got:-unknown}"
elif [ "$got" = "$WANT_VERSION" ]; then
    ok "ai-2 $got is on the image"
else
    bad "ai-2 on the image is ${got:-unknown}, expected $WANT_VERSION"
fi

echo
if [ "$fails" = 0 ]; then
    echo "Layer check passed."
else
    echo "Layer check: $fails problem(s)."
fi
exit $((fails > 0))
