# AI-2: one-line update hint at login, fed by `ai-2 update-check` (autostarted
# in the desktop session). Reads only a local cache file; never hits the network.
case $- in *i*)
if [ -f "${XDG_STATE_HOME:-$HOME/.local/state}/ai2/updates.json" ]; then
    _ai2_upd="${XDG_STATE_HOME:-$HOME/.local/state}/ai2/updates.json"
    # skip when pacman ran after the check (count is stale) or the check is
    # older than 2 days (machine long offline; the autostart will refresh it)
    if [ ! /var/lib/pacman/local -nt "$_ai2_upd" ] && [ -n "$(find "$_ai2_upd" -mtime -2 2>/dev/null)" ]; then
        _ai2_n=$(sed -n 's/.*"count": *\([0-9][0-9]*\).*/\1/p' "$_ai2_upd" 2>/dev/null)
        if [ -n "$_ai2_n" ] && [ "$_ai2_n" -gt 0 ] 2>/dev/null; then
            echo "AI-2: $_ai2_n update(s) available. Update with:  sudo pacman -Syu"
        fi
        unset _ai2_n
    fi
    unset _ai2_upd
fi
;; esac
