#!/bin/sh
# AI-2 crash record. The kernel runs this (as root) for every process that
# dies with a core-dumping signal, because 60-ai2-crashes.conf names it in
# kernel.core_pattern:  |/usr/lib/ai2/crash-handler %t %u %p %s %e %E
# It keeps NO core dump: it closes the dump's pipe at once and writes one line
# per crash, so a user can be told that something stopped unexpectedly and
# `ai-2 doctor` can say what to do about it (ai2/crashes.py reads the file).
# Nothing leaves the machine. runit has no systemd-coredump, which is what does
# this elsewhere; with a pipe here the core size limit (0 by default) does not
# stop the kernel from running the handler (fs/coredump.c, pipe path).
#
# Line format: <epoch> <uid> <pid> <signal> <comm> <path-with-!-for-/>
exec </dev/null
log=${AI2_CRASH_LOG:-/var/lib/ai2/crashes.log}
mkdir -p "$(dirname "$log")" 2>/dev/null || exit 0
printf '%s %s %s %s %s %s\n' "$1" "$2" "$3" "$4" "$5" "$6" >> "$log" 2>/dev/null || exit 0
chmod 644 "$log" 2>/dev/null
# A crash loop must not grow the file without end: over 500 lines, keep the newest 200.
if [ "$(wc -l < "$log")" -gt 500 ]; then
    tail -n 200 "$log" > "$log.new" 2>/dev/null && mv -f "$log.new" "$log"
fi
exit 0
