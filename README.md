# AI-2

**Give your computer an AI brain.**

AI-2 automatically transforms compatible PCs into the best AI workstation that hardware can realistically support. It never says "your computer is too weak." It detects the hardware, assigns a capability tier, tunes the system for it, measures what the machine can really do, and recommends models that genuinely fit, locally where possible, remotely by explicit choice.

Reference platform is Artix Linux with runit. The oldest validated target is a 2011 laptop (AMD A4-3305M, no SSE4.1, 4 GB RAM, spinning disk) that runs a 0.5B model at about 2 tokens per second from a package built for exactly that CPU class.

## Install

On any Artix (or Arch-based) system, add the signed AI-2 repository:

```
curl -fsSL https://raw.githubusercontent.com/ProWoos-Devs/ai2-packages/main/ai2-package-signing.asc | sudo pacman-key --add -
sudo pacman-key --lsign-key F1889E37B4E5FEC8
```

Append to `/etc/pacman.conf`:

```
[ai2]
SigLevel = Required DatabaseOptional
Server = https://github.com/ProWoos-Devs/ai2-packages/releases/download/x86_64
```

Then:

```
sudo pacman -Sy ai2-keyring ai-2
sudo pacman -S ai2-llama-cpp-baseline    # or -noavx / -avx2, ai-2 detect tells you which
```

Or boot the AI-2 ISO (Artix XFCE runit, Calamares installer, everything above preinstalled).

## Commands

```
ai-2 detect          # what AI-2 sees: CPU (and which llama.cpp build it needs), RAM, GPU, disk, init
ai-2 tier            # the assigned capability tier and why
ai-2 init            # dry run, print the tuning plan for this machine
ai-2 init --apply    # apply it (root): zram, earlyoom, sysctl, no idle suspend during inference
ai-2 benchmark       # run llama.cpp on a fixed workload, compute the 0-100 AI Score and capability stars
ai-2 recommend       # which local model fits this machine, and when to go remote
ai-2 runtime install # install the llama.cpp package for this CPU class (--apply, root)
ai-2 model pull      # download the recommended model (or: ai-2 model pull <id>)
ai-2 serve           # llama-server on demand with the recommended model, OpenAI-compatible
                     # API on http://127.0.0.1:8080, exits after 10 idle minutes
ai-2 logo            # the mark, in the size the terminal allows
```

`AI-2` works as a synonym for `ai-2` everywhere.

## Packages

- `ai-2`, this tool.
- `ai2-keyring`, the package signing key for pacman.
- `ai2-llama-cpp-baseline` (pure SSE2, pre-2011 and Llano-class CPUs), `ai2-llama-cpp-noavx` (SSE4.x, no AVX), `ai2-llama-cpp-avx2` (Haswell and later). All three come from one pinned llama.cpp release; every binary is disassembled against its target instruction set before it ships, because a single stray SSE4.1 instruction crashes an old machine.

## Architecture

Three orthogonal pillars. The Adaptation Engine detects hardware, assigns one of six capability tiers (Tiny, Light, Standard, Creator, Studio, Workstation), and applies the corresponding configuration. The Workflow Engine describes what the user wants to do, as declarative YAML profiles. The Runtime Engine executes models; the local runtime is llama.cpp, selected per CPU class, with persistent heavyweight daemons avoided on low-memory tiers.

**Workflows request capabilities; tiers grant a subset; runtimes execute what was granted.** RAM alone over-promises, so the AI Score measured by `ai-2 benchmark`, not the tier, gates which model is recommended.

Everything is declarative. Tier definitions live in `ai2/data/tiers/*.yml`, the model catalog in `ai2/data/models.yml`, workflow profiles in `profiles/`. The engine is deliberately small (Python 3.11+, PyYAML only).

## Layout

- `ai2/` the tool. `tests/` (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/`).
- `packaging/` PKGBUILDs, the ISA gate (`isa-check.sh`), build and sign/publish scripts.
- `iso/` the artools profile for the AI-2 ISO and the QEMU test helper.
- `branding/` MOTD and greeter configuration.

## Status

Foundation done and validated on real hardware. Signed package repository live. ISO boots and installs (BIOS/MBR verified on the 2011 laptop and in QEMU). The loop closes: `ai-2 init --apply` installs the right runtime package, `ai-2 model pull` fetches the recommended model, `ai-2 serve` runs it on demand (verified end to end on the 2011 laptop). Next, `ai-2 doctor`, first-boot wizard, workflow profiles.

## License

MIT, see `LICENSE`. Two small pieces derived from Artix Linux keep their own terms, see `LICENSES.md`.
