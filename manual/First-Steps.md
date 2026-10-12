## The setup wizard

At your first login a window titled "AI-2 setup" opens by itself and walks you through everything. It appears together with the desktop, says "AI-2 setup is starting, please wait..." and begins a few seconds later. It speaks English, Spanish or German, following the language you picked in the installer. It scans the computer, tunes the system for its [[tier|Capability Tiers]] (asks for your password once), installs the AI engine build for your CPU, measures what the machine can really do (the [[AI Score|AI Score and Benchmarks]]), recommends a model that fits and offers to download it. A few minutes, three questions.

The wizard finishes even without a network. It tunes the machine and installs the engine, then says the model and AI Score are pending and offers to come back when you are online. It keeps a transcript (`wizard.log`) and a report (`wizard.json`), and a re-run opens with a one-line summary of what the last run did.

If you closed it, run it again any time:

```
ai-2 wizard
```

Unattended setup runs with `ai-2 wizard --yes`.

## Chat right away

A small starter model (Gemma 3 270M, about 242 MB) comes on the ISO, so you can chat the moment the install finishes, even offline. It is fast and light, but it is not the smartest model, sub-1B models are fluent but unreliable on facts and arithmetic. Once you are online, AI-2 measures your machine and can fetch a model that genuinely fits it, see [[Models]].

Open the chat with **Applications > AI-2 Chat**, or in a terminal:

```
ai-2 chat
```

It starts the local AI and opens the chat page in the browser. The AI stops by itself when you have not used it for a while, or stop it now with `ai-2 stop`.

The address bar says "Not Secure" because the page is served by your own computer at 127.0.0.1. Nothing leaves the machine, there is nothing to secure. If the page shows an error the first time, reload it.

On a low-end PC the better way is **Applications > AI-2 Chat (Terminal)**, or:

```
ai-2 chat --terminal
```

Same AI, no browser around it, so it appears faster and leaves the browser's memory free for the model. It also works over SSH, and is what `ai-2 chat` uses automatically when there is no graphical display. Enter sends, `/new` starts a fresh conversation, Ctrl-C during an answer stops just that answer.

## The same steps by hand

```
ai-2 detect          # what AI-2 sees: CPU, RAM, GPU, disk, init system
ai-2 tier            # the capability tier assigned to this machine, and why
sudo ai-2 init --apply   # tune the system for the tier
ai-2 benchmark       # measure real speed, compute the AI Score
ai-2 recommend       # which local model fits, and when to go remote
ai-2 model pull      # download the recommended model
ai-2 chat            # start the local AI and open the chat page
```

The full list is on [[Commands]]. Every command has `--help`, and `AI-2` works as a synonym for `ai-2` everywhere.

## Staying up to date

AI-2, the AI engine and the model catalog all update the normal Artix/Arch way, from AI-2's signed package repository that is already configured:

```
sudo pacman -Syu
```

Being based on Artix means a rolling release, you update, you never reinstall for a new version. AI-2 checks for updates passively and tells you when some are waiting.

## Lean by design

AI-2 ships only what it needs, the desktop, a browser, a text editor and the AI engine. Anything you miss is one command away:

```
sudo pacman -S atril          # PDF viewer
sudo pacman -S cups           # printing
sudo pacman -S vlc            # media player
sudo pacman -S libreoffice-still
```
