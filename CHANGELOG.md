# Changelog

All notable changes to AI-2: the `ai-2` tool (semantic versions, matching the `ai-2` pacman package) and the AI-2 ISO (date snapshots, `artix-ai2-runit-YYYYMMDD-x86_64.iso`, each tagged `iso-YYYYMMDD` in git at the commit it was built from). Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### ISO (next build)
- FIX: installed systems get Artix's `/etc/default/grub` again (GRUB theme, `os-prober` enabled so Windows shows in the boot menu, 1024x768 mode). Our profile had lost the stock symlink into artools' common overlay; the 20260816/17 ISOs install a text-mode GRUB without other operating systems. Workaround on an affected install: enable `GRUB_DISABLE_OS_PROBER=false` and the theme in `/etc/default/grub`, then `grub-mkconfig -o /boot/grub/grub.cfg`.
- Installer: QML welcome page (language choice first, labeled; "Read the guide" button), padded sidebar logo, root filesystem labeled "AI-2", live session never locks or blanks the screen, START-HERE explains how to recognize partitions.

### ai-2 (tool)
- `ai-2 logo` prints the bare boxed mark; the tagline and the "Based on Artix Linux" line are gone from the tool, the MOTD and every shipped asset (2026-08-16). Not yet in a built package (0.2.0-1 was built before this change).

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
