#!/bin/sh
# AI-2 owner setup session (ai2/owner.py). On a computer installed "for
# someone else", the login manager logs the temporary account into this
# session at the first boot: a window manager and one maximized terminal
# running the owner setup as root (the sudo rule the install left allows
# exactly that command). When the setup is done the computer restarts. When
# the window is closed instead, the terminal is opened again: the login
# manager shows its greeter after an automatic session ends (seen 2026-10-13),
# and the temporary account has no password to log in with, so this session
# must not end while the owner is still owed.
# xfwm4 4.20 has no --daemon any more; it goes to the background here and
# gets a moment so that the terminal's --maximize finds a window manager.
if command -v xfwm4 >/dev/null 2>&1; then
    xfwm4 >/dev/null 2>&1 &
    sleep 1
fi
run="sudo -n /usr/bin/ai-2 owner-setup; printf '\n\nPress Enter to try again. '; read _"
while [ -e /etc/ai2/owner-setup-pending ]; do
    if command -v xfce4-terminal >/dev/null 2>&1; then
        xfce4-terminal --disable-server --maximize --hide-menubar --title="AI-2" -x sh -c "$run"
    else
        xterm -T "AI-2" -geometry 100x38 -e sh -c "$run"
    fi
    sleep 1
done
