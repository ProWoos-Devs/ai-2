# Changelog

All notable changes to AI-2: the `ai-2` tool (semantic versions, matching the `ai-2` pacman package) and the AI-2 ISO (date snapshots, `artix-ai2-runit-YYYYMMDD-x86_64.iso`, each tagged `iso-YYYYMMDD` in git at the commit it was built from). Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.13.1] - 2026-09-05
### Changed
- **Broadcom, final shape (decision 2026-09-05, supersedes the 0.13.0 installer job).** `broadcom-wl` is gone from the live stick as well, and the Calamares job that copied it into the target is removed. The QEMU install of the never-released ISO 20260905 showed why: Artix's prebuilt `broadcom-wl` (built 2026-08-22) carries a module for kernel 7.1.9 while the repos ship kernel 7.2.2, so the driver was dead weight on the stick and in the target alike, and the package is abandoned upstream in favor of dkms. Broadcom chips that the in-kernel brcm80211/b43 drivers do not cover get WiFi with `ai-2 install broadcom-wifi` after connecting by cable once; the wizard says so on such a machine and the guides are worded accordingly. `ai-2 update` (0.12.0) still cleans up installs from older ISOs.

## [0.13.0] - 2026-09-05
### Changed
- **Broadcom, steps 2 to 4 of the plan.** `broadcom-wl` leaves the installed package set and stays on the live stick only (ISO profile). The stage script also puts the prebuilt package FILE on the live medium (`/usr/share/ai2/pkgs/`), and a new Calamares job (`shellprocess@broadcom`, right after the keyring job, offline and online configs) installs it into the target only when sysfs shows a Broadcom WiFi device (class 0x028000, vendor 0x14e4), so such a laptop has WiFi at first boot with no download; `ai-2 update` (0.12.0) then carries it over to the dkms driver. Machines without the chip never carry the package again. Test hook: `touch /run/ai2-force-broadcom` on the live system.
### Added
- `ai-2 install broadcom-wifi` = `broadcom-wl-dkms` plus the headers package of the installed kernel (`linux-headers`, `linux-lts-headers`, ...). The wizard names it when it finds a Broadcom WiFi chip without the wl driver and offers to install it when online. Detection falls back to sysfs when pciutils is absent. Guides mention it in the three languages.

## [0.12.0] - 2026-09-05
### Added
- **Broadcom wl migration for installed systems** (`ai2/broadcom.py`, step 1 of the Broadcom plan). ISOs up to 20260830 install `broadcom-wl`; Artix now ships `broadcom-wl-dkms` with `Replaces: broadcom-wl`, and libalpm looks for a replacer before the package itself, so every such install swaps at its next `-Syu`, pulls 292 MiB of build tools and fails to build for lack of kernel headers (rafaminu-pc, 2026-09-03). `ai-2 update` now runs a preflight: no Broadcom WiFi device (lspci class 0280, vendor 14e4), the wl package is removed first; a Broadcom device, the kernel's headers package joins the upgrade so the dkms build succeeds. `ai-2 doctor` reports the same condition with the fix line. Known limit, stated plainly: a plain `pacman -Syu` or pamac still swaps on an existing install's first update, and the ai-2 package carrying the preflight arrives in that same transaction; the next `ai-2 update` or doctor cleans up.

## [0.11.1] - 2026-09-05
### Fixed
- **The update bubble now fires on a machine that is never logged out.** The desktop autostart ran `ai-2 update-check` once, three minutes after login, and never again; rafaminu-pc sat through a whole day and two releases without a check (2026-09-04). `ai-2 update-check --every HOURS` keeps checking for the life of the session (the autostart uses `--every 6` with `--max-age 20`, so a real check runs about once a day) and on those later rounds raises the bubble only when a fresh check found something, so a bubble still on screen is not stacked.
### Changed
- **Tier tuning is recovery-safe and reversible** (public PR #2). The manifest records the original enabled/disabled state of every service AI-2 touches (v2, v1 manifests migrate), so `init --revert` re-enables what a tier policy disabled and never disables a service that was on before AI-2; recovery state is written before the root-level change, files and the manifest atomically; an already-enabled provider is not re-claimed; a tier change reconciles zram and zswap both ways (the boot helper disables stale zswap on zram tiers).
- **Persistent tiers keep the server** (public PR #4). Standard and above declare `service: persistent` and now resolve to no idle timeout: `ai-2 chat` leaves the server loaded until `ai-2 stop`. Tiny and Light keep their timeouts. Creator drops the `gpu_offload: auto` setting nothing read; README states the packaged runtimes are CPU-only today. Guides qualified accordingly.
- README: install with `pacman -Syu` (a bare `-Sy <pkg>` is a partial upgrade); Status section brought up to date (public PR #3, README part; its PKGBUILD changes were not taken, fakeroot is needed by checkupdates and pamac stays a hard dependency by the 2026-09-03 decision).

## [0.11.0] - 2026-09-04
### Added
- **`ai-2 workflow list | info | install | status`, the Workflow Engine's first user-facing piece.** Three profiles ship in `ai2/data/profiles/` (chat, translation, documents): each requests capabilities, the tier grants a subset, and the AI Score's per-capability stars must clear the profile's `minimum`. Verdicts are honest and never a bare refusal: ready, needs setup, via remote AI (a profile with `remote: true` on a machine with `ai-2 remote` set up), too slow here (with `ai-2 remote set` named as the way out), not on this tier. `install` is read-only toward the system in this version: it downloads the models and prints the exact `sudo pacman -S --needed` line for the packages. Translation is LLM-only (no argos-translate packaging); documents = tesseract + eng/spa/deu data + poppler + img2pdf, names verified against the Artix world repo. Decisions of 2026-09-04 in `000/20260825-workflow-engine-plan.md`.
### Changed
- The reference profile moved from `profiles/` to `ai2/data/profiles/` so it ships in the package, and its schema gained `minimum`, `remote` and `usage`.

## [0.10.0] - 2026-09-04
### Added
- **Remote inference, the sentence `ai-2 recommend` has printed since 0.1.0 finally has something behind it.** `ai-2 remote set <url> [--api-key KEY | --api-key-stdin] [--model NAME] [--default]` saves an OpenAI-compatible endpoint (another computer running `ai-2 serve --host 0.0.0.0 --api-key KEY`, or an API provider) in `~/.config/ai2/remote.json` (mode 600); `show`, `test`, `default on|off`, `clear`. `ai-2 chat --remote` talks to it: a llama-server remote gets its own chat page opened in the browser, anything else is the terminal chat with the key and model on the request. Never silent: a remote is used only with `--remote` or after `remote default on` (`--local` goes back), and every remote chat starts by saying where the messages go. The wizard and `ai-2 recommend` point at it whenever the score says "use remote". Guide section in the three languages.
- The AI is told what it is. A short system prompt (`ai2/persona.py`) names AI-2, the model, what it can do and that it runs offline; the browser page gets it as the web UI's default system message (`llama-server --ui-config`, applied on a browser's first visit, a browser with saved chat settings keeps them) and the terminal chat opens every conversation with it. Before, "what are your capabilities" got the vendor's boilerplate ("I am a large language model trained by Google").
- `ai-2 chat --model` (short form `-m`) and `ai-2 serve --model` with no value show a numbered list of the models on this computer and let you pick one (Enter takes the recommended one). Found on rafaminu-pc 2026-09-04: the score-picked Gemma 3 270M could not answer "what are your capabilities", the Qwen2.5 0.5B already on disk could, and switching meant knowing the catalog id.

## [0.9.0] - 2026-09-03
### Changed
- **One menu, Applications > AI-2.** The four AI-2 entries (Chat, Chat (Terminal), Guide, Software Updates) were tagged `Utility;Office;` and `System;`, so XFCE filed them under Accessories, Office and System, and a user reading "Applications > AI-2 Chat" in the guide found nothing at the top level (rafaminu-pc, 2026-09-03). Every entry now carries the single `X-AI2` category and a merged menu file (`/etc/xdg/menus/applications-merged/ai2.menu` plus `ai2.directory`) gathers them into one submenu right after Accessories. The directory is the one garcon 4.20 actually reads for `xfce-applications.menu`; under the spec-suggested `xfce-applications-merged/` the entries land in "Other", checked with garcon itself. The live stick's "Remote help (SSH)" joins the submenu.
- **pamac is a hard dependency of `ai-2`** instead of an optional one. A machine installed before ISO 20260830, or one that never pulled the optional package, had a guide promising "Add/Remove Software" and a Software Updates entry that hid itself. Updating to 0.9.0 installs pamac (4.54 MiB on our image, everything else it needs is already there).
- The three guides and the three START-HERE texts now name the real paths: Applications > AI-2 > ... for AI-2's own entries and Applications > System > Add/Remove Software for pamac's.
### Fixed
Eleven findings from a whole-tree review of the `ai2` package (2026-09-03), all small, none a crash:
- The screen-reader and audio-server probes gave up on the first failed `pgrep` instead of trying the next candidate, so a hiccup probing orca hid a running espeakup, and one on pipewire hid pulseaudio.
- The wizard declared itself done (and wrote the setup marker) when the benchmark model's download failed while online; the score is now left pending and the wizard comes back.
- `ai-2 stop` on a state file without a pid would have sent SIGTERM to its own process group, the terminal included; pids below 1 are now "no server". After its 30 s deadline `ai-2 stop` also escalates to SIGKILL (the process group when the wrapper leads one) before dropping the record, so a second `ai-2 stop` never says nothing is running while the model still holds RAM.
- `ai-2 doctor` reported "system is current" when checkupdates failed (exit 1, offline), and was the one place suggesting `sudo pacman -Syu`; the wizard's closing update line had the same exit-code blindness. Both now go through the same check the login hint and the desktop bubble use, which also warms that cache.
- `ai-2 serve --host ::1` built an unbracketed IPv6 poll URL, so the wrapper never saw its own server as up and shut it down as idle about 25 minutes in regardless of traffic.
- `ai-2 chat` said "stops after 0 s" for `--idle-timeout 0` and quoted the default timeout when a server was already running; it now says what it knows.
- `ai-2 serve` read the server record twice in a row (a narrow race that turned a clean error into a traceback), the package backends' `pacman -Q` / `dpkg -s` queries had no timeout, `capability_stars` carried a `ram_gib` argument it never read, and the wizard kept a duplicate of `models.benchmark_model` that only a test called.


## [0.8.1] - 2026-08-30
### Changed
- The update notification stays on screen until it is dismissed. It used to take xfce4-notifyd's default lifetime and disappear after about ten seconds, which was merely annoying while the only way to act on it was typing a command, and became wasteful in 0.8.0 when the bubble gained a button that does the whole job in one click. One had already fired unseen on a real machine (rafaminu-pc, 2026-08-26).
  Measured on the shipped image rather than assumed: the default bubble was gone within 45 s while `-t 0` and urgency critical both survived. AI-2 uses `-t 0`, the spec's "never expire", because a pending update is not a critical alert and critical urgency would also override Do Not Disturb.
  A button needs a client alive behind it for as long as the bubble is up, which was also measured: kill notify-send and the bubble's button stops doing anything and the bubble simply vanishes when clicked. So `notify()` forks the holding process and returns at once, which keeps `ai-2 update-check` usable from a terminal, and there is deliberately no timeout on the holder, since any cap would turn a still-visible bubble into a dead one. Without a button (no graphical package manager installed) nothing needs holding and no process is forked.

## ISO 20260830 (2026-08-30), tag `iso-20260830`
Ships `ai-2` 0.8.0 and adds **pamac** to the image, so a freshly installed machine has both a guide to read and a window for installing software and updating. 1,968,680,960 bytes (1.833 GiB, still inside GitHub's 2 GiB asset limit), sha256 `19967d20bb6ebd96ffeee36257594731de1d0e1091460492765a8d72c9d39b12`.

Verified by a complete QEMU install (erase disk, BIOS) and first boot:
- `AI-2-GUIDE.txt` on the desktop after the first login, and Applications > System carrying both "Add/Remove Software" and "Software Updates".
- The wizard's closing block showing the three new lines (more programs, update everything, the guide).
- **pamac's polkit authentication works under runit and elogind**, which was the one real risk in shipping it: `pamac install` printed `==== AUTHENTICATING FOR org.manjaro.pamac.commit ====`, took the user's password, and completed the transaction (refreshing `ai2.db` on the way, so the signed repo is reached from the installed system).
- `ai-2 install printing` installed cups, system-config-printer and cups-runit, then enabled the service: the `runsvdir/default/cupsd` symlink exists and `sv status` reports `run: cupsd: (pid 2185)`.
- pamac's update tray is hidden and not running (our pacman hook applied it during the rootfs build, so it ships that way rather than being fixed on first boot).

The image also grew by ~13 MB for a reason unrelated to any of this: Artix moved appstream 1.1.6 to 1.2.0, which added a libvips dependency (libvips, cfitsio, fftw, imath, libcgif, libimagequant, openexr, openjph, ~75 MiB installed). pamac itself is 4.54 MiB installed, all of its other dependencies were already on the image.

## [0.8.0] - 2026-08-30
### Added
- A guide for the **installed** system, and a way to reach it. START-HERE.txt was written for the USB stick and stopped being the right document the moment the machine rebooted, and nothing on the installed desktop pointed at any document at all. `AI-2-GUIDE.txt` (with `AI-2-GUIA.txt` and `AI-2-ANLEITUNG.txt`) covers the computer the user now has: what it can do, talking to the AI, adding software, updating, what to do when something is wrong, accessibility, remote access. It lands on the desktop at the first login in the system language, sits in the menu as "AI-2 Guide", and prints with `ai-2 guide` (`--open` for the text editor, `--lang` to pick a language), so it is readable over SSH and through a screen reader.
- `ai-2 install`: the plain-language answer to "how do I get an office suite". Short names (office, pdf, media, photos, image-editor, browser, archives, printing, scanner, usb-disks) map to what Artix actually calls those packages, anything else is passed straight through, and the exact pacman command is printed before it runs. A daemon's service is enabled afterwards, which is the step that makes the difference between installing cups and being able to print on runit.
- `ai-2 update`: one command for AI-2, the AI engine, the model catalog and the whole system, because on a rolling release they are one thing. It prints the command it runs, and says what to do when signatures fail.
- **pamac on the ISO**, Artix's own package of Manjaro's Add/Remove Software, which is what "a clear way to install things" looks like with a mouse. It costs two packages and 4.5 MiB installed: gtk4 and libadwaita already come with epiphany, polkit and the polkit-gnome authentication agent with xfce4-session (measured against the profile's package closure, not estimated). A "Software Updates" menu entry opens it on its updates page, and hides itself through TryExec where pamac is not installed.
### Changed
- The update notification now carries a button that opens the graphical updates page, and both it and the login-shell hint point at `ai-2 update` instead of `sudo pacman -Syu`. The bubble, its button and the spoken version are translated into Spanish and German (`ai2/updates.py` joined the catalog coverage test), and a libnotify without `--action` support falls back to the plain bubble instead of showing nothing.
- The wizard's closing block ends with the three things a new user needs next: more programs, updating, and the guide.
- pamac's own update tray is hidden on AI-2 (a pacman hook re-applies it after every pamac upgrade, since the file belongs to pamac). AI-2 already notifies, accessibly, and a second permanent GTK process is not what a 2 GB machine needs.

## [0.7.1] - 2026-08-27
### Fixed
- Spoken output actually makes sound on a stock install: the lean system runs no PulseAudio/PipeWire session server (runit has no systemd user units to start one), and speech-dispatcher's default output played into the void while exiting 0. Found by capturing the VM's audio to WAV in the 0.7.0 release verification: 0 bytes despite clean exits, while direct ALSA produced audio. Now `ai-2 accessibility setup` writes `AudioOutputMethod "alsa"` into the user's speechd.conf when no audio server runs (this is also what makes Orca audible, same daemon), and `--speak`/spoken notifications fall back to espeak-ng straight to ALSA when speech-dispatcher has no working audio path, choosing by observable state, never by spd-say's return code.

## [0.7.0] - 2026-08-26
### Added
- Accessibility, first installment (accessible chat on installed systems; plan in the workspace, decisions of 2026-08-26):
  - The terminal chat and the wizard now print whole lines only, no token-by-token repaints, no `\r` progress redraws, no dot spinners: screen readers, locally and over SSH, only follow completed lines, and at local-model speeds the sighted cost is nil. `ai-2 chat --terminal --stream` (or `AI2_CHAT_STREAM=1`) restores token streaming.
  - Spoken chat: `ai-2 chat --terminal --speak` speaks each answer sentence through speech-dispatcher in the system language, queued in order without blocking the token stream.
  - When a screen reader (Orca or espeakup) is running, `ai-2 chat` opens the terminal chat instead of the browser page, which is llama-server's own UI and not ours to make accessible.
  - The update notification is mirrored to speech when a screen reader is running; the visual bubble expires in seconds and was easy to miss even sighted.
  - `ai-2 accessibility` shows the screen-reader status of the machine; `ai-2 accessibility setup` installs orca, speech-dispatcher and espeak-ng (one sudo prompt) and wires the assistive-technologies flag, Orca autostart and a Super+Alt+S Orca shortcut for the current user. Opt-in only; nothing is added to the ISO and sighted installs are untouched.

## ISO 20260826 (2026-08-26), tag `iso-20260826`
Ships `ai-2` 0.6.1 (the 0.6.0 batch plus the same-day fixes below). Installer changes: the slideshow and welcome page speak Spanish and German, the welcome page switches language the moment one is picked (including the guide button, which then opens EMPIEZA-AQUI/START-HIER), and the GRUB menu no longer stretches on widescreen panels (gfxmode auto-first, the logo as a fixed-size image, reduced). Verified by two complete QEMU installs, one in Spanish and one in German, each through first boot, the localized wizard, tuning apply, benchmark, and a real `ai-2 chat --terminal` conversation against llama-server (the German run declining the recommended download to exercise the 0.6.1 fallback).

## [0.6.1] - 2026-08-26
### Fixed
- Declining the recommended model download no longer blocks chatting: `ai-2 chat`/`serve` now fall back to the best model already on disk when the recommendation's file is absent, instead of refusing with "not set up". Found live in the 20260826 ISO verify (score 88 recommended Qwen3 1.7B, the download was declined, and chat refused despite two models being installed); regression-tested.
### ISO profile (next build)
- The installer welcome page now switches language immediately when one is picked: Calamares never retranslates loaded QML (checked upstream sources, stock welcomeq has the same flaw), so every visible string binding re-evaluates via a counter bumped on the language change. Before this, the page that offers the language choice stayed English, and its guide button opened the English guide.

## [0.6.0] - 2026-08-26
### Added
- `ai-2 chat --terminal`: chat with the same local AI in the terminal, no browser around it. Stdlib-only client streaming from the unchanged `ai-2 serve`, so it is the fastest to appear and the lightest next to the model (the browser's memory stays free for inference), and it works over SSH. Used automatically when there is no graphical display. `/new` starts a fresh conversation; Ctrl-C during an answer stops only that answer. Speaks Spanish and German like the wizard.
- A second menu entry, "AI-2 Chat (Terminal)", with localized names and comments saying it is the fastest and lightest way and recommended on low-end PCs; the browser entry's comment points slow-PC users at it. The wizard's closing "how to use it" block is now tier-aware: on the on-demand (low-RAM) tiers it recommends the terminal chat first. START-HERE explains both options in all three languages.
- The START-HERE guide in Spanish (`EMPIEZA-AQUI.txt`) and German (`START-HIER.txt`): packaged to `/usr/share/doc/ai2/`, placed on the live desktop below the English guide (next ISO build), and pointed to from the top of the English guide, which now also says the live session is English while the installed system follows the language picked in the installer.
- The setup wizard and the AI Score display speak Spanish and German, following the system locale the installer sets. Deliberately not gettext: JSON catalogs under `ai2/data/i18n/` keyed by the exact English text, `tr()` in the new `ai2/i18n.py` falls back to English for any missing key, and CI enforces that every wizard template exists in every catalog with matching placeholders (the yes/no prompt already accepted sí/ja/nein).
- `ai-2 profile`: one view of everything AI-2 knows about the machine (hardware, assigned vs configured tier, AI Score, capability stars), with `--json` for scripts and a future control center. Backed by `machine_profile()` in the new `ai2/profile.py`, which assembles the pieces read-only; where each piece is stored does not change.
- Schema tests for every declarative YAML file (tier definitions, the model catalog, workflow profiles): each file's shape, types and vocabularies are now validated in CI, including the profile rules translation.yml had promised ("narrow, never exceed" on capabilities and context size, and no contradicting data duplicated from the catalog). The first run caught stale qwen3-1.7b sizes in translation.yml, now fixed by referencing the catalog by id.
### ISO profile (next build)
- The GRUB boot menu no longer stretches on widescreen panels: GRUB_GFXMODE is `auto` first (native panel mode when the firmware offers it, 1024x768 fallback), the background is a vignette only, and the logo is a separate fixed-size image that cannot distort, reduced to 0.65 scale (was 0.8). Applies to the live menu and installed systems.
- The installer slideshow and the welcome page's own strings are translated into Spanish and German: every text wrapped in qsTr(), catalogs in the branding component's `lang/` (`calamares-ai2_es/de.ts`, the compiled `.qm` committed alongside; regenerate with qt6-tools' `lrelease`). Calamares applies the language chosen on the welcome page. The welcome page's "Read the guide" button now opens the guide in that language (the file path is itself a translated string).

## ISO 20260825 (2026-08-25), tag `iso-20260825`
Ships `ai-2` 0.5.2 (update notification, real stop, fixed-model-only benchmark, starter-model honesty, Gemma sampling, bare-command help) plus a day of real-hardware fixes from installing on a 2016 Acer ES1-522:
- Reworked installer slideshow: new "chat right away, offline" slide naming the bundled starter model's limits, the `> AI-2` wordmark in the top band of every text slide.
- Wide boxed-banner logo at 85% of the installer sidebar via a QML sidebar in the branding component (the widget sidebar hardcodes an 80x80 logo slot).
- Smaller GRUB menu type (items 20 -> 14 px, hints 16 -> 12) so long entries fit.
- SI/CIK-era AMD GPUs (2012-2016) steered to the mature radeon driver: amdgpu probe-crashes on them under kernel 7.1 and the screen stayed black after GRUB.
- "Erase disk" no longer missing in the installer: the live boot activates any swap partition it finds, which made Calamares refuse whole-disk installs on machines that previously ran Linux; the install launcher now releases all swap first.
- New "Remote help (SSH)" icon on the live desktop: one double-click starts SSH and shows what a helper on the same network should type; explained in START-HERE, whose black-screen tip now points at the safe-graphics menu entry instead of asking the user to type nomodeset.

## ISO 20260824 (2026-08-24), tag `iso-20260824`
Ships `ai-2` 0.5.1 and, for the first time, a bundled model (Gemma 3 270M, `/var/lib/ai2/models/`) so a fresh install chats with no network. 1,955,495,936 bytes (smaller than 20260823 despite the model, because the qcom/marvell firmware trim saved more than the model added). Verified by complete QEMU installs on BIOS and UEFI, the installed system carrying only the CPU's own engine build (the other two pruned), no qcom/marvell firmware, and `ai-2 chat` serving the bundled Gemma before any benchmark. Released on GitHub with the fixed-name assets.


## [0.5.1] - 2026-08-23
### Changed
- The AI Score is now always measured on the fixed benchmark model (`qwen2.5-0.5b`), never on whichever model happens to be present, so scores stay comparable across machines. The wizard separates the ready-to-chat model from the benchmark model: with a model already on disk (for example one bundled on the ISO) it says you can chat straight away and defers the score until the machine is online.
- The wizard checks for updates at the end when online (system, engine and models list all update through `sudo pacman -Syu`) and explains the setup, including that a small model is included for offline use.
- `ai-2 chat` and `ai-2 serve` fall back to the best model already on disk when there is no AI Score yet, so a fresh machine can chat before the first benchmark.
### ISO profile (next build)
- Bundles Gemma 3 270M (about 242 MB) in the installed system, so a fresh install can chat with no network; downloaded and checksum-verified at ISO build time (not stored in git).


## [0.5.0] - 2026-08-23
Second sprint of the 2026-08-21 enhancement review.
### Added
- `ai-2 model list` (what is on the machine and in the catalog, with sizes and the recommended/loaded markers), `ai-2 model rm <id>` (free disk space; refuses a model the server is using), `ai-2 model verify` (SHA-256 against the catalog).
- `ai-2 init --revert`: undo a previous `--apply` from a manifest, restoring the original of any file AI-2 overwrote (kept as `*.ai2-orig`) or removing files it created, and disabling the services it enabled. Never removes packages.
### Changed
- The wizard finishes even without a network: it tunes the machine and installs the engine, then says the model and AI Score are pending and offers to come back. It keeps a transcript (`wizard.log`) and a report (`wizard.json`) in the state dir, and a re-run opens with a one-line summary of what the last run did. The internet check now rejects a captive portal (a login page that answers for every host).
- Benchmark: reads llama-bench's JSON (two repetitions, the spread reported), is time-boxed per CPU class (150 to 300 s) instead of a flat 600 s, and records the runtime build, CPU, kernel and date in the score. The score and the wizard now say in plain words what the speed feels like ("patience mode", "comfortable for chat").
- `ai-2 chat` waits for the server to report "ok", not just an open port (llama-server answers `/health` 200 while still loading). `ai-2 doctor` and `ai-2 report` run under `sudo` look at the invoking user's score and models, not root's.
### ISO profile (next build)
- Drops `linux-firmware-marvell` and `linux-firmware-qcom` (about 257 MB of Chromebook and Snapdragon firmware, useless on an x86_64 ISO for old laptops).
- A Calamares job removes the two CPU engine builds the installed machine cannot use (the ISO still ships all three for offline installs).


## ISO 20260823 (2026-08-23), tag `iso-20260823`
20260821b plus `ai-2` 0.4.1. 1,988,726,784 bytes. Verified by complete QEMU installs on BIOS and UEFI (installed system: ai-2 0.4.1, lsb-release AI-2, GRUB saved/8 s, doctor clean with MGLRU and zram). Released on GitHub with the fixed-name `ai-2-x86_64.iso` assets.


## [0.4.1] - 2026-08-23
### Changed
- The user's D-Bus session bus now starts at `$XDG_RUNTIME_DIR/bus` (`/etc/X11/xinit/xinitrc.d/30-ai2-session-bus.sh`, before Artix's `80-dbus.sh`), the path most desktop components and sandboxes expect, instead of a `dbus-launch` socket under `/tmp`. Note on the record: this was first shipped as a fix for a blank `ai-2 chat` page seen while testing over SSH on the 2011 laptop; after a session restart the blank page could not be reproduced in any configuration, including the original one, and the owner reports the chat always worked from the desktop. The cause of what was seen is not established; the change is kept because it is harmless and standard.


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
