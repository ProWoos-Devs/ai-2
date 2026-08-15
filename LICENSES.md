# Licenses

AI-2 is released under the MIT License (see `LICENSE`). Two pieces of this tree were not written by the AI-2 project and keep their original terms:

- `iso/profiles/ai2/root-overlay/usr/bin/artix-service` is a modified copy of the `artix-service` script from Artix Linux (package `base`, https://www.artixlinux.org), which Artix distributes under the GPL. The AI-2 modification (linking runit services into `/etc/runit/runsvdir/default` so enabling works inside the installer chroot) is offered under the same license.

- `iso/profiles/ai2/` started as a copy of the `xfce` profile from Artix's artools `iso-profiles` (https://gitea.artixlinux.org/artix/iso-profiles), BSD 2-Clause License, Copyright (c) 2017, Cromnix GNU/Linux. That notice is retained here as the license requires; the AI-2 additions to the profile are MIT like the rest of the project.

The packages built from `packaging/` carry their upstream licenses, llama.cpp is MIT (its LICENSE file ships in each `ai2-llama-cpp-*` package).
