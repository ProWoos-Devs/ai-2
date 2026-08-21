<p align="center"><img src="branding/ai2-logo.svg" width="420" alt="> AI-2"></p>

# AI-2

**Give your computer an AI brain.**

AI-2 automatically transforms compatible PCs into the best AI workstation that hardware can realistically support. 
It detects the hardware, assigns a capability tier, tunes the system for it, measures what the machine can really do, and recommends models that genuinely fit, locally where possible, remotely by explicit choice.

Reference platform is Artix Linux with runit. The oldest validated target is a 2011 laptop (AMD A4-3305M, no SSE4.1, 4 GB RAM, spinning disk) that runs a 0.5B model at about 2 tokens per second from a package built for exactly that CPU class.

## Install

### Option 1: the AI-2 ISO (recommended)

A complete system: Artix Linux (runit), XFCE, the AI engine and the `ai-2` tool, with a graphical installer. Lean by design, 1.85 GB.

1. Download the latest ISO from the [Releases page](https://github.com/ProWoos-Devs/ai-2/releases) (current: [artix-ai2-runit-20260821-x86_64.iso](https://github.com/ProWoos-Devs/ai-2/releases/download/iso-20260821/artix-ai2-runit-20260821-x86_64.iso), with its [SHA-256](https://github.com/ProWoos-Devs/ai-2/releases/download/iso-20260821/artix-ai2-runit-20260821-x86_64.iso.sha256)).
2. Verify it: `sha256sum -c artix-ai2-runit-20260821-x86_64.iso.sha256`
3. Write it to a USB stick of 4 GB or more. Linux or macOS (replace `sdX`, everything on the stick is erased): `sudo dd if=artix-ai2-runit-20260821-x86_64.iso of=/dev/sdX bs=4M conv=fsync status=progress`. Windows: Rufus or balenaEtcher in their default mode.
4. Boot the computer from the stick. It starts a live desktop (logs in by itself, user `ai-2`, password `ai-2`) that you can try without touching your disks. `START-HERE.txt` on that desktop explains the installation; "Install AI-2" starts the installer.

After the installation, the setup wizard opens at the first login and does everything below for you. Requirements: a 64-bit PC, 2 GB of RAM (4 GB recommended), about 6 GB of disk. Internet is not needed to install, only later for models and updates.

### Option 2: packages on an existing Artix or Arch-based system

Add the signed AI-2 repository:

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
sudo ai-2 init --apply                   # or just: ai-2 wizard
```

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

Early, usable, tested on one old laptop and in QEMU. The ISO (lean by design, 1.85 GB) boots and installs (BIOS/MBR verified on the 2011 laptop and in QEMU), a setup wizard runs at the first login, `ai-2 chat` opens a local chat page. Next, `ai-2 doctor`, workflow profiles, a Plymouth splash. Bugs and ideas: https://github.com/ProWoos-Devs/ai-2/issues

## License

MIT, see `LICENSE`. Two small pieces derived from Artix Linux keep their own terms, see `LICENSES.md`.

## About

AI-2 is made by Rafael Minuesa (ProWoos, https://prowoos.com), built with Claude Code. MIT licensed; Artix Linux, llama.cpp and the models keep their own licenses (see `LICENSES.md`). Project page: https://prowoos.com/software-development/linux/ai-2/
