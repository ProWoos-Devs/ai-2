# AI-2

AI-2 automatically transforms any compatible PC into the best AI workstation that hardware can realistically support.

It never says "your computer is too weak." It detects the hardware, assigns a capability tier, tunes the system for it, and serves the largest models that genuinely fit, locally where possible, remotely by explicit choice.

Reference platform is Artix Linux with runit. Phase 0 goal, prove that AI-2 can transform a vanilla Artix installation into an adaptive AI workstation.

## Commands

```
ai-2 detect          # show what AI-2 sees (CPU, RAM, GPU, storage, init system)
ai-2 tier            # show the assigned capability tier and why
ai-2 init            # dry run, print the tuning plan for this machine
ai-2 init --apply    # apply the plan (root required)
```

`AI-2` works as a synonym for `ai-2` everywhere.

## Architecture

Three orthogonal pillars. The Adaptation Engine detects hardware, assigns one of six capability tiers (Tiny, Light, Standard, Creator, Studio, Workstation), and applies tuning. The Workflow Engine describes what the user wants to do, as declarative community-editable YAML profiles. The Runtime Engine executes models (llama.cpp first, others behind the same abstraction). Workflows request capabilities, tiers grant a subset, runtimes execute what was granted.

Everything is declarative. Tier definitions live in `ai2/data/tiers/*.yml`, workflow profiles in `profiles/`. The engine is deliberately small.

## Status

Phase 0 (Foundation). Detection, tier assignment, tuning engine with dry-run and apply, tier and profile YAML formats. Not yet here, benchmark and AI Score, `ai-2 doctor`, model downloads, the package repo, the ISO.
