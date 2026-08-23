#!/bin/sh
# AI-2: after install, remove the two llama.cpp engine builds this CPU cannot
# use. The ISO ships all three (baseline+noavx+avx2) so an offline install has
# the right one; only one ever runs on a given machine. Runs in the target
# chroot (install happens on the target hardware, so /proc/cpuinfo is real).
# Best-effort: never fails the install.
V=$(ai-2 detect --json 2>/dev/null | sed -n 's/.*"cpu_variant" *: *"\([a-z0-9]*\)".*/\1/p')
[ -n "$V" ] || exit 0
DROP=""
for v in baseline noavx avx2; do
    [ "$v" = "$V" ] || DROP="$DROP ai2-llama-cpp-$v"
done
[ -n "$DROP" ] && pacman -R --noconfirm $DROP 2>/dev/null
exit 0
