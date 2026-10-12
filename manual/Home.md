**Give your computer an AI brain.**

AI-2 is a Linux distro for ordinary and older PCs, based on Artix Linux (runit). It detects your hardware, assigns a capability tier, tunes the system for it, measures what the machine can really do, and recommends AI models that genuinely fit, locally where possible, remotely by explicit choice.

The oldest validated machine is a 2011 laptop with 4 GB of RAM and no SSE4.1, running a 0.5B model locally. The installer, the setup wizard and the chat speak English, Spanish and German.

## Getting started

* [[Installation]], download and verify the ISO, write the USB stick, try the live desktop, run the installer.
* [[First Steps]], the setup wizard at first login, opening the chat, the basic commands.
* [[Install on an existing Artix or Arch system]], the signed `[ai2]` pacman repository.
* [[Verifying and Pinning|Verifying-and-Pinning]], checking the image and the packages against the AI-2 signing key, and staying on an older version.

## Reference

* [[Commands]], every `ai-2` subcommand explained.
* [[Capability Tiers]], the six tiers (Tiny, Light, Standard, Creator, Studio, Workstation) and how one is assigned.
* [[AI Score and Benchmarks]], what the 0-100 score measures and why it, not RAM, gates model recommendations.
* [[Models]], the catalog, pulling, verifying and removing models, and the embedding models `ai-2 doc` uses for your documents.
* [[Knowledge Packs|Knowledge-Packs]], offline collections your computer can search and answer from, the three that come with AI-2, and how to make your own. The community catalog, where every pack is listed with its download and where you share yours, is at https://github.com/ProWoos-Devs/ai2-knowledge.
* [[Local API Server]], `ai-2 serve`, an OpenAI-compatible API on your own machine.

## Help

* [[FAQ and Troubleshooting]], Secure Boot, CPU build variants, graphics fallback, common errors.
* [[Accessibility]], using AI-2 with a screen reader, spoken chat, honest status and limits.
* [[Validated Hardware]], machines AI-2 has been tested on, with their scores.

## Elsewhere

* Downloads live on the [Releases page](https://github.com/ProWoos-Devs/ai-2/releases), mirrored on [SourceForge](https://sourceforge.net/projects/ai-2/).
* Questions and ideas go to [Discussions](https://github.com/ProWoos-Devs/ai-2/discussions), confirmed bugs to [Issues](https://github.com/ProWoos-Devs/ai-2/issues). Attach `~/ai2-report.txt` (from `ai-2 report`) to bug reports.
* Project page: [prowoos.com/software-development/linux/ai-2](https://prowoos.com/software-development/linux/ai-2/)
