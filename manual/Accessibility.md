AI-2 aims to be usable without sight, with the local AI itself as part of the answer. This page is the honest status, what works today, what needs help, and what is planned. Feedback, corrections, and testing offers are very welcome in [Discussions](https://github.com/ProWoos-Devs/ai-2/discussions).

## What works today

**Chat with a screen reader.** `ai-2 chat --terminal` prints whole sentences, one per line, which screen readers follow naturally, locally in a terminal or over SSH with the reader on your own computer. When Orca is running, the AI-2 Chat menu entry opens the terminal chat automatically instead of the browser page.

**Spoken chat.** `ai-2 chat --terminal --speak` speaks each answer aloud through speech-dispatcher, in English, Spanish or German following your system language. Fast token streaming for sighted users who prefer it: `--stream`.

**One-command setup.** `ai-2 accessibility setup` installs the screen-reader stack (Orca, speech-dispatcher, espeak-ng, one sudo prompt), turns on XFCE's assistive technologies, autostarts Orca at your next login, and binds Super+Alt+S to start or restart Orca. `ai-2 accessibility` shows the current status. This is opt-in; nothing changes on machines that don't ask for it.

**Spoken updates.** When a screen reader is running, the "updates available" notification is spoken, not just flashed as a bubble.

**Everything important is a terminal program.** The setup wizard, chat, `ai-2 profile`, `doctor` and updates all run in a terminal with plain linewise output, and all of it works over SSH, so you can drive an AI-2 machine entirely from another computer with your own screen reader.

## What does not work yet, honestly

**Installation currently requires sighted assistance.** The graphical installer runs as root, which makes it invisible to Orca (an upstream limitation), and the ISO does not yet ship a screen reader for the live session. A sighted person is needed once, for the install itself; after first boot, `ai-2 accessibility setup` makes the installed system yours. We say this plainly rather than promise otherwise.

**The browser chat page is not ours.** It is llama-server's built-in UI; use the terminal chat instead, or Firefox if you prefer a browser with a stronger screen-reader record than the shipped Epiphany.

**The smallest machines get the basics only.** On the Tiny tier (2 GB) there is no voice input and the espeak-ng voice; the AI answers in text at reading speed. The wizard tells you what your machine earned, in the same honest register it uses for model quality.

**The AI can be wrong.** The bundled models are small and can state wrong facts confidently. Nothing the AI says runs commands or changes your system by itself, and it should never be your source for exact numbers, medical or financial facts, or commands to type.

## Planned

Tier-gated natural voices (Piper), a spoken live session on the ISO, and a read-only "ask the machine" voice assistant grounded in the machine's real, deterministic facts. The full plan with its open verification gates lives in the project workspace; items ship only after being verified on real old hardware.

## Testing and feedback

Screen-reader users' reports are worth more than any of our tests. If you can try AI-2, over SSH is a first-class path, say hello in [Discussions](https://github.com/ProWoos-Devs/ai-2/discussions) or open an [issue](https://github.com/ProWoos-Devs/ai-2/issues); attach `~/ai2-report.txt` from `ai-2 report` if something misbehaves.
