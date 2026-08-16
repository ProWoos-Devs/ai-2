# Licenses

AI-2 is released under the MIT License (see `LICENSE`). Two pieces of this tree were not written by the AI-2 project and keep their original terms:

- `iso/profiles/ai2/root-overlay/usr/bin/artix-service` is a modified copy of the `artix-service` script from Artix Linux (package `base`, https://www.artixlinux.org), which Artix distributes under the GPL. The AI-2 modification (linking runit services into `/etc/runit/runsvdir/default` so enabling works inside the installer chroot) is offered under the same license.

- `iso/profiles/ai2/live-overlay/usr/share/grub/cfg/grub.cfg` and `kernels.cfg` are modified copies of the live boot menu scripts from Artix's `artix-grub-live` package (https://gitea.artixlinux.org/artix/artix-live), GPL. The AI-2 modifications (a single "Start AI-2" entry, listed first and preselected) are offered under the same license.

- `iso/profiles/ai2/` started as a copy of the `xfce` profile from Artix's artools `iso-profiles` (https://gitea.artixlinux.org/artix/iso-profiles), BSD 2-Clause License, Copyright (c) 2017, Cromnix GNU/Linux. That notice is retained here as the license requires; the AI-2 additions to the profile are MIT like the rest of the project.

- `iso/profiles/ai2/root-overlay/usr/share/grub/themes/artix/dejavu-sans-mono-*.pf2` are GRUB font files rendered from DejaVu Sans Mono (https://dejavu-fonts.github.io), which is distributed under the Bitstream Vera Fonts license with the Arev/DejaVu additions in the public domain. The rest of the AI-2 GRUB theme in that directory (background, pixmaps, icons, theme.txt, sources in `branding/grub-theme/`) is MIT; the generic glyph icons come from Artix's `artix-grub-theme` package at build time and are not part of this tree.

The packages built from `packaging/` carry their upstream licenses, llama.cpp is MIT (its LICENSE file ships in each `ai2-llama-cpp-*` package).
