AI-2's promises are tested on real, old machines, not just in virtual machines. This page lists the hardware AI-2 has been validated on. Ran it on something else? Share the machine and its score in [Discussions](https://github.com/ProWoos-Devs/ai-2/discussions).

## 2011 HP Pavilion g4 (the reference old machine)

AMD A4-3305M (no AVX, not even SSE4.1), 4 GB of RAM, spinning disk. [[Light tier|Capability Tiers]], AI Score 29-30.

This is the oldest validated target and the machine that shaped AI-2's honesty rules. It runs the `baseline` (pure SSE2) engine build, and measured speeds there (2 threads, 150-token workload):

| Model | Measured speed |
|---|---|
| Gemma 3 270M | 4.5 tok/s |
| Qwen2.5 0.5B | 1.8-2.0 tok/s |
| Qwen3.5 0.8B | 1.0 tok/s |

Chat in the browser runs at about 1.45 tok/s, patience mode, but genuinely local and genuinely working. BIOS/MBR installs, dual boot alongside Windows 7 included, are verified on this machine.

## 2016 Acer ES1-522

Standard tier, AI Score 23, and proof that a newer machine is not automatically a faster one, it scores below the 2011 laptop despite five more years and more RAM. Installing on it surfaced two real-hardware fixes that ship since ISO 20260825, steering its 2012-2016-era AMD GPU to the radeon driver (amdgpu probe-crashes on that generation and left the screen black), and releasing leftover swap partitions before the installer runs.

## Virtual machines

Every ISO release is verified by complete QEMU installs before it ships, on BIOS and, since ISO 20260821b, on UEFI (OVMF with a GPT disk and an EFI system partition), including first login, the setup wizard and chat.

## What "validated" means

Not "it booted once". The release checklist includes a full installer run, the installed system booting to the branded login, the first-login wizard completing, tuning applying and surviving a reboot, and `ai-2 chat` answering in the browser.
