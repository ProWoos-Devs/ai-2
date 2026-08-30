#!/bin/sh
# AI-2: keep pamac's own update tray out of the session.
#
# AI-2 already tells the user about updates: `ai-2 update-check`, autostarted
# once a day, raises a bubble that carries a button opening pamac on its
# updates page, mirrors itself to speech when a screen reader is running, and
# leaves a one-line hint in login shells. pamac-tray would be a second
# notifier and a permanent GTK process on machines with 2 GB of RAM, so its
# autostart entry is hidden here.
#
# The file belongs to the pamac package, so a pamac upgrade restores it; that
# is why this runs from a pacman hook after every pamac install or upgrade.
# To get the tray back, remove the Hidden line and the hook
# (/usr/share/libalpm/hooks/zz-ai2-pamac.hook).
set -e

for f in /etc/xdg/autostart/pamac-tray.desktop \
         /etc/xdg/autostart/pamac-tray-budgie.desktop; do
    [ -f "$f" ] || continue
    grep -q '^Hidden=true' "$f" && continue
    awk '{ print }
         /^\[Desktop Entry\]$/ && !done {
             print "# AI-2: AI-2 has its own update notification (ai-2 update-check)."
             print "Hidden=true"
             done = 1
         }' "$f" > "$f.ai2new" && mv "$f.ai2new" "$f"
done
