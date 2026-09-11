#!/bin/sh
# AI-2: make `reboot` work for the user sitting at the machine.
#
# Software Updates (pamac) offers a Restart button after updates that touch
# the kernel, drivers, Xorg, mesa or cryptsetup. The button runs plain
# `reboot` as the logged-in user and ignores the result. On systemd that asks
# logind; on Artix runit, /usr/bin/reboot is runit's halt, which only root may
# run ("init: fatal: unable to create /etc/runit/stopit: access denied"), so
# the button did nothing (reproduced in a VM on 2026-09-11).
#
# Installed as /usr/local/bin/reboot, which comes before /usr/bin in PATH.
# Root gets runit's reboot unchanged, with its options. Anyone else asks
# elogind, whose polkit defaults let the active local user restart without a
# password (org.freedesktop.login1.reboot, allow_active yes).
if [ "$(id -u)" -eq 0 ]; then
    exec /usr/bin/reboot "$@"
fi
if command -v loginctl >/dev/null 2>&1; then
    loginctl reboot && exit 0
fi
exec /usr/bin/reboot "$@"
