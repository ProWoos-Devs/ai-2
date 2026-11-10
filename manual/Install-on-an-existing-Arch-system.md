**An installation on Arch Linux, or on a system built on it such as Manjaro, is not supported.** AI-2 is Artix Linux with runit. It uses no systemd and ships nothing for it. Arch and the systems built on it run systemd, so a computer set up this way is not AI-2 and has moved away from Artix. What follows from that:

* Nothing here is tried on Arch before a release.
* The settings AI-2 applies at every start of the computer do not run. `ai-2 init --apply` applies them once, and they are gone at the next start.
* The processor guard, which keeps an old laptop from overheating during AI work, does not run.
* `ai-2 doctor` gives a warning that the installation is not supported.
* Questions and bug reports about such an installation are not answered.

For a supported system, use the ISO ([[Installation]]) or an existing Artix system with runit ([[Install on an existing Artix system]]).

The packages come from the same signed pacman repository, and the steps are the same as on Artix.

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

`ai-2 init --apply` also installs the engine by itself, so the middle line is optional. From here, [[First Steps]] describes the tool; what it says about the system itself applies to Artix.

## Undoing the tuning

`sudo ai-2 init --revert` undoes a previous `--apply` from its manifest. It never removes packages.
