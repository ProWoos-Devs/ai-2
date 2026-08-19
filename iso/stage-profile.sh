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

# Compose root-overlay: the stock xfce profile symlinks these into artools'
# common overlays and our copied profile lost the links (found 2026-08-18 when
# an installed system had no Windows entry and no GRUB theme):
#   common/root-overlay/etc/default/grub  -> GRUB_THEME artix (= our AI-2 theme
#                                            files), GRUB_DISABLE_OS_PROBER=false,
#                                            GRUB_GFXMODE 1024x768 (Calamares'
#                                            grubcfg keeps an existing file's
#                                            values, so this is what installs get)
#   common/gtk/root-overlay/usr           -> GTK2 defaults (Artix-dark, Roboto)
# NOT taken: common hosts/issue/pacman.conf (ours or the package's are right).
COMMON=/root/artools-workspace/iso-profiles/common
mkdir -p "$DST/root-overlay/etc/default"
cp -aL "$COMMON/root-overlay/etc/default/." "$DST/root-overlay/etc/default/"
cp -aL "$COMMON/gtk/root-overlay/usr/." "$DST/root-overlay/usr/"
cp -a "$SRC/iso/profiles/ai2/root-overlay/." "$DST/root-overlay/"

chmod 755 "$DST/root-overlay/usr/bin/artix-service" "$DST/live-overlay/usr/bin/ai2-install" "$DST/live-overlay/usr/bin/desktop-items" "$DST/live-overlay/usr/share/ai2/label-root.sh"

# The ai-2 tool + llama.cpp runtimes come from the signed [ai2] repo now
# (profile.yaml lists them). buildiso must be run with -w so this pacman.conf,
# with [ai2], is copied into the rootfs and therefore into installed systems.
mkdir -p "$HOME/.config/artools/pacman.conf.d"
cp "$SRC/iso/pacman.conf.d/iso-x86_64.conf" "$HOME/.config/artools/pacman.conf.d/iso-x86_64.conf"

# basestrap copies the build host's pacman keyring into the rootfs, so the
# AI-2 signing key must be trusted here (idempotent).
if ! pacman-key --list-keys F1889E37B4E5FEC8 >/dev/null 2>&1; then
  pacman-key --add "$SRC/packaging/ai2-keyring/ai2-package-signing.asc"
  pacman-key --lsign-key F1889E37B4E5FEC8
fi

echo "Staged $(find "$DST" -type f | wc -l) files into $DST"
