#!/bin/sh
# AI-2 owner setup session (ai2/owner.py). On a computer installed "for
# someone else", the login manager logs the temporary account into this
# session at the first boot: a window manager and one maximized terminal
# running the owner setup as root (the sudo rule the install left allows
# exactly that command). When the setup is done the computer restarts; when
# the window is closed instead, the session ends and the login manager starts
# it again, so the question cannot be lost.
command -v xfwm4 >/dev/null 2>&1 && xfwm4 --daemon 2>/dev/null
run="sudo -n /usr/bin/ai-2 owner-setup; printf '\n\nPress Enter to try again. '; read _"
if command -v xfce4-terminal >/dev/null 2>&1; then
    exec xfce4-terminal --disable-server --maximize --hide-menubar --title="AI-2" -x sh -c "$run"
else
    exec xterm -T "AI-2" -geometry 100x38 -e sh -c "$run"
fi
