# Changelog

All notable changes to AI-2: the `ai-2` tool (semantic versions, matching the `ai-2` pacman package) and the AI-2 ISO (date snapshots, `artix-ai2-runit-YYYYMMDD-x86_64.iso`, each tagged `iso-YYYYMMDD` in git at the commit it was built from). Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### ISO (next build)
- Installed systems: the `ai-2` package (0.3.0) now ships the first-login setup wizard autostart, the "AI-2 Chat" menu entry, the AI-2 icon and START-HERE.txt (the live session hides the autostart); the overlays no longer carry START-HERE/icon. XFCE default browser set to Epiphany (the one installed) so AI-2 Chat opens the chat page directly. NOTE: this ISO needs ai-2 0.3.0 published in the [ai2] repo first.
- FIX: installed systems get Artix's `/etc/default/grub` again (GRUB theme, `os-prober` enabled so Windows shows in the boot menu, 1024x768 mode). Our profile had lost the stock symlink into artools' common overlay; the 20260816/17 ISOs install a text-mode GRUB without other operating systems. Workaround on an affected install: enable `GRUB_DISABLE_OS_PROBER=false` and the theme in `/etc/default/grub`, then `grub-mkconfig -o /boot/grub/grub.cfg`.
- Installer: QML welcome page (language choice first, labeled; "Read the guide" button), padded sidebar logo, root filesystem labeled "AI-2", live session never locks or blanks the screen, START-HERE explains how to recognize partitions.

## [0.3.0] - 2026-08-19
### Added
- `ai-2 wizard`: the guided first-run setup (scan, tune with one password prompt, install the engine, get a first model, measure the AI Score, recommend and download the fitting model, explain how to use it). Runs by itself in a terminal window at the first login of an installed system (`ai2-first-boot`, marker `~/.config/ai2/setup-done`), and any time by hand. Unattended with `--yes`.
- `ai-2 chat`: starts the local AI server on demand (detached, stops after 30 min without generation; a chat page left open does not count) and opens the chat page (llama.cpp's built-in web UI) in the browser; "AI-2 Chat" desktop entry. Verified end to end in QEMU (wizard, downloads, benchmark, chat answer in the browser).
- The AI Score is persisted per user (`~/.config/ai2/score.json`) when not root, so `recommend`, `model pull`, `serve` and `chat` work without sudo.
### Changed
- `ai-2 logo` prints the bare boxed mark; the tagline and the "Based on Artix Linux" line are gone from the tool, the MOTD and every shipped asset.
- Models downloaded as a user (`~/.local/share/ai2/models`) are found by the benchmark.
- Package depends on xdg-utils; optdepends xfce4-terminal; ships icon, desktop entries, START-HERE.

## ISO 20260817 (2026-08-17), tag `iso-20260817`
- Live desktop: the "Install AI-2" icon sits right under START-HERE, before the Artix PDFs.

## ISO 20260816 (2026-08-16), tag `iso-20260816`
- AI-2 GRUB boot menu: boxed `> AI-2` logo above a translucent panel, phosphor palette, DejaVu Sans Mono 20 items with Unifont fallback, dark-on-green selection, key hints. Theme sources in `branding/grub-theme/`, overlaid on `themes/artix` so the ISO and installed systems share it.
- One boot entry, "Start AI-2", listed first and preselected; auto-starts after 10 s with a visible countdown; prints "Starting AI-2 ..." while the kernel and initramfs load from the stick; boot-menu help rewritten for beginners.
- "Install AI-2" starts Calamares directly with the offline configuration (no chooser dialog).
- Branding: tagline and attribution line removed everywhere (wallpaper, MOTD, Calamares slide and banner, tool).
- START-HERE.txt beginner guide on the live desktop (replaces Artix's one-line README.txt) and at `/usr/share/doc/ai2/`; Leafpad defaults (900x650, word wrap) for new users.

## ISO 20260815 (2026-08-15), tag `iso-20260815`
- `ai-2`, `ai2-keyring` and the three `ai2-llama-cpp-*` runtimes come from the signed `[ai2]` repository; installed systems carry `[ai2]` in `pacman.conf`.
- The offline installer now initializes and populates the target's pacman keyring (Calamares `shellprocess@keyring` job); the live session's `pacman-init` trusts `[ai2]` too. Fully re-validated by a complete QEMU install.

## [0.2.0] - 2026-08-16
### Added
- `ai-2 runtime install`, `ai-2 model pull`, `ai-2 serve` (llama-server on demand, exits when idle). `ai-2 init --apply` installs the runtime package for the machine's CPU class. Verified on RMM-PC serving a completion over the LAN.

## [0.1.0] - 2026-08-16
First tagged release, Phase 0 validated on real hardware (HP Pavilion g4, AMD A4-3305M without SSE4.1, 4 GB).
### Added
- `ai-2 detect`, `tier`, `init` (`--apply`: zram, earlyoom, no idle suspend), `benchmark` (0-100 AI Score from measured tokens/s), `recommend` (score-gated local model catalog), `logo`.
- Signed `[ai2]` pacman repository on GitHub Releases; packages `ai-2`, `ai2-keyring`, `ai2-llama-cpp-{baseline,noavx,avx2}` (llama.cpp b10398, ISA-gated builds).
- MIT license, README with the mantra "Give your computer an AI brain".

## ISO 20260814 (2026-08-14), tag `iso-20260814`
- First fully validated AI-2 ISO (QEMU install and RMM-PC live boot): AI-2 Calamares branding, live user `ai-2`/`ai-2` with autologin, NetworkManager, AI-2 wallpaper as the xfdesktop fallback, MOTD and greeter branding.
- Fixed in the installer path: Artix's `artix-service` could not enable runit services inside the Calamares chroot (a fixed copy is shipped), and the inherited profile enabled `connmand` without installing it.

## ISO 20260813 (2026-08-13)
- First AI-2 ISO built (Artix XFCE runit profile plus the `ai-2` tool, zramen, earlyoom, branding overlay). Superseded by 20260814.
