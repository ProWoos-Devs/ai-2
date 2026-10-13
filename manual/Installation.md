The recommended way to get AI-2 is the ISO, a complete system with Artix Linux (runit), XFCE, the AI engine and the `ai-2` tool, plus a graphical installer. Lean by design, 1.85 GB. To add AI-2 to a Linux system you already have, see [[Install on an existing Artix or Arch system]] instead.

## Requirements

* A 64-bit (x86_64) PC. Very old CPUs are fine, AI-2 ships three builds of the AI engine (llama.cpp) and picks the one your CPU can run, including CPUs without AVX or SSE4.1. The oldest validated machine is a 2011 laptop, see [[Validated Hardware]].
* 2 GB of RAM minimum (4 GB recommended). More RAM unlocks larger models, see [[Capability Tiers]].
* About 6 GB of disk for the system, plus room for models (the smallest is about 0.4 GB, the largest in the catalog about 5 GB).
* BIOS or UEFI boot, with Secure Boot off (the image is not signed for it).
* Internet is not needed to install, only later for models and updates. A small model comes on the ISO, so a fresh install can chat offline.

## 1. Download and verify

Download the latest ISO and its checksum:

* [ai-2-x86_64.iso](https://github.com/ProWoos-Devs/ai-2/releases/latest/download/ai-2-x86_64.iso)
* [ai-2-x86_64.iso.sha256](https://github.com/ProWoos-Devs/ai-2/releases/latest/download/ai-2-x86_64.iso.sha256)

Every release is also kept under its build date on the [Releases page](https://github.com/ProWoos-Devs/ai-2/releases), and mirrored on [SourceForge](https://sourceforge.net/projects/ai-2/).

Verify the download:

```
sha256sum -c ai-2-x86_64.iso.sha256
```

To check the signature on that checksum too, and the key it was made with, see [[Verifying and Pinning|Verifying-and-Pinning]].

The boot menu also has a "Check this stick first" entry that verifies the written stick itself.

## 2. Write the USB stick

Use a stick of 4 GB or more, or burn a DVD. Everything on the stick is erased.

Linux or macOS (replace `sdX` with the stick's device):

```
sudo dd if=ai-2-x86_64.iso of=/dev/sdX bs=4M conv=fsync status=progress
```

Windows: Rufus or balenaEtcher in their default mode.

## 3. Boot the live desktop

Boot the computer from the stick (the boot-device key is shown at power-on, often F12, Esc or F9; Secure Boot is turned off in the firmware setup, often F2, Del or F10). The stick starts a live desktop that logs in by itself (user `ai-2`, password `ai-2`) without touching your disks. `START-HERE.txt` on that desktop explains everything, with `EMPIEZA-AQUI.txt` (Spanish) and `START-HIER.txt` (German) next to it.

* If the screen stays black, reboot and pick "Start AI-2 (safe graphics, if the screen stays black)" in the boot menu.
* If someone is helping you remotely, the "Remote help (SSH)" desktop icon starts SSH and shows exactly what the helper types on their computer. Only machines on your own network can connect, and it ends at shutdown.

## 4. Install

Back up anything you care about first, installing can erase a disk. Then double-click "Install AI-2". The installer opens with a language choice (English, Spanish and German are fully translated, and the installed system follows what you pick), then asks for location, keyboard, partitions, and your user. For the partitions step:

* **Erase disk** uses the whole disk for AI-2 (everything on it is lost).
* **Install alongside** keeps an existing system (for example Windows), lets you shrink it to make room, and gives you a boot menu.
* **Manual** is for people who know their partitions.

Windows lives on NTFS partitions, a Linux system shows under its own name, and AI-2 labels its own partition "AI-2". When in doubt, the size tells partitions apart.

Read the summary page (the last moment to go back), install, tick "Restart now", and remove the stick when asked. The installed system boots to the AI-2 login screen. Continue with [[First Steps]].

### Installing for someone else

When the computer is for another person (a relative, a refurbished machine), double-click "Install for someone else" instead. The installer runs the same steps without the Users page. The first time the computer starts, it asks the owner for a name, a login name, a password and the computer's name, in the language you picked in the installer, then restarts; the login screen asks for that password and the usual first-login setup follows. Until the owner has answered, the computer logs a temporary account into that question by itself; the account has no password, can run nothing but the question, and is removed with the answer. Nothing of the installer's stays on the machine. The command behind it is `ai-2 owner-setup`.
