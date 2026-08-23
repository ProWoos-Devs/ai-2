# Changelog

All notable changes to AI-2: the `ai-2` tool (semantic versions, matching the `ai-2` pacman package) and the AI-2 ISO (date snapshots, `artix-ai2-runit-YYYYMMDD-x86_64.iso`, each tagged `iso-YYYYMMDD` in git at the commit it was built from). Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## ISO 20260821b (2026-08-21), tag `iso-20260821b`
Ships `ai-2` 0.4.0 and the installer/boot-menu changes listed under 0.4.0. 1,988,308,992 bytes. Verified by a complete QEMU install on BIOS AND, for the first time, on UEFI (OVMF, GPT with a 512 MB EFI system partition): installed systems carry lsb-release AI-2, GRUB saved/8 s/no splash, ai-2 0.4.0, broadcom-wl, no live autologin; `ai-2 init --apply` then `ai-2 doctor` on the installed system reports MGLRU enabled with min_ttl_ms 1000 through the new boot-tuning path. Installed on the 2011 laptop 2026-08-23 (Windows 7 in the menu, wizard, doctor clean, idle exit verified). Released on GitHub 2026-08-23 with the fixed-name `ai-2-x86_64.iso` assets that the `releases/latest` URL serves.

## [0.4.0] - 2026-08-21
First sprint of the 2026-08-21 enhancement review (`000/20260821-enhancement-review.md` in the workspace).
### Fixed
- The on-demand server no longer stays resident forever after one failed idle poll (it failed open); a poll failure now counts as idle once the server has answered, with a 15 minute start-up grace for cold HDD loads. Verified on the 2011 laptop 2026-08-23 (exits after the tier's 600 s).
- Downloads resume instead of restarting, every catalog file is verified by SHA-256, `model pull` and the wizard refuse to start on a full disk, `serve` warns when free RAM is below the model's peak.
- Tier YAMLs named models that were not in the catalog; capability key `coding_assist` did not match the scoring (`coding`); `pyproject.toml` carried a stale version. Cross-file tests and a GitHub Actions workflow now catch this.
- `ai-2 init --apply` reports which step failed and what was already applied instead of a traceback; the no-suspend drop-in goes to systemd-logind on systemd systems.
- `ai-2 chat --model X` refuses to attach to a server that holds a different model.
### Added
- `ai-2 doctor` (health checks), `ai-2 report` (bug-report file), `ai-2 stop`.
- `serve --api-key` (required to bind off localhost, or `--insecure`); serve/chat take idle timeout and context from the applied tier (Tiny 300 s / 1024 tokens).
- zswap and MGLRU `min_ttl_ms` are applied through `/usr/lib/ai2/boot-tuning.sh` and the `ai2-boot` one-shot service; Standard and Creator tiers stop being memory no-ops; pre-SSE4.1 CPUs get lz4 zram.
- Catalog: Gemma 3 270M (242 MB) and Qwen3.5 0.8B MTP (525 MB), license field on every entry; `qwen2.5-0.5b` flagged as the fixed benchmark workload. Measured on the 2011 laptop (A4-3305M, 2 threads, 150 tokens): Gemma 3 270M 4.5 tok/s, Qwen2.5 0.5B 1.8, Qwen3.5 0.8B 1.0; speculative decoding (`--spec-type draft-mtp`) halves Qwen3.5's speed there, so it is not used.
- A pacman hook re-applies the fixed `artix-service` after `base` upgrades.
### ISO profile (takes effect with the next ISO)
- `broadcom-wl` in the installed system, not only the live layer.
- Installer: swap default "small" instead of RAM-sized; UEFI boot entry named AI-2; GRUB remembers the last choice and waits 8 s; "splash" dropped from the kernel line; `/etc/lsb-release` says AI-2; live autologin no longer travels into the installed lightdm.conf.
- Boot menu: "Check this stick first" (checksum=y) and "safe graphics" (nomodeset) entries.
- START-HERE: Secure Boot and 64-bit notes, doctor/report/stop commands.


### ISO 20260819 (details)
- Installed systems: the `ai-2` package (0.3.0) now ships the first-login setup wizard autostart, the "AI-2 Chat" menu entry, the AI-2 icon and START-HERE.txt (the live session hides the autostart); the overlays no longer carry START-HERE/icon. XFCE default browser set to Epiphany (the one installed) so AI-2 Chat opens the chat page directly. ai-2 0.3.0 was published to the [ai2] repo 2026-08-19 22:01.
- FIX: installed systems get Artix's `/etc/default/grub` again (GRUB theme, `os-prober` enabled so Windows shows in the boot menu, 1024x768 mode). Our profile had lost the stock symlink into artools' common overlay; the 20260816/17 ISOs install a text-mode GRUB without other operating systems. Workaround on an affected install: enable `GRUB_DISABLE_OS_PROBER=false` and the theme in `/etc/default/grub`, then `grub-mkconfig -o /boot/grub/grub.cfg`.
- Installer: QML welcome page (language choice first, labeled; "Read the guide" button), padded sidebar logo, root filesystem labeled "AI-2", live session never locks or blanks the screen, START-HERE explains how to recognize partitions.

## [0.3.2] - 2026-08-21
### Changed
- START-HERE: states the real floor (64-bit CPU, 2 GB of RAM, about 6 GB of disk) instead of "AI-2 never says this computer cannot run AI", which the installer's own requirements check contradicted.

## ISO 20260821 (2026-08-21), tag `iso-20260821`
Same lean system as 20260820 (ai-2 0.3.1), installer only. 1,989,390,336 bytes. Verified by a complete QEMU install and first login (GRUB theme, greeter, wizard autostart, Mousepad wraps START-HERE on the installed system). First ISO published as a GitHub Release on the public repo https://github.com/ProWoos-Devs/ai-2.
### Fixed
- Welcome page no longer shows "This computer does not satisfy the minimum requirements" while the disk scan is still running (seen on a real HDD). Calamares fills the requirements list module by module and the QML page had no "check finished" state; it now shows "Checking this computer (disks, memory, network)…" with Calamares' progress line until the partition module has reported (2 minute fallback).
### Changed
- Install slideshow: seven slides, 8 s each (logo, honest about your hardware, first steps with the wizard and `ai-2 chat`, your data stays here, lean by design, based on Artix Linux, your feedback with the issues page and the project page).

## [0.3.1] - 2026-08-20
### Changed
- START-HERE: "Lean by design" section (the ISO ships only the desktop, a browser, a text editor and the AI engine; how to add a PDF viewer, printing, a media player, an office suite), Artix help points at wiki.artixlinux.org (the PDF guides left the live desktop).
- Ships a GSettings override so Mousepad wraps long lines and opens at 900x650 (`/usr/share/glib-2.0/schemas/90_ai2.gschema.override`).

## ISO 20260820 (2026-08-20), tag `iso-20260820`
Ships `ai-2` 0.3.1 (final build 22:26, sha256 8a83d0aa…298f replaced by the one in `iso/out/*.sha256`; the 20:23 build carried 0.3.0 plus overlay copies). Lean by design. The ISO had grown past GitHub's 2 GiB release-asset limit (20260819: 2,173,290,496 bytes); this build is 1,989,390,336 bytes (1.85 GiB) with the same AI-2 content. The installed system drops from 655 to 556 packages (3.29 to 2.71 GB uncompressed); the initramfs from 161 to 51 MB. Live boot, START-HERE and the installer launch verified in QEMU; no full install run this time (the install path is unchanged).
### Removed (all installable later with pacman; START-HERE has a "Lean by design" section saying so)
- `linux-headers` (282 MB, no compiler ships anyway). artools needs it to read the kernel version when building the initramfs, so it is installed only into the throwaway bootfs layer (`packages-boot` in our `iso/profiles/common/common.yaml`, a trimmed copy of artools' list that `stage-profile.sh` puts in the workspace).
- `linux-firmware-nvidia` (104 MB): the split firmware packages replace the meta package; radeon, amdgpu, intel, atheros, realtek, broadcom, marvell, mediatek, qcom, cirrus and "other" stay.
- `atril` with `webkit2gtk-4.1` and `mathjax2` (175 MB), `cups` and `ghostscript` (58 MB, cupsd service gone), `vim`/`vi`, `leafpad` and gtk2, `zsh`, `texinfo`, `powertop`, `inxi`, `xfce4-goodies` (kept: mousepad, notifyd, pulseaudio plugin, screenshooter, taskmanager).
- Live session: `hexchat`, `virtualbox-guest-utils`, `artix-docs` (the PDF guides had no viewer left; START-HERE links wiki.artixlinux.org).
### Changed
- Mousepad is the text editor; it opens START-HERE wrapped at 900x650 (GSettings, set by the live `desktop-items` script; a gschema override is shipped for installed systems).
- Still to shrink further: Artix's `calamares` package depends on `plasma-integration`, which pulls Plasma, KWin and Breeze into the live layer (about 650 MB uncompressed); needs our own Calamares build.

## [0.3.0] - 2026-08-19
### Added
- `ai-2 wizard`: the guided first-run setup (scan, tune with one password prompt, install the engine, get a first model, measure the AI Score, recommend and download the fitting model, explain how to use it). Runs by itself in a terminal window at the first login of an installed system (`ai2-first-boot`, marker `~/.config/ai2/setup-done`), and any time by hand. Unattended with `--yes`.
- `ai-2 chat`: starts the local AI server on demand (detached, stops after 30 min without generation; a chat page left open does not count) and opens the chat page (llama.cpp's built-in web UI) in the browser; "AI-2 Chat" desktop entry. Verified end to end in QEMU (wizard, downloads, benchmark, chat answer in the browser).
- The AI Score is persisted per user (`~/.config/ai2/score.json`) when not root, so `recommend`, `model pull`, `serve` and `chat` work without sudo.
### Changed
- `ai-2 logo` prints the bare boxed mark; the tagline and the "Based on Artix Linux" line are gone from the tool, the MOTD and every shipped asset.
- Models downloaded as a user (`~/.local/share/ai2/models`) are found by the benchmark.
- Package depends on xdg-utils; optdepends xfce4-terminal; ships icon, desktop entries, START-HERE.

## ISO 20260819 (2026-08-19), tag `iso-20260819`
Everything listed under "ISO (next build)" above, built and verified by a complete QEMU install plus first login: themed GRUB with the "AI-2 Linux" entry and `os-prober` on, root filesystem labeled "AI-2", first-login wizard opens by itself, tuning applies with one password. Ships `ai-2` 0.3.0. Found and fixed on the way: Calamares 3.4's shellprocess rejects `$vars` in commands and no longer substitutes `@@ROOT@@` (use `${ROOT}`); xfce4-power-manager's inactivity value 14 means 14 minutes (0 = never), the live session used to suspend after 14 idle minutes.

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
