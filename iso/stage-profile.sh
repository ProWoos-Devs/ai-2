#!/bin/bash
# Stage the AI-2 ISO profile into the artools workspace.
# Run INSIDE the build container (repo mounted at /ai2-repo):
#   docker exec ai2-iso-build bash /ai2-repo/www/ai-2/iso/stage-profile.sh
set -euo pipefail

SRC=/ai2-repo/www/ai-2
DST=/root/artools-workspace/iso-profiles/ai2

rm -rf "$DST"
cp -a "$SRC/iso/profiles/ai2" "$DST"

# Compose live-overlay: Artix common live config (calamares-offline/online,
# live polkit rules, sudoers, elogind conf) underneath the AI-2 overrides.
# -L dereferences common's internal symlinks into real files.
rm -rf "$DST/live-overlay"
cp -aL /root/artools-workspace/iso-profiles/common/live-overlay "$DST/live-overlay"
cp -a "$SRC/iso/profiles/ai2/live-overlay/." "$DST/live-overlay/"

# Ship the ai2 Python package at /usr/lib/ai2 (wrapper in root-overlay/usr/bin/ai-2)
mkdir -p "$DST/root-overlay/usr/lib/ai2"
cp -a "$SRC/ai2" "$DST/root-overlay/usr/lib/ai2/ai2"
find "$DST/root-overlay/usr/lib/ai2" -name __pycache__ -type d -exec rm -rf {} +
chmod 755 "$DST/root-overlay/usr/bin/ai-2" "$DST/root-overlay/usr/bin/artix-service"

echo "Staged $(find "$DST" -type f | wc -l) files into $DST"
