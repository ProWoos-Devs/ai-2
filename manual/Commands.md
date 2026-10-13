Every command has `--help`. `AI-2` works as a synonym for `ai-2` everywhere, and running bare `ai-2` lists the commands.

## Seeing your machine

| Command | What it does |
|---|---|
| `ai-2 detect` | What AI-2 sees: CPU (and which llama.cpp build it needs), RAM, GPU, disk, init system. |
| `ai-2 tier` | The assigned [[capability tier|Capability Tiers]] and why. |
| `ai-2 profile` | Everything AI-2 knows about this machine in one view: hardware, tier, AI Score, capability stars. `--json` for scripts. |
| `ai-2 benchmark` | Run llama.cpp on a fixed workload and compute the 0-100 [[AI Score|AI Score and Benchmarks]] and capability stars. |
| `ai-2 recommend` | Which local model fits this machine, and when to go remote. |

## Tuning the system

| Command | What it does |
|---|---|
| `ai-2 init` | Dry run, print the tuning plan for this machine. |
| `sudo ai-2 init --apply` | Apply it: compressed swap in RAM (zram or zswap per tier), out-of-memory protection (earlyoom), sysctl tuning, no idle suspend, and the engine build for this CPU. |
| `sudo ai-2 init --revert` | Undo it from the manifest: restore the original of any file AI-2 overwrote, remove files it created, disable the services it enabled. Never removes packages. |
| `sudo ai-2 runtime install` | Install the llama.cpp package for this CPU class. |

## Models

| Command | What it does |
|---|---|
| `ai-2 model pull` | Download the recommended model, or a specific one with `ai-2 model pull <id>`. Downloads resume, and every file is verified by SHA-256. |
| `ai-2 model list` | Models on this computer and in the catalog, with sizes and the recommended/loaded markers. |
| `ai-2 model rm <id>` | Delete a model to free disk space (refuses a model the server is using). |
| `ai-2 model verify` | Check downloaded models against the catalog checksums. |

More on the catalog and how recommendations work: [[Models]].

## Using the AI

| Command | What it does |
|---|---|
| `ai-2 chat` | Start the local AI if needed and open the chat page in the browser. |
| `ai-2 chat --terminal` | Chat right in the terminal, no browser around it: the fastest to appear, the lightest next to the model, and it works over SSH. Used automatically when there is no graphical display. `/new` starts a fresh conversation. |
| `ai-2 serve` | llama-server on demand with the recommended model, an OpenAI-compatible API on `http://127.0.0.1:8080`, exits when idle. See [[Local API Server]]. |
| `ai-2 stop` | Stop the local AI (and the document index server) and free their memory. |
| `ai-2 wizard` | The guided setup, re-runnable any time (`--yes` for unattended). |

## Your documents

| Command | What it does |
|---|---|
| `ai-2 doc index FILE...` | Read text files, PDFs, DOCX or scans (`--lang spa` for Spanish OCR) into the documents index. The text is cut into parts of about 110 words and each part is embedded by a second, small on-demand server. Slow on an old CPU, about 9 tokens a second on the 2016 reference laptop, so a 20-page document takes roughly 20 minutes there; the command shows parts done and minutes left, and can be left running. A new collection takes the embedding model that best fits this machine's RAM; `--embedder ID` decides instead, which is what a pack meant for other people wants (`nomic-embed-text-v1.5`, 85 MB and already on every ISO install, rather than the 345 MB multilingual one). A collection keeps the model it was built with. |
| `ai-2 doc ask "question"` | The closest parts of your documents go to the AI together with the question, and the answer names its sources, with the page for PDFs ("constitucion.pdf, page 8") and the part number for other files. When a remote AI is configured (`ai-2 remote`) and the local answer would come from a starter model or after a long wait, the question and the excerpts go there, and the command says so first, because they leave the computer. `--local` and `--remote` decide by hand, `--doc NAME` searches one document, `--top N` changes how many parts are handed over. |
| `ai-2 doc search "question"` | The parts of your documents closest to the question, printed with their pages, and no chat model involved. With no question at all it asks for one and keeps asking, which is what the **Search Knowledge** menu entry runs. The text is the document's own, so nothing can be made up, and it takes seconds instead of the minutes an answer takes on an old computer (18.9 s from a cold disk cache on the 2011 reference laptop, 4.1 s for the next question). `--top N` and `--doc NAME` as for ask. |
| `ai-2 doc list` | What is indexed, by collection, with the embedding model each collection was built with. |
| `ai-2 doc forget NAME` | Remove a document; its collection is found by name, and `--in NAME` is asked for only when two collections have a document of that name. `--all --in NAME` removes a whole collection (`--all` alone, the `documents` collection; a new one may then pick another embedder). |
| `ai-2 knowledge export NAME` | Write a collection as one `.ai2pack` file (document paths left out). `--manifest FILE` supplies a YAML with id, version, title, languages, license, attribution, modified and sources (file, title, url); without it the pack is named after the collection. |
| `ai-2 knowledge install FILE` | Install a pack as a collection, downloading its embedding model if missing. A pack whose revision is the same or higher replaces the installed one of that id; an older revision is refused and needs `--force`. A pack never overwrites a collection of your own (`--as NAME`). Searches then show the source URL next to its citations and the pack's license and attribution. |
| `ai-2 knowledge available [TERM]` | The packs of the community catalog (https://github.com/ProWoos-Devs/ai2-knowledge) this AI-2 can fetch by name, and which of them are installed. |
| `ai-2 knowledge install ID` | Fetch a cataloged pack, check its size and SHA-256 and install it. An interrupted download resumes. |
| `ai-2 knowledge list` / `remove NAME` | The knowledge packs installed here, and removing one. |
| `ai-2 gopher` | Serve the installed knowledge packs over Gopher (read them from another machine with `w3m gopher://this-computer:7070/`), so any machine on the network can ask them with an ordinary Gopher client and no AI-2 of its own. Search items answer with the passages themselves, named and attributed. Knowledge packs only unless `--all`; `--host 0.0.0.0` shares it with the network, `--port` defaults to 7070, and one question is answered at a time (`--workers N` for more, which is rarely better on an old machine). The chat model is not served, because an answer takes minutes and no Gopher client waits that long. |

Documents live in collections. `ai-2 doc index --in NAME FILE` adds to a named one (without `--in`, to `documents`), and `ask` and `search` look in all of them unless `--in NAME` picks one; with several, the sources name the collection. Each collection is `~/.local/share/ai2/doc/NAME/index.sqlite`, plain SQLite, one embedding model per collection. A question is embedded once, so a collection built with another embedding model is left out of a search across collections, and the command says so. The single index of 0.14 and 0.15 becomes the `documents` collection by itself.

A knowledge pack is how the slow part moves to a fast computer (the [[Knowledge Packs|Knowledge-Packs]] page covers them on their own). Indexing runs at about 9 tokens a second on the 2016 reference laptop and in seconds on a recent one, and a search needs only the question embedded. So index there, `ai-2 knowledge export`, copy the file, `ai-2 knowledge install` on the old computer. Installing checks the file before using it (the tables `ai-2 doc` makes and nothing else, the part counts and the SHA-256 in the manifest), because it is a database made on another computer. Nothing new is installed for it: the embedding server is the llama-server AI-2 already ships, running one of the two embedding models in the [[catalog|Models]]. `pdftotext` (poppler) and `tesseract` come with the documents workflow (`ai-2 workflow install documents` prints the package line).

## Speech to text

| Command | What it does |
|---|---|
| `ai-2 transcribe FILE` | Turns a recording, a voice note or a video's audio into FILE.txt with whisper.cpp, offline. Anything that is not a 16 kHz mono WAV is converted with `ffmpeg` first. `--lang es` names the language (detected otherwise), `--model tiny`, `base` (default) or `small` picks the speech model, downloaded on first use, `-o` sets the output file. Needs the `ai2-whisper-cpp` package, one for every CPU. File transcription only, slow on an old computer: the engine works in 30-second windows, and the tiny model on the 2011 reference laptop took about 13 seconds per window. |

## Software and updates

| Command | What it does |
|---|---|
| `ai-2 update` | Update AI-2, the AI engine, the model catalog and the whole system in one step. It prints the `sudo pacman -Syu` it runs, checks a Broadcom WiFi driver first, and then finishes the update for your account (the migrations below). `--gui` opens Software Updates instead. |
| `ai-2 install <name>` | Install software AI-2 leaves out by a short name (`office`, `pdf`, `printing`, `media`, ...) or by package name, enabling the service a daemon needs on runit. `--list` shows the short names, `--gui` opens Add/Remove Software. |
| `ai-2 migrate` | Finish an update for this account: run the per-user migrations still pending. `ai-2 update` and every login do this on their own; `--pending` only lists them. See Updates in [[FAQ and Troubleshooting]]. |
| `ai-2 update-check` | Check for pending system updates without installing anything. The desktop runs `ai-2 update-check --notify --every 6` for the life of the session, which is where the "updates available" bubble and the one-line hint in a new terminal come from. |

## Health and help

| Command | What it does |
|---|---|
| `ai-2 doctor` | Check engine, model, tuning, services and repository key. |
| `ai-2 report` | Write `~/ai2-report.txt` to attach to a bug report. |
| `ai-2 crashes` | The programs that stopped unexpectedly for this account in the last 7 days, and what to do about each. The desktop says so once in a bubble; `ai-2 doctor` has the same as a check. Only a name, a signal and a time are kept, never a memory dump, and nothing is sent anywhere. |
| `ai-2 guide` | The AI-2 guide for this computer in the system language (`--lang es`, `--open` in the text editor, `--path`). The first login puts it on the desktop. |
| `ai-2 accessibility` | Screen-reader status; `ai-2 accessibility setup` installs Orca and spoken chat for this user. See [[Accessibility]]. |
| `ai-2 logo` | The mark, in the size the terminal allows. |
| `ai-2 about` | The AI-2 version, the system it is based on, this computer's AI Score, the website and the license. The menu entry Applications > AI-2 > About AI-2 shows the same in a terminal window. |
