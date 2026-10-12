You do not need the ISO to use AI-2. The `ai-2` tool and the AI engine install as normal packages on an existing Artix or Arch-based system, from AI-2's signed pacman repository.

## 1. Trust the signing key

```
curl -fsSL https://raw.githubusercontent.com/ProWoos-Devs/ai2-packages/main/ai2-package-signing.asc | sudo pacman-key --add -
sudo pacman-key --lsign-key F1889E37B4E5FEC8
```

## 2. Add the repository

Append to `/etc/pacman.conf`:

```
[ai2]
SigLevel = Required DatabaseOptional
Server = https://github.com/ProWoos-Devs/ai2-packages/releases/download/x86_64
```

## 3. Install and set up

```
sudo pacman -Sy ai2-keyring ai-2
sudo pacman -S ai2-llama-cpp             # the engine; it picks the build for this CPU at start
sudo ai-2 init --apply                   # or just: ai-2 wizard
```

`ai-2 init --apply` also installs the engine by itself, so the middle line is optional. From here, [[First Steps]] applies the same as on an ISO install.

## The packages

* `ai-2`, the tool itself.
* `ai2-keyring`, the package signing key for pacman.
* `ai2-llama-cpp`, the engine, one package for every CPU class. llama.cpp from one pinned release, built for plain x86-64, plus one CPU backend module per instruction-set level (x64, sse42, sandybridge, ivybridge, piledriver, haswell, ...); ggml scores the modules against the CPU at start and loads the best, x64 always qualifying. Before it ships, every file that must run on a pure-SSE2 machine is disassembled against that instruction set, and so is every constructor a module runs at load, because a single stray SSE4.1 instruction crashes an old machine. `ai-2 benchmark` records which module ran. (Machines installed before this package carry `ai2-llama-cpp-baseline`, `-noavx` or `-avx2`; the next update swaps them for this one.)

## Undoing the tuning

`sudo ai-2 init --revert` undoes a previous `--apply` from its manifest, restoring the original of any file AI-2 overwrote (kept as `*.ai2-orig`) or removing files it created, and disabling the services it enabled. It never removes packages.
