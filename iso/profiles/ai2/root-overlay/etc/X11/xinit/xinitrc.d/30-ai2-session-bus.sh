#!/bin/sh
# AI-2: start the user's D-Bus session bus at $XDG_RUNTIME_DIR/bus, the path
# every desktop component (and WebKitGTK's sandbox, which proxies the session
# bus into the web process) expects. Without it, Artix's 80-dbus.sh falls back
# to dbus-launch, which puts the socket under /tmp; the sandbox cannot reach it,
# xdg-dbus-proxy dies and Epiphany's web process aborts on every page, so the
# AI-2 chat page stays blank (found on the 2011 laptop, 2026-08-23).
# Sourced by xfce's xinitrc before 80-dbus.sh, which then returns early.
rt="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [ -d "$rt" ] && [ ! -S "$rt/bus" ] && command -v dbus-daemon >/dev/null 2>&1; then
    dbus-daemon --session --address="unix:path=$rt/bus" --fork --nopidfile --nosyslog 2>/dev/null
fi
if [ -S "$rt/bus" ]; then
    DBUS_SESSION_BUS_ADDRESS="unix:path=$rt/bus"
    export DBUS_SESSION_BUS_ADDRESS
fi
