#!/bin/sh
# AI-2 disk health, read once at every boot by the ai2-boot service.
# smartctl needs root, and `ai-2 doctor` runs as an ordinary account, so root
# asks each built-in disk here and leaves the answers where anyone may read
# them (ai2/health.py). Only the health verdict and the attribute table are
# asked for (-H -A): that output carries no serial number. /run is memory, so
# nothing is written to the disk being asked and the record is fresh each boot.
command -v smartctl >/dev/null 2>&1 || exit 0
out=/run/ai2/disk-health
mkdir -p "$out" 2>/dev/null || exit 0
chmod 755 /run/ai2 "$out" 2>/dev/null
for dev in /sys/block/sd* /sys/block/nvme*n*; do
    [ -e "$dev" ] || continue
    name=${dev##*/}
    [ "$(cat "$dev/removable" 2>/dev/null)" = 1 ] && continue
    case "$(readlink -f "$dev")" in */usb*) continue ;; esac
    # smartctl's exit status is a set of flags about the disk, not an error
    timeout 30 smartctl -j -H -A "/dev/$name" > "$out/$name.json.new" 2>/dev/null
    if [ -s "$out/$name.json.new" ]; then
        chmod 644 "$out/$name.json.new"
        mv -f "$out/$name.json.new" "$out/$name.json"
    else
        rm -f "$out/$name.json.new"
    fi
done
exit 0
