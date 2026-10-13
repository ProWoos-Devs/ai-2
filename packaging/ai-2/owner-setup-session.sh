#!/bin/sh
# AI-2 owner setup session (ai2/owner.py). On a computer installed "for
# someone else", the login manager logs the temporary account into this
# session at the first boot: a window manager and one terminal running the
# owner setup as root (the sudo rule the install left allows exactly that
# command). When the setup is done the computer restarts. When the window is
# closed instead, the terminal is opened again: the login manager shows its
# greeter after an automatic session ends (seen 2026-10-13), and the temporary
# account has no password to log in with, so this session must not end while
# the owner is still owed.
#
# xfwm4 4.20 has no --daemon, so it is backgrounded. It draws the window frame
# when it is up; the terminal opens with a fixed readable geometry rather than
# --maximize, because on a cold first boot the window mapped before xfwm4 was
# managing and stayed small (seen 2026-10-13). 100x38 is the size the first-
# login setup window uses, and it needs no window manager to be right.
if command -v xfwm4 >/dev/null 2>&1; then
    xfwm4 >/dev/null 2>&1 &
fi
run="sudo -n /usr/bin/ai-2 owner-setup; printf '\n\nPress Enter to try again. '; read _"
while [ -e /etc/ai2/owner-setup-pending ]; do
    if command -v xfce4-terminal >/dev/null 2>&1; then
        xfce4-terminal --disable-server --geometry=100x38 --hide-menubar --title="AI-2" -x sh -c "$run"
    else
        xterm -T "AI-2" -geometry 100x38 -e sh -c "$run"
    fi
    sleep 1
done
