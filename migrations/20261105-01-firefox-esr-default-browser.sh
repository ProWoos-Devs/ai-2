# Make Firefox ESR this account's web browser, unless the account already chose one.
#
# Xfce asks helpers.rc, and other programs ask mimeapps.list. Until now both
# were left to the system, so a browser named in either file is somebody's own
# choice and stays, Epiphany included (Rafael, 2026-11-05). This never touches
# a line it did not write. Without Firefox ESR there is nothing to point at.
command -v firefox-esr >/dev/null 2>&1 || exit 0
config=${XDG_CONFIG_HOME:-$HOME/.config}
changed=

helpers=$config/xfce4/helpers.rc
if ! { [[ -f "$helpers" ]] && grep -q '^WebBrowser=' "$helpers"; }; then
    mkdir -p "$config/xfce4"
    echo 'WebBrowser=firefox-esr' >> "$helpers"
    changed=1
fi

mime=$config/mimeapps.list
mkdir -p "$config"
[[ -f "$mime" ]] || : > "$mime"
wanted=()
for type in x-scheme-handler/http x-scheme-handler/https text/html; do
    grep -q "^$type=" "$mime" || wanted+=("$type=firefox-esr.desktop")
done
if ((${#wanted[@]})); then
    new=$(mktemp "$mime.XXXXXX")
    placed=
    while IFS= read -r line || [[ -n "$line" ]]; do
        printf '%s\n' "$line" >> "$new"
        if [[ -z "$placed" && "$line" == '[Default Applications]' ]]; then
            printf '%s\n' "${wanted[@]}" >> "$new"
            placed=1
        fi
    done < "$mime"
    if [[ -z "$placed" ]]; then
        { echo '[Default Applications]'; printf '%s\n' "${wanted[@]}"; } >> "$new"
    fi
    mv "$new" "$mime"
    changed=1
fi

if [[ -n "$changed" ]]; then
    echo "Firefox ESR is now the web browser; Settings > Default Applications changes it"
fi
