On an installed system, start with `ai-2 doctor`, which checks the engine, model, tuning, services and repository key. For a bug report, `ai-2 report` writes `~/ai2-report.txt` to attach to an [issue](https://github.com/ProWoos-Devs/ai-2/issues). Questions and ideas go to [Discussions](https://github.com/ProWoos-Devs/ai-2/discussions).

## Booting the stick

**The computer refuses to boot the stick and mentions Secure Boot.** Turn Secure Boot off in the firmware setup (the key shown at power-on, often F2, Del, F10 or Esc). The image is not signed for Secure Boot.

**The screen stays black after the boot menu.** Reboot and pick "Start AI-2 (safe graphics, if the screen stays black)". Since ISO 20260825, AMD GPUs of the 2012-2016 era (SI/CIK) are steered to the mature radeon driver automatically, because the newer amdgpu driver probe-crashes on them under current kernels.

**Is my machine too old?** Above the floor (a 64-bit x86_64 CPU, 2 GB of RAM, about 6 GB of disk) AI-2 does not turn a computer away. CPUs without AVX or even SSE4.1 are served by dedicated engine builds, see [[Validated Hardware]]. 32-bit machines are not supported, and the boot menu says so.

**Is the download corrupted?** Verify with `sha256sum -c ai-2-x86_64.iso.sha256`, and use the boot menu's "Check this stick first" entry to verify the written stick.

## Installing

**"Erase disk" is missing in the installer.** Fixed in ISO 20260825. Older ISOs activated any swap partition found at live boot, which made the installer refuse whole-disk installs on machines that previously ran Linux. With an older ISO, run `sudo swapoff -a` in a terminal before starting the installer, or download the current ISO.

**An install made with ISO 20260816 or 20260817 boots to a text-mode GRUB without Windows in the menu.** Those two ISOs lost Artix's GRUB defaults. On an affected install, set `GRUB_DISABLE_OS_PROBER=false` in `/etc/default/grub`, then run `sudo grub-mkconfig -o /boot/grub/grub.cfg`. ISOs from 20260819 on are fixed.

## Using the AI

**The chat page says "Not Secure".** Expected. The page is served by your own computer at 127.0.0.1, nothing leaves the machine, there is nothing to secure.

**The chat page shows an error the first time.** Reload it. On a slow disk the server needs a moment to load the model.

**The AI engine crashes instantly ("illegal instruction").** With the one `ai2-llama-cpp` package this should not happen, the engine picks the CPU build at start (x64 as the floor) and every file that must run on a pure-SSE2 machine is checked before it ships. If it does happen, run `ai-2 report` and attach `~/ai2-report.txt` to an issue; it says which module was loaded. A machine still on one of the old per-CPU packages (`ai2-llama-cpp-baseline`, `-noavx`, `-avx2`) gets the new package with the next update.

**Why does the benchmark download a model I did not ask for?** The [[AI Score|AI Score and Benchmarks]] is always measured on one fixed model so scores stay comparable across machines. Benchmarking whatever model happens to be present would produce incomparable numbers, so AI-2 refuses to.

**Why is the recommended model so small? I have the RAM for a bigger one.** RAM says what fits, not what runs. The recommendation is gated by measured speed, and AI-2 would rather tell you a big model is unusably slow on this machine than pretend, see [[Models]].

## Updates

**A bubble says updates are available, and Software Updates then has nothing to install.** Fixed in ai-2 0.19.3. In earlier versions, an update check that was running while updates were being installed could save its old count afterwards, and the bubble repeated that count at the next logins. It clears by itself within a day. To clear it at once, run `ai-2 update-check` in a terminal, which checks again and answers "The system is current."

**Does an update finish by itself?** The packages do, at once. What a package cannot reach is each account's own files under its home directory, so since the version after 0.19.3 a release can ship a migration for those (`migrations/README.md` in the repository says what one may do). `ai-2 update` runs the pending ones after the upgrade, and every login runs them for the account logging in, silently, so an update made through Software Updates is finished the next time you log in. `ai-2 migrate --pending` lists what is waiting, `ai-2 migrate` runs it, and `ai-2 doctor` reports it. A migration never asks for a password and only touches that account's files.

**`sudo pacman -Syu` asks me about a Broadcom driver.** This computer has the `broadcom-wl` or `broadcom-wl-dkms` package. A plain upgrade can swap the driver for the dkms build without the kernel headers it needs, and the WiFi is gone after the reboot. `ai-2 update` checks that first (it removes a wl driver the machine has no chip for, or adds the headers), so answer no and run `ai-2 update`, or use Software Updates. On a machine without that package pacman runs exactly as before.

## Crashes

**A bubble said a program stopped unexpectedly.** The kernel tells AI-2 when a program crashes (an illegal instruction, a memory access error, an abort), and the desktop says so once, at the next login round of the update check. Only the program's name, the signal and the time are kept, in `/var/lib/ai2/crashes.log`; no memory dump is written and nothing leaves the computer. `ai-2 crashes` lists the last 7 days with a sentence on what to do, and `ai-2 doctor` carries the same as a check. One case AI-2 can explain on its own: the AI engine stopping with an illegal instruction means its build does not fit this CPU, and the message says to run `ai-2 doctor` and, if it finds nothing wrong, to send `ai-2 report`.

**I do not want crashes recorded.** Put a file after ours in `/etc/sysctl.d/`, for example `/etc/sysctl.d/99-no-crash-record.conf` with the line `kernel.core_pattern = core`, and run `sudo sysctl --system`. `ai-2 doctor` then says the records are off.

## Remote access

**Getting help from someone remotely, in the live session.** Double-click "Remote help (SSH)" on the live desktop, it shows the exact command and password the helper types on their computer. Only machines on your own network can connect, and it ends at shutdown.

**SSH on an installed system.** Off by default. To allow it:

```
sudo ln -s /etc/runit/sv/sshd /run/runit/service/
```
