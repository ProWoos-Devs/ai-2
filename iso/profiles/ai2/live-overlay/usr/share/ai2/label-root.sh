#!/bin/sh
# AI-2 installer job: give the freshly installed root filesystem the label
# "AI-2" so partition views (a later reinstall, another OS, gparted) show a
# name instead of "sdaN". Called by Calamares (shellprocess@label, outside
# the chroot) as:  label-root.sh <target-root-mountpoint>
# Only ext2/3/4, btrfs and xfs are labeled; anything else is left alone.
# Never fails the installation: a missing label is cosmetic.
root="$1"
[ -n "$root" ] && [ -f "$root/etc/fstab" ] || exit 0
src=$(awk '$2=="/" && $1!~/^#/ {print $1; exit}' "$root/etc/fstab")
fs=$(awk '$2=="/" && $1!~/^#/ {print $3; exit}' "$root/etc/fstab")
case "$src" in
    UUID=*) dev=/dev/disk/by-uuid/${src#UUID=} ;;
    /dev/*) dev=$src ;;
    *) exit 0 ;;
esac
[ -e "$dev" ] || exit 0
case "$fs" in
    ext2|ext3|ext4) e2label "$dev" AI-2 || true ;;
    btrfs) btrfs filesystem label "$dev" AI-2 || true ;;
    xfs) xfs_admin -L AI-2 "$dev" || true ;;
esac
exit 0
