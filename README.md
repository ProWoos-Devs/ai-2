<p align="center"><img src="branding/ai2-logo.svg" width="420" alt="> AI-2"></p>

# AI-2

**Give your computer an AI brain.**

AI-2 turns an ordinary or old PC into a local AI machine that fits what that hardware can actually do. It detects
the machine, tunes it, measures what it can really manage, and recommends models that fit, locally where possible
and remotely only by explicit choice. Reference platform is Artix Linux with runit.

## Install

### Option 1: the AI-2 ISO (recommended)

A complete system: Artix Linux (runit), XFCE, the AI engine and the `ai-2` tool, with a graphical installer. Lean by design, about 1.9 GB, with three Knowledge Packs and the model that searches them already on board.

1. Download the latest ISO: [ai-2-x86_64.iso](https://github.com/ProWoos-Devs/ai-2/releases/latest/download/ai-2-x86_64.iso) and its [SHA-256](https://github.com/ProWoos-Devs/ai-2/releases/latest/download/ai-2-x86_64.iso.sha256). Every release is also kept under its build date on the [Releases page](https://github.com/ProWoos-Devs/ai-2/releases), and mirrored on [SourceForge](https://sourceforge.net/projects/ai-2/).
2. Verify it: `sha256sum -c ai-2-x86_64.iso.sha256`
   The checksum itself is signed with the same key that signs every AI-2 package. To check that too, download [ai-2-x86_64.iso.sha256.sig](https://github.com/ProWoos-Devs/ai-2/releases/latest/download/ai-2-x86_64.iso.sha256.sig), then:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/ProWoos-Devs/ai2-packages/main/ai2-package-signing.asc | gpg --import
   gpg --verify ai-2-x86_64.iso.sha256.sig ai-2-x86_64.iso.sha256
   ```
   It should say a good signature from the AI-2 signing key, `F1889E37B4E5FEC8`. The key, how pacman checks every package, and how to stay on an older version are on one page, [Verifying and Pinning](https://github.com/ProWoos-Devs/ai-2/wiki/Verifying-and-Pinning).
3. Write it to a USB stick of 4 GB or more, or burn it to a DVD. Linux or macOS (replace `sdX`, everything on the stick is erased): `sudo dd if=ai-2-x86_64.iso of=/dev/sdX bs=4M conv=fsync status=progress`. Windows: Rufus or balenaEtcher in their default mode.
4. Boot the computer from the stick. It starts a live desktop (logs in by itself, user `ai-2`, password `ai-2`) that you can try without touching your disks. `START-HERE.txt` on that desktop explains the installation; "Install AI-2" starts the installer.

After the installation, the setup wizard opens at the first login and does everything below for you. Requirements: a 64-bit PC, 2 GB of RAM (4 GB recommended), about 6 GB of disk, Secure Boot off (the image is not signed for it). Internet is not needed to install, only later for models and updates.

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
sudo pacman -Syu ai2-keyring ai-2
sudo pacman -S ai2-llama-cpp             # the engine; it picks the build for this CPU at start
sudo ai-2 init --apply                   # or just: ai-2 wizard
```

## Knowledge Packs

A Knowledge Pack is a set of documents this computer searches and answers from in seconds, with no internet,
naming the document every answer came from. No model writes those answers, so an old laptop gives the same ones
as a new machine. Three come with the ISO, and **Applications > AI-2 > Search Knowledge** answers from them right
after the install.

- **Get more**: `ai-2 knowledge browse` (or **Applications > AI-2 > Knowledge Packs**) lists what there is, with
  what is in each and who made it, and installs the ones you pick by number.
- **Make one**: `ai-2 knowledge export` builds a pack from your own PDFs and notes. To share it, host the file and
  open a pull request adding your entry to the catalog; the steps are in
  [CONTRIBUTING.md](https://github.com/ProWoos-Devs/ai2-knowledge/blob/main/CONTRIBUTING.md), and the checks on your
  pull request download the file, install it and compare it with what your entry claims.
- **Everything lives here**: the community catalog, https://github.com/ProWoos-Devs/ai2-knowledge, where the
  project's own packs sit with everyone else's. Ideas and problems about packs belong in that repository's
  [Issues](https://github.com/ProWoos-Devs/ai2-knowledge/issues); anything about AI-2 itself belongs in
  [this one's](https://github.com/ProWoos-Devs/ai-2/issues).

More in the wiki, [Knowledge Packs](https://github.com/ProWoos-Devs/ai-2/wiki/Knowledge-Packs).

## Translations

So far, in the installer AI-2 speaks the following languages:

<!-- installer-languages:start -->
- English
- Spanish
- German
- Polish
<!-- installer-languages:end -->

Anyone can add a language, with no programs to install and nothing to compile; [TRANSLATING.md](TRANSLATING.md) walks
the whole way, and the checks on your pull request say what is still missing.

<!-- translators:start -->
| Language | Code | Translated by |
|---|---|---|
| English | `en` | [ProWoos team](https://github.com/ProWoos-Devs) |
| Español | `es` | [Rafael Minuesa](https://github.com/rafael-minuesa) |
| Deutsch | `de` | [ProWoos team](https://github.com/ProWoos-Devs) |
| Polski | `pl` | [Mateusz Szczepaniak](https://github.com/szczepaniakmateusz59-del) |
<!-- translators:end -->

## What your machine can do

`ai-2 benchmark` runs llama.cpp on a fixed workload and scores the machine from 0 to 100. That score, not the
amount of RAM, decides which model is recommended: RAM alone over-promises. The oldest validated target is a 2011 laptop (AMD A4-3305M, no SSE4.1, 4 GB RAM, spinning disk) that runs a 0.5B model at about 2 tokens per second from a package built for exactly that CPU class.

The packaged llama.cpp runtime is CPU-only, and `ai-2 detect` says so next to any GPU it lists. This position was reviewed with sources on 2026-09-14. CUDA and ROCm are not coming for the hardware AI-2 is built for. The CUDA toolkit package alone is bigger than the whole AI-2 ISO and CUDA 13 dropped the GeForce GTX 10 series and older, while ROCm is over 9 GB installed and supports no GCN card. Proprietary NVIDIA drivers are out-of-tree kernel modules, the same class of problem as the Broadcom WiFi driver, so they will never ship on the image. The one GPU path under consideration is a Vulkan build of llama.cpp on Mesa's open drivers. It is not built, and it would pay off only on a machine with a discrete card of the Radeon RX 400 or GeForce GTX 10 generation or later, never on the shared-memory integrated GPUs of the laptops AI-2 was validated on, which cannot run it at all.

## Commands

```
ai-2 wizard          # the guided setup, re-runnable any time
ai-2 doc search      # ask the Knowledge Packs and your own documents (the Search Knowledge menu entry)
ai-2 knowledge browse # see the Knowledge Packs there are, install or update by number
ai-2 chat            # start the local AI if needed and open the chat page (--terminal on a slow machine)
ai-2 update          # update AI-2, the engine, the model catalog and the system in one step
ai-2 doctor          # check engine, model, tuning, services, repository key
```

Everything else, 27 commands in all, from `ai-2 detect` to `ai-2 transcribe`, is in the wiki,
[Commands](https://github.com/ProWoos-Devs/ai-2/wiki/Commands). `AI-2` works as a synonym for `ai-2` everywhere.

### Using the local AI from other apps

`ai-2 serve --host 0.0.0.0 --api-key KEY` is a standard OpenAI-compatible endpoint. Any app with a custom base URL field takes `http://HOST:8080/v1` plus that key. Documented by their upstreams (not yet driven end to end from an AI-2 box), Open WebUI, Paperless-GPT, Open Notebook and Blinko. Home Assistant only through the community integrations Home LLM or Extended OpenAI Conversation, since its built-in OpenAI, Ollama and Anthropic integrations do not accept a third-party endpoint. Those apps run on another machine, the AI-2 box is only the server. An embedding endpoint exists too, `ai-2 serve --model nomic-embed-text-v2-moe --host 0.0.0.0 --api-key KEY` serves `/v1/embeddings` on port 8081 (it is what `ai-2 doc` uses locally).

Two things to know. `ai-2 serve` is a foreground command with no boot-time service yet, so a box that serves other apps needs it kept running (tmux, screen, or a runit service of your own), and `ai-2 chat` only ever starts a server on localhost. It serves the score-recommended model with the tier's context size (4096 on Standard, 8192 on Creator). `--model` and `--ctx` override that with a RAM check only, no speed check, and `/v1/models` reports the model file path as the id.

Which machine can be the server is a question for the AI Score, not the tier. On the 2011 reference laptop the 0.5B model generates at about 2 tokens per second and reads prompts no faster, so a 1000-token tagging prompt takes minutes before the first output token. Machines like that are the clients. A stronger machine on the network runs `ai-2 serve` and they run `ai-2 chat --remote`. Background jobs such as document tagging tolerate a slow server, a voice assistant does not.

## Packages

- `ai-2`, this tool.
- `ai2-keyring`, the package signing key for pacman.
- `ai2-help`, `ai2-everyday`, `ai2-linux-essentials`, the three Knowledge Packs that come with AI-2. Each installs
  the file the catalog publishes, into `/usr/share/ai2/doc/`, so `pacman -Syu` refreshes them and `pacman -R`
  removes one.
- `ai2-llama-cpp`, the engine, one package for every CPU class: llama.cpp from one pinned release, built for plain x86-64, plus one CPU backend module per instruction-set level (x64, sse42, sandybridge, ivybridge, piledriver, haswell, ...); ggml scores the modules against the CPU at start and loads the best, x64 always qualifying. Before it ships, every file that must run on a pure-SSE2 machine is disassembled against that instruction set, and the constructors every module runs at load are checked the same way, because a single stray SSE4.1 instruction crashes an old machine. `ai-2 benchmark` records which module ran.
- `ai2-whisper-cpp`, the speech-to-text engine for `ai-2 transcribe`, from one pinned whisper.cpp release with its own ggml, no ffmpeg linked in. One package for every CPU: like ggml in llama.cpp, it picks the CPU build at start, and the same gate checks every binary and every CPU module before it ships.

## Status

AI-2 0.19.0. Tested on two older AMD laptops and through complete QEMU installs. The ISO boots and installs in
BIOS/MBR and UEFI/GPT modes, a setup wizard runs at the first login, and three Knowledge Packs answer offline from
the moment it is installed. Hardware detection, tier tuning, AI Score benchmarking, model recommendations, health
reports, speech to text and the workflow profiles are implemented; `ai-2 workflow install` downloads a profile's
models and prints its packages as a pacman line rather than installing them. Validation details live in the
[Wiki](https://github.com/ProWoos-Devs/ai-2/wiki/Validated-Hardware); bugs and ideas belong in
[Issues](https://github.com/ProWoos-Devs/ai-2/issues).

## For people who clone the repo

**Architecture.** Three parts. The Adaptation Engine detects hardware, assigns one of six capability tiers (Tiny,
Light, Standard, Creator, Studio, Workstation) and applies the matching configuration. The Workflow Engine
describes what the user wants to do, as declarative YAML profiles. The Runtime Engine executes models; the local
runtime is llama.cpp, chosen per CPU class, and heavyweight daemons are avoided on low-memory tiers. Workflows
request capabilities, tiers grant a subset, runtimes execute what was granted.

Everything is declarative. Tier definitions live in `ai2/data/tiers/*.yml`, the model catalog in
`ai2/data/models.yml`, workflow profiles in `ai2/data/profiles/*.yml`. The engine is deliberately small
(Python 3.11+, PyYAML only).

**Layout.**

- `ai2/` the tool. `tests/` (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/`).
- `packaging/` PKGBUILDs, the ISA gate (`isa-check.sh`), build and sign/publish scripts.
- `iso/` the artools profile for the AI-2 ISO and the QEMU test helper.
- `branding/` MOTD and greeter configuration.

## License

MIT, see `LICENSE`. Two small pieces derived from Artix Linux keep their own terms, see `LICENSES.md`.

## About

AI-2 is made by Rafael Minuesa (ProWoos, https://prowoos.com), built with Claude Code. MIT licensed; Artix Linux, llama.cpp and the models keep their own licenses (see `LICENSES.md`). Project page: https://prowoos.com/software-development/linux/ai-2/
