AI-2 assigns every machine one of six capability tiers. The tier decides how the system is tuned and how the AI runtime behaves. Check yours with `ai-2 tier`, which also explains why.

## The six tiers

| Tier | Requires | Memory tuning | AI runtime |
|---|---|---|---|
| Tiny | 2 GB RAM, 1 core | zram (lz4 on pre-SSE4.1 CPUs, zstd otherwise), high swappiness | llama.cpp on demand, exits after 5 idle minutes |
| Light | 4 GB RAM, 2 cores | zram (zstd), high swappiness | llama.cpp on demand, exits after 10 idle minutes |
| Standard | 8 GB RAM, 2 cores | zswap (zstd) | llama.cpp, persistent service |
| Creator | 16 GB RAM, 4 cores | zswap (zstd) | llama.cpp, persistent service (CPU-only, like every tier today) |
| Studio | 32 GB RAM, 4 cores | same configuration as Creator | same as Creator |
| Workstation | 64 GB RAM, 8 cores | same configuration as Creator | same as Creator |

Assignment is simple, the highest tier whose RAM and core requirements the machine meets. A machine below every requirement still gets the smallest tier, AI-2 does not turn a computer away above its small floor (64-bit CPU, 2 GB of RAM, about 6 GB of disk).

## What the tier controls

`sudo ai-2 init --apply` applies the tier's configuration:

* Compressed swap in RAM, zram on the low-memory tiers, zswap with MGLRU tuning from Standard up.
* Out-of-memory protection with earlyoom on every tier.
* Kernel memory sysctls (swappiness and friends) matched to the mechanism.
* No idle suspend, so a long model download or generation is not cut off.
* On the small tiers, services an old machine does not need (for example cupsd, avahi-daemon, bluetoothd on Tiny) are kept off.
* Whether the AI engine runs on demand (started when you chat, exits when idle, so a 2-4 GB machine gets its RAM back) or as a persistent service.
* Default context sizes for the models the tier typically runs.

Everything is declarative, the tier definitions live in [`ai2/data/tiers/*.yml`](https://github.com/ProWoos-Devs/ai-2/tree/main/ai2/data/tiers).

## Tiers do not pick your model

RAM alone over-promises. Which model AI-2 recommends is gated by the measured [[AI Score|AI Score and Benchmarks]], not by the tier. A machine can have the RAM for a 7B model and still be steered to a smaller one because the measured speed says the big one would be unusable.
