#!/bin/sh
# AI-2 processor guard. Old laptops with tired cooling climb past 90 °C under
# AI work (the 2011 HP reached 94 in 8 minutes, 1 degree under the point where
# its firmware steps in). This watches the processor's temperature and, when
# it reaches the ceiling, lowers the top speed one step: first the boost, then
# the top frequency, down to half of it. When the processor has cooled it goes
# back up the same way. A computer that cools well never reaches the ceiling
# and loses nothing.
#
# Run as root by the ai2-boot service, after the boot-time tuning. It only
# writes /sys (the boost switch and scaling_max_freq), so nothing survives a
# reboot, and on TERM it puts back what it found. /etc/ai2/cpu-guard.conf may
# hold "ceiling = 80" (50 to 100) or "ceiling = off".
#
# --once does one reading and one step, for the tests.
SYS=${AI2_SYS:-/sys}
RUN=${AI2_RUN:-/run/ai2}/cpu-guard
CONF=${AI2_CONF:-/etc/ai2/cpu-guard.conf}
TICK=5        # seconds between readings
HOLD=30       # seconds to let a step show before the next one
RELEASE=6     # degrees under the ceiling before going back up
ONCE=0
[ "$1" = "--once" ] && ONCE=1

BOOST=$SYS/devices/system/cpu/cpufreq/boost
NOTURBO=$SYS/devices/system/cpu/intel_pstate/no_turbo

rd() { R=; [ -r "$1" ] && read -r R < "$1" 2>/dev/null; }
put() { [ -w "$1" ] && printf '%s\n' "$2" > "$1" 2>/dev/null; }
isnum() { case $1 in ''|*[!0-9]*) return 1 ;; esac; return 0; }

park() {
    [ "$ONCE" = 1 ] && exit 0
    command -v pause >/dev/null 2>&1 && exec pause
    exec sleep infinity
}

# The drivers that report the processor itself, best first (as ai2/health.py).
find_sensor() {
    for want in coretemp k10temp zenpower cpu_thermal acpitz; do
        for d in "$SYS"/class/hwmon/hwmon*; do
            rd "$d/name"
            if [ "$R" = "$want" ]; then SENSOR=$d; SNAME=$want; return 0; fi
        done
    done
    return 1
}

# T: the hottest reading in whole degrees, 0 when nothing could be read
temp() {
    T=0
    for f in "$SENSOR"/temp*_input; do
        rd "$f"
        isnum "$R" || continue
        [ "$R" -gt "$T" ] && T=$R
    done
    T=$((T / 1000))
}

boost_state() {
    rd "$BOOST"
    if [ "$R" = 1 ]; then B=on; return; fi
    if [ "$R" = 0 ]; then B=off; return; fi
    rd "$NOTURBO"
    if [ "$R" = 0 ]; then B=on; return; fi
    if [ "$R" = 1 ]; then B=off; return; fi
    B=none
}

set_boost() {   # on | off
    if [ -e "$BOOST" ]; then
        [ "$1" = on ] && put "$BOOST" 1 || put "$BOOST" 0
    elif [ -e "$NOTURBO" ]; then
        [ "$1" = on ] && put "$NOTURBO" 0 || put "$NOTURBO" 1
    fi
}

policies() { for p in "$SYS"/devices/system/cpu/cpufreq/policy*; do [ -w "$p/scaling_max_freq" ] && echo "$p"; done; }

# N: the next frequency under $2 for policy $1, never under half of its top $3
lower() {
    floor=$(($3 / 2))
    rd "$1/scaling_available_frequencies"
    N=$2
    if [ -n "$R" ]; then
        best=0
        for f in $R; do
            isnum "$f" || continue
            [ "$f" -lt "$2" ] && [ "$f" -ge "$floor" ] && [ "$f" -gt "$best" ] && best=$f
        done
        [ "$best" -gt 0 ] && N=$best
    else
        N=$(($2 - $3 / 10))
        [ "$N" -lt "$floor" ] && N=$floor
    fi
}

# N: the next frequency over $2 for policy $1, never over its top $3
higher() {
    rd "$1/scaling_available_frequencies"
    N=$3
    if [ -n "$R" ]; then
        for f in $R; do
            isnum "$f" || continue
            [ "$f" -gt "$2" ] && [ "$f" -lt "$N" ] && N=$f
        done
    else
        N=$(($2 + $3 / 10))
        [ "$N" -gt "$3" ] && N=$3
    fi
}

top_of() { rd "$RUN/top.${1##*/}"; }

step_down() {   # returns 0 when something changed
    boost_state
    if [ "$B" = on ]; then set_boost off; return 0; fi
    changed=1
    for p in $POLICIES; do
        top_of "$p"; top=$R
        rd "$p/scaling_max_freq"; cur=$R
        isnum "$top" && isnum "$cur" || continue
        lower "$p" "$cur" "$top"
        if [ "$N" -lt "$cur" ]; then put "$p/scaling_max_freq" "$N"; changed=0; fi
    done
    return $changed
}

step_up() {     # returns 0 when something changed
    raised=1
    for p in $POLICIES; do
        top_of "$p"; top=$R
        rd "$p/scaling_max_freq"; cur=$R
        isnum "$top" && isnum "$cur" || continue
        [ "$cur" -lt "$top" ] || continue
        higher "$p" "$cur" "$top"
        put "$p/scaling_max_freq" "$N"
        # with the boost off some drivers will not go all the way to the top
        rd "$p/scaling_max_freq"
        isnum "$R" && [ "$R" -gt "$cur" ] && raised=0
    done
    [ "$raised" = 0 ] && return 0
    rd "$RUN/boost"; was=$R
    boost_state
    if [ "$was" = on ] && [ "$B" = off ]; then
        set_boost on
        for p in $POLICIES; do top_of "$p"; isnum "$R" && put "$p/scaling_max_freq" "$R"; done
        return 0
    fi
    return 1
}

restore() {
    rd "$RUN/boost"
    [ "$R" = on ] && set_boost on
    for p in $POLICIES; do top_of "$p"; isnum "$R" && put "$p/scaling_max_freq" "$R"; done
    rm -rf "$RUN"
}

# What `ai-2 doctor` reads: is the processor being held, and at what.
status() {
    boost_state
    held=0; low=
    rd "$RUN/boost"; [ "$R" = on ] && [ "$B" = off ] && held=1
    for p in $POLICIES; do
        top_of "$p"; top=$R
        rd "$p/scaling_max_freq"; cur=$R
        isnum "$top" && isnum "$cur" || continue
        [ "$cur" -lt "$top" ] && held=1
        { [ -z "$low" ] || [ "$cur" -lt "$low" ]; } && low=$cur
    done
    printf 'ceiling=%s\nsensor=%s\nheld=%s\nboost=%s\nmax_khz=%s\n' \
        "$CEILING" "$SNAME" "$held" "$B" "$low" > "$RUN/status.new" 2>/dev/null
    chmod 644 "$RUN/status.new" 2>/dev/null
    mv -f "$RUN/status.new" "$RUN/status" 2>/dev/null
    [ "$ONCE" = 1 ] || ! command -v logger >/dev/null 2>&1 ||
        logger -t ai2-cpu-guard "processor at $T °C (ceiling $CEILING): boost $B, top speed ${low:-?} kHz"
}

# --- the ceiling
CEILING=85
if [ -r "$CONF" ]; then
    want=$(sed -n 's/^ceiling *= *//p' "$CONF" | head -1)
    [ "$want" = off ] && park
    isnum "$want" && [ "$want" -ge 50 ] && [ "$want" -le 100 ] && CEILING=$want
fi
# stay 5 degrees under the point where the firmware itself slows the processor
for t in "$SYS"/class/thermal/thermal_zone*/trip_point_*_type; do
    rd "$t"
    [ "$R" = passive ] || continue
    rd "${t%_type}_temp"
    isnum "$R" && [ "$R" -gt 0 ] || continue
    [ $((R / 1000 - 5)) -lt "$CEILING" ] && CEILING=$((R / 1000 - 5))
done

find_sensor || park
POLICIES=$(policies)
boost_state
[ -z "$POLICIES" ] && [ "$B" = none ] && park

# Remember what was found, once: a restart must not take a lowered speed for
# the top one. /run is memory, so every boot starts clean.
if [ ! -d "$RUN" ]; then
    mkdir -p "$RUN" 2>/dev/null || park
    chmod 755 "${RUN%/*}" "$RUN" 2>/dev/null
    printf '%s\n' "$B" > "$RUN/boost"
    for p in $POLICIES; do
        rd "$p/scaling_max_freq"
        isnum "$R" && printf '%s\n' "$R" > "$RUN/top.${p##*/}"
    done
    T=0; status
fi

tick() {   # returns 0 when a step was made
    temp
    [ "$T" -gt 0 ] || return 1
    if [ "$T" -ge "$CEILING" ]; then
        step_down && { status; return 0; }
    elif [ "$T" -le $((CEILING - RELEASE)) ]; then
        step_up && { status; return 0; }
    fi
    return 1
}

if [ "$ONCE" = 1 ]; then tick; exit 0; fi

trap 'restore; exit 0' TERM INT HUP
while :; do
    if tick; then wait_s=$HOLD; else wait_s=$TICK; fi
    sleep "$wait_s" &
    wait $!
done
