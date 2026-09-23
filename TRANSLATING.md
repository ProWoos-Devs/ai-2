# Translating AI-2, step by step

AI-2 speaks English, Spanish and German, and Polish in the installer. Anyone can add a language. You need a GitHub account and nothing else. There is no program to install, nothing to compile, and nobody to ask for permission until the pull request at the end.

This page is written for a first translation. Everything can be done in the GitHub web editor.

---

## What there is to translate

There are two parts, and each is a complete pull request on its own. Doing only the first is a valid contribution.

**Part 1, the installer and the menu.** About 30 short texts shown while AI-2 installs, and the names of the AI-2 menu entries. An afternoon of work.

**Part 2, the installed system.** About 150 texts of the setup window, Search Knowledge and the Knowledge Packs window, plus the two guides (START-HERE, about the USB stick and the installation, and the Guide, about the installed computer). These go in together, because the installed system only switches to a language that has all of them. A few days of work.

Whatever you have not translated shows in English, so a language never breaks by being incomplete.

## 0. Before you start

1. Find your language's code, the two letters the system uses for it, such as `pl` for Polish, `fr` for French, `pt` for Portuguese or `it` for Italian. For a regional variant use the full form, `pt_BR`.
2. Look at the [open pull requests](https://github.com/ProWoos-Devs/ai-2/pulls) and [issues](https://github.com/ProWoos-Devs/ai-2/issues) for your language, so two people do not translate the same thing. If you are starting, open an issue titled "Translation: <your language>" to say so.
3. Fork the repository. On https://github.com/ProWoos-Devs/ai-2 press **Fork** (top right). You work in your fork and cannot push to ours directly; that is normal.

## Words that are names

A few words are names and follow fixed rules in every language.

- **AI-2** is never translated.
- **Knowledge Packs** is the name of a feature. Translate it, and write it with capitals like a name, as in Spanish "Paquetes de Conocimiento", German "Wissenspakete" and Polish "Pakiety Wiedzy". Use the same form everywhere.
- **Search Knowledge** is an ordinary menu label, translated as ordinary words, as in Spanish "Buscar conocimiento", German "Wissen durchsuchen" and Polish "Szukaj wiedzy".
- For words the system already uses (Settings, Applications, Terminal), use the words your language's Linux desktop uses. When a text names a menu path such as `Applications > AI-2 > Search Knowledge`, translate each part exactly as the menu shows it.

---

## Part 1, the installer and the menu

### 1.1 The installer texts

The installer's texts are in `iso/profiles/ai2/live-overlay/usr/share/calamares/branding/ai2/lang/`. Each language is one file, `calamares-ai2_<code>.ts`.

1. Open the German file, [`calamares-ai2_de.ts`](https://github.com/ProWoos-Devs/ai-2/blob/main/iso/profiles/ai2/live-overlay/usr/share/calamares/branding/ai2/lang/calamares-ai2_de.ts), and copy all of it (the **Raw** button shows it as plain text).
2. In your fork, go to the same folder, press **Add file > Create new file**, name it `calamares-ai2_<code>.ts` (for example `calamares-ai2_fr.ts`) and paste.
3. In the third line change `language="de"` to your code, `language="fr"`.
4. Replace the text inside each `<translation>...</translation>` with your translation of the English `<source>` just above it.

Rules for each text:

- **Do not change any `<source>` line.** It is how the installer finds your translation.
- **Keep `%1` exactly as it is.** The installer puts the system's name there.
- **Keep the line breaks** where the English has them. The slides have a fixed size.
- **Keep the markup.** `&lt;p&gt;` and `&lt;/p&gt;` are paragraph marks and `&gt;` is the `>` in menu paths; they stay where they are.
- **One text is a file path**, `file:///usr/share/doc/ai2/START-HERE.txt`. Leave it in English unless you are also doing Part 2, and then put the path of your own START-HERE there (see 2.3).
- Do not add a `.qm` file. That is the compiled form, and our build makes it from your `.ts`.

### 1.2 The menu entries

The AI-2 menu entries are the `.desktop` files in [`branding/desktop/`](https://github.com/ProWoos-Devs/ai-2/tree/main/branding/desktop). Each translated text is a line with your code in brackets, next to the Spanish and German ones:

```
Name=Search Knowledge
Name[es]=Buscar conocimiento
Name[de]=Wissen durchsuchen
Name[fr]=Rechercher dans les connaissances
```

Open each file, press the pencil icon to edit, and add a line for your language under every `Name`, `GenericName` and `Comment` that already has Spanish and German lines. Leave alone the ones that have none; they stay English on purpose (a product name like "AI-2 Chat", or an entry no menu shows).

### 1.3 Open the pull request

Commit your changes to a new branch in your fork, with a message that says what it is ("French translation of the installer"), then press **Contribute > Open pull request**. Say in the description which parts you translated.

Go on to "What happens next" below.

---

## Part 2, the installed system

### 2.1 The texts of the setup window and the AI-2 programs

These are in `ai2/data/i18n/`, one file per language.

1. Copy [`ai2/data/i18n/es.json`](https://github.com/ProWoos-Devs/ai-2/blob/main/ai2/data/i18n/es.json) (or `de.json`, whichever you read better) to `ai2/data/i18n/<code>.json` in your fork.
2. Each line is `"English text": "translation"`. **Change only the part after the colon**, and never the English part before it, which is how the program finds your text.
3. **Keep every `{name}` in braces exactly as it is**, spelled the same, even when the word inside is English (`{n}`, `{url}`, `{label}`). The program puts a number, an address or a name there.
4. Keep `\n` (a line break) and the spaces at the start of a text, which line things up on screen.

### 2.2 The two guides

Both are plain text files in [`branding/`](https://github.com/ProWoos-Devs/ai-2/tree/main/branding), and each language gives them names in its own words, so a person who does not read English recognizes them.

| | English | Spanish | German |
|---|---|---|---|
| START-HERE, on the USB stick | `START-HERE.txt` | `EMPIEZA-AQUI.txt` | `START-HIER.txt` |
| The Guide, on the installed computer | `AI-2-GUIDE.txt` | `AI-2-GUIA.txt` | `AI-2-ANLEITUNG.txt` |

1. Pick your two names, in capitals, with only letters, digits and hyphens and no accents (`COMMENCER-ICI.txt`, `AI-2-GUIDE-FR.txt`).
2. Translate `START-HERE.txt` and `AI-2-GUIDE.txt` into those two files. Start from the Spanish or German versions if they are easier for you. Near the top, each Guide names the Guides in other languages. In yours, keep only the English one ("In English: AI-2-GUIDE.txt").
3. **No line longer than 80 characters.** The Guide is also read in a terminal.
4. The Guide must keep the commands `ai-2 install`, `ai-2 update`, `ai-2 chat` and `ai-2 guide` as they are, and name the menu as `Applications > AI-2 > ...` translated as your desktop shows it.

### 2.3 Tell AI-2 about the language

1. Add your language to [`ai2/data/languages.json`](https://github.com/ProWoos-Devs/ai-2/blob/main/ai2/data/languages.json), after the others, with the name of the language in its own words, your two file names, and one line pointing at your START-HERE:

   ```json
   "fr": {
     "name": "Français",
     "start_here": "COMMENCER-ICI.txt",
     "guide": "AI-2-GUIDE-FR.txt",
     "start_here_line": "En français : /usr/share/doc/ai2/COMMENCER-ICI.txt"
   }
   ```

   Mind the commas. Every entry except the last one ends with `},`.
2. Add that same `start_here_line` near the top of the English [`branding/START-HERE.txt`](https://github.com/ProWoos-Devs/ai-2/blob/main/branding/START-HERE.txt), under the Spanish and German lines. That English file is the one on the live desktop, and this line is how someone who does not read English finds theirs.
3. In your installer file from Part 1, set the file path text to your START-HERE, `file:///usr/share/doc/ai2/COMMENCER-ICI.txt`.

Then open the pull request as in 1.3.

---

## What happens next

The checks run on your pull request by themselves, usually within a few minutes. On your first pull request to this repository, GitHub holds them until a maintainer approves the run, which protects the project from code nobody has read; that happens when we first look at it. The **translations** check compiles your installer file, checks every text in it, validates the menu files, and shows a table of how much of each language is done (open the check and scroll to the bottom). The **unit** check runs the project's tests, which also check your `.json`, your guides and your `languages.json` entry.

If a check fails, its message says what to fix, for example:

```
ERROR calamares-ai2_fr.ts: placeholders ['%1'] in the English, [] in the translation of '<h2>Welcome to the %1 installer</h2>'
fr: add this line to branding/START-HERE.txt: En français : /usr/share/doc/ai2/COMMENCER-ICI.txt
```

Fix it in the same branch, and the pull request updates itself. You do not need a new one.

Then a maintainer reads it. We may suggest wording, and if another speaker of your language is around we ask them to look too. When it is merged, your translation goes into the next ISO and the next `ai-2` package, and you are named in the [changelog](CHANGELOG.md).

## Keeping it current

English texts change from one release to the next. When they do, the translations check lists the texts your language does not have yet ("not translated yet"), and we open an issue that mentions you. Nothing breaks in the meantime; the new texts show in English until they are translated.

## Checking it on your own computer

Not needed, the checks do this for you. If you have the repository cloned and Python 3.11 or newer:

```
python tools/translations.py check        # the installer files
python tools/translations.py coverage     # how far each language has got
python -m pytest -q tests/                 # everything the unit check runs (needs pytest and pyyaml)
```

Questions go in your pull request or in an [issue](https://github.com/ProWoos-Devs/ai-2/issues). Asking is not a failure; most of this page exists because someone asked.
