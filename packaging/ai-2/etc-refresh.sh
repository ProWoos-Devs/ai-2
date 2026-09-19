#!/bin/sh
# AI-2: bring /etc/motd and the greeter configuration up to date after an
# upgrade, without ever overwriting what somebody changed.
#
# Both files reach an installed machine from the ISO overlay, and both are
# also inside the ai-2 package (/usr/share/ai2/). Nothing copied them, so a
# machine that upgraded for months kept the login message and the greeter of
# the image it was installed from, while everything else moved on.
#
# The rule: replace /etc only when what is there is byte-for-byte a copy AI-2
# itself shipped at some point (etc-known.sha256, every version of those files
# that has been committed). A file that was edited, by the user or by anything
# else, matches nothing in that list; it is left exactly as it is and the new
# version is written beside it as FILE.ai2new, the way pacman does it.
set -e

KNOWN=/usr/share/ai2/etc-known.sha256
[ -f "$KNOWN" ] || exit 0

refresh() {
    src=$1
    dest=$2
    name=$3
    [ -f "$src" ] || return 0
    if [ ! -f "$dest" ]; then
        install -Dm644 "$src" "$dest"
        return 0
    fi
    have=$(sha256sum < "$dest" | cut -d' ' -f1)
    want=$(sha256sum < "$src" | cut -d' ' -f1)
    [ "$have" = "$want" ] && return 0
    if grep -q "^$have  $name\$" "$KNOWN"; then
        install -Dm644 "$src" "$dest"
        echo "AI-2: $dest brought up to date."
    else
        install -Dm644 "$src" "$dest.ai2new"
        echo "AI-2: $dest was changed on this computer, so it is kept; the new version is $dest.ai2new"
    fi
}

refresh /usr/share/ai2/motd /etc/motd motd
refresh /usr/share/ai2/lightdm-gtk-greeter.conf \
        /etc/lightdm/lightdm-gtk-greeter.conf lightdm-gtk-greeter.conf
