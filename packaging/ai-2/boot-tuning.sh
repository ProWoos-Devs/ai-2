#!/bin/sh
# AI-2 boot-time memory tuning. Applies what /etc/ai2/memory.conf asks for:
# settings that live in sysfs and do not survive a reboot (zswap parameters,
# MGLRU anti-thrashing). Written by `ai-2 init --apply`, run at boot by the
# ai2-boot service (runit) or ai2-boot.service (systemd), and once directly
# when the plan is applied. Idempotent; every step is optional.
CONF=/etc/ai2/memory.conf
[ -r "$CONF" ] || exit 0

get() { sed -n "s/^$1 *= *//p" "$CONF" | head -1; }
put() { [ -w "$1" ] && printf '%s\n' "$2" > "$1" 2>/dev/null; }

mechanism=$(get mechanism)
if [ "$mechanism" = "zswap" ] && [ -d /sys/module/zswap/parameters ]; then
    # zswap compresses pages on their way to a real swap device; without one
    # (no swap partition/file) it has nothing to do, which is harmless.
    put /sys/module/zswap/parameters/compressor "$(get compressor)"
    put /sys/module/zswap/parameters/zpool "$(get zpool)"
    put /sys/module/zswap/parameters/enabled 1
fi

ttl=$(get mglru_min_ttl_ms)
if [ -n "$ttl" ] && [ -d /sys/kernel/mm/lru_gen ]; then
    # Multi-Gen LRU: min_ttl_ms keeps the working set resident for at least
    # this long instead of thrashing (docs.kernel.org multigen_lru, ~1000 ms
    # "eliminates intolerable janks"). Needs CONFIG_LRU_GEN in the kernel.
    put /sys/kernel/mm/lru_gen/enabled y
    put /sys/kernel/mm/lru_gen/min_ttl_ms "$ttl"
fi
exit 0
