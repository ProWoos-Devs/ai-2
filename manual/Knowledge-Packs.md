A knowledge pack is a set of documents your computer can search and answer from with no internet connection, naming the source of every answer. AI-2 installs one as a collection like any other, so `ai-2 doc search` and `ai-2 doc ask` find it straight away.

**The community catalog, https://github.com/ProWoos-Devs/ai2-knowledge, is where every pack is listed with its download, and where you share one you made.** Anyone can add a pack, and the AI-2 project's own three are in it with everyone else's.

Packs exist because indexing is the slow part. Turning a book into something searchable runs at a few parts per second on a 2011 laptop and takes minutes to hours; searching it afterwards takes seconds. A pack is that slow work done once, on a fast computer, and shipped as one file.

## Using them

| Command | What it does |
|---|---|
| `ai-2 knowledge list` | The packs installed on this computer, with their version and license. |
| `ai-2 knowledge available` | The packs of the community catalog this AI-2 can fetch by name, and which of them you already have. |
| `ai-2 knowledge install ID` | Fetch one by name, check it and install it. |
| `ai-2 knowledge install FILE.ai2pack` | Install a pack file you downloaded from [the catalog](https://github.com/ProWoos-Devs/ai2-knowledge), that someone gave you, or that you made yourself. |
| `ai-2 knowledge remove ID` | Remove an installed pack. |
| `ai-2 knowledge export NAME` | Turn one of your own document collections into a pack file. |

Then ask, the ordinary way:

```
ai-2 doc search "how do I find a big file?"     the passages themselves, with their source
ai-2 doc ask "how do I find a big file?"        the AI answers from those passages
```

In the menu it is **Applications > AI-2 > Search Knowledge**, which opens a window that asks for a question and keeps asking. It shows passages from the documents on this computer, so nothing in the answer is written by the AI.

`ai-2 doc search` needs no chat model at all, which is why it answers in seconds on an old machine where `ask` takes minutes. Both name where the text came from, down to the page for a PDF, and a pack's own licence and attribution are printed with its results.

## Making one for yourself

This is the household case: a recent computer does the indexing, the old one does the asking.

```
ai-2 doc index --in recipes ~/Documents/recipes/*.pdf     on the fast computer
ai-2 knowledge export recipes -o recipes.ai2pack
```

Copy the file across, then on the old computer:

```
ai-2 knowledge install recipes.ai2pack
ai-2 doc search "how long do I boil an egg?"
```

The pack holds the documents' text and the search index, not your file paths. A pack can only be searched with the embedding model that built it, and AI-2 fetches that model for you if it is missing (on an ISO install of 2026-09-16 or later the English one is already on the machine).

## The three packs that come with AI-2

Which of these are already on your computer depends on how it got AI-2.

**Installed from the ISO of 2026-09-16 or later:** all three are already there, and so is the English embedding model they need. Nothing to download, nothing to set up; `ai-2 knowledge list` shows them and `ai-2 doc search` answers straight away, with no network at all.

**An older AI-2 brought up to date:** the packs are not added by an update, because an update changes packages and not your documents. `ai-2 knowledge available` lists them and `ai-2 knowledge install ID` fetches one, which also fetches the English embedding model the first time.

| Pack | What is in it | Size |
|---|---|---|
| `ai2-help` | AI-2's own documentation, so a machine with no working network can still answer "how do I get the WiFi working?" | 337 KB |
| `linux-essentials` | Twenty everyday tasks on a Linux machine, written for AI-2 (which runs runit, so `systemctl` does not exist here) | 125 KB |
| `everyday` | 196 countries with their capitals, currencies, official languages, country codes and calling codes, from Wikidata | 579 KB |

All three are English and share one embedding model, so installing a second and third pack costs only the pack.

## Reading them from another machine

The computer holding the packs can answer for the others. On it:

```
ai-2 gopher --host 0.0.0.0
```

On any other machine, open `gopher://that-computer:7070/` in a text browser. AI-2 ships **w3m**, which speaks Gopher; lynx does too, and clients exist for phones. Nothing of AI-2 is needed on the asking side.

The menu offers, for each pack, a search item and a list of its documents. Type a question into the search item and the answer comes back as the passages themselves, each naming the document and page it came from, with the pack's license and attribution underneath.

Only knowledge packs are served. Your own indexed documents stay on your machine unless you add `--all`, and the command says plainly what it is exposing. The chat model is not served at all: an answer takes minutes on the machines AI-2 is built for, far longer than a Gopher client waits, and the passages are the part that is reliable there anyway.

## Where packs come from, and where yours goes

One place, the community catalog at [ProWoos-Devs/ai2-knowledge](https://github.com/ProWoos-Devs/ai2-knowledge). Its front page lists every pack with what is in it, who made it, its language, size, license and a download link. Packs are made by anyone: the three that come with AI-2 were made by the project, from recipes in that repository that anyone can read and rerun, and they sit in the catalog next to everyone else's.

Every entry is checked the same way before it is accepted: the file is downloaded, checked against its checksum, installed by AI-2 itself and compared with what the entry claims. Nobody verifies that a pack's contents are correct; each entry names who made the pack, and that is what you go by.

Each `ai-2` release carries a copy of the catalog inside the signed package, and `ai-2 knowledge install ID` resolves a name only against that copy, so what arrives is checked against a hash the package signature covers. A pack added to the catalog after your `ai-2` was released is listed by name from the next release on; until then, download its file from the catalog and run `ai-2 knowledge install FILE.ai2pack`.

To share a pack you made, that repository has a step-by-step guide, [CONTRIBUTING.md](https://github.com/ProWoos-Devs/ai2-knowledge/blob/main/CONTRIBUTING.md), which covers everything from a folder of text to a merged catalog entry, including building a pack on a machine that does not run AI-2. Two things matter most: the content must be something you may redistribute (public domain, CC0, CC BY or CC BY-SA, with the attribution line in the pack), and it must answer questions asked in ordinary words, which in testing meant writing topics as tasks rather than copying a reference manual.

## What packs are not

They do not teach the AI anything. The model on your computer is unchanged; the pack is searched, and the passages found are handed to the model with your question. That is why an answer can name its source, and why a pack is as up to date as the day it was built, no more.

For that reason the packs that come with AI-2 avoid anything that goes stale: no prices, no populations, no security advice, no "who currently holds this office". A pack that sits on a machine for two years should still be right.
