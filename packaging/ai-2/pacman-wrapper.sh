#!/bin/sh
# AI-2: a word before a system upgrade typed by hand, only when it matters.
#
# `ai-2 update` (and Software Updates) is how AI-2 keeps a machine current. It
# runs this same `pacman -Syu`, and before it the Broadcom preflight
# (ai2/broadcom.py): a machine with the broadcom-wl package and no Broadcom
# WiFi gets it removed first, because libalpm swaps broadcom-wl for the dkms
# build at every upgrade and that build needs the kernel headers; a machine
# that does have the chip gets the headers added to the upgrade. A plain
# `sudo pacman -Syu` skips that and can leave the WiFi driver unbuilt.
#
# Installed as /usr/local/bin/pacman, ahead of /usr/bin in PATH and in sudo's
# secure_path (the same placement as the reboot wrapper). For everything
# except a system upgrade on a terminal, this is /usr/bin/pacman: scripts,
# pamac (libalpm, never this file), queries, installs and removals go
# straight through, and so does an upgrade with no terminal to ask on.
# On a machine without a Broadcom driver package the upgrade goes through
# silently too: nothing else `ai-2 update` does needs to happen before pacman,
# the per-user migrations run at the next login. The idea of guarding a
# direct upgrade is Omarchy's; the restraint is ours.
real=/usr/bin/pacman
sync=0; up=0
for a in "$@"; do
    case $a in
        --) break ;;
        --sync) sync=1 ;;
        --sysupgrade) up=1 ;;
        --*) ;;
        -*) case $a in *S*) sync=1 ;; esac
            case $a in *u*) up=1 ;; esac ;;
    esac
done
if [ "$sync$up" = 11 ] && [ -t 0 ] && [ -t 1 ]; then
    if "$real" -Qq broadcom-wl >/dev/null 2>&1 || "$real" -Qq broadcom-wl-dkms >/dev/null 2>&1; then
        echo "AI-2: this computer has a Broadcom WiFi driver package. A plain upgrade can"
        echo "leave that driver unbuilt; ai-2 update checks it first (or use Software Updates)."
        printf 'Upgrade with pacman directly anyway? [y/N] '
        read -r ans || ans=
        case $ans in
            y|Y|yes|YES|Yes) ;;
            *) echo "Nothing done. Run:  ai-2 update"; exit 1 ;;
        esac
    fi
fi
exec "$real" "$@"
