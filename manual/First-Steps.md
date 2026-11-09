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

Open the chat with **Applications > AI-2 > AI-2 Chat (Gopher)**, or in a terminal:

```
ai-2 chat
```

It opens the AI-2 Gopher app on the chat page, with no browser. Type your question in the box at the bottom and press Enter. The answer appears line by line, above it, and the conversation stays on the page. On a slow computer the very first answer can take more than a minute. AI-2 then keeps its reading of its own instructions on disk, so later ones start sooner.

Conversations are saved on this computer as you go, in `~/.local/share/ai2/chats/`, and only your account can read them. **Earlier conversations** lists them, and choosing one lets you carry on where you left off. **Delete this conversation** removes it from the disk. A long conversation gets slower, and once it no longer fits the model, the model reads only the most recent part, although the page still shows it all. The terminal chat saves nothing.

**Search Knowledge Packs**, under the box on the chat page, looks things up in the Knowledge Packs on this computer without asking the AI, and needs no internet. Choose **Search all installed Knowledge Packs** and type what you want to know. The results are headed **Closest passages**, because they are the original text nearest to your question, and a passage may not answer it. Each one names its source, and **Read the complete topic** opens the whole document. The Back arrow returns through the results to your conversation, as you left it. Each search stands alone and does not use the conversation. On a 2011 laptop the first search takes about 11 seconds and later ones about 3. Knowledge Packs are explained on [[Knowledge-Packs]], and more can be downloaded from the catalog at https://github.com/ProWoos-Devs/ai2-knowledge.

The AI stops by itself when you have not used it for a while, or stop it now with `ai-2 stop`.

**Applications > AI-2 > AI-2 Chat (Browser)**, or `ai-2 chat --browser`, opens a chat page in the browser instead. It is the slowest and heaviest of the three on an old computer, and it does not use the saved conversations. Its address bar says "Not Secure" because the page is served by your own computer at 127.0.0.1. Nothing leaves the machine, there is nothing to secure. It opens in Firefox ESR, the browser AI-2 comes with.

On a low-end PC the better way is **Applications > AI-2 > AI-2 Chat (Terminal)**, or:

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

## Read a web page as text

Firefox comes with **Gopher Reader**, the **>_** button on its toolbar (or Alt+Shift+0). It turns the page you are on into plain text with numbered links, on the article alone or the full page. **Open in Gopher app** saves that copy and opens it in the AI-2 Gopher app, so you can close Firefox, which is the heaviest program on an old computer, and keep reading. Saved pages stay in the app's **Saved web pages** without the internet. Nothing is sent anywhere; the copy is made from the page already loaded.

You can remove it in Firefox under Menu > Add-ons and themes > Extensions, and it does not come back.

## Staying up to date

AI-2, the AI engine and the model catalog all update the normal Artix/Arch way, from AI-2's signed package repository that is already configured. One command, or Applications > AI-2 > Software Updates:

```
ai-2 update
```

It runs `sudo pacman -Syu`, printing the command first, and then finishes the update for your account (see Updates in [[FAQ and Troubleshooting]]). Typing `sudo pacman -Syu` yourself is fine too; what it leaves for your account is finished at your next login.

Being based on Artix means a rolling release, you update, you never reinstall for a new version. AI-2 checks for updates passively and tells you when some are waiting.

## Lean by design

AI-2 ships only what it needs, the desktop, a browser, a text editor and the AI engine. Anything you miss is one command away:

```
sudo pacman -S atril          # PDF viewer
sudo pacman -S cups           # printing
sudo pacman -S vlc            # media player
sudo pacman -S libreoffice-still
```
