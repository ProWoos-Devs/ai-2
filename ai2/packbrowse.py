"""The Knowledge Packs window: see what there is, pick by number, install, and
bring installed packs up to date.

Until 0.18.7 all of this was three terminal commands a person had to know
(`ai-2 knowledge available`, `install ID` one pack at a time, and nothing at all
that said a newer version of an installed pack existed). Rafael, 2026-09-19:
"how do I know which ones are available, how do I select the ones I want, and
how do I install them?", and then "if those Knowledge Packs get changed, how
will users who have them installed, update them?". The honest answer to both
was "in a terminal, if they know to", so this is the menu entry Applications >
AI-2 > Knowledge Packs, and `ai-2 knowledge browse` in a terminal.

What it lists is the copy of the community catalog inside the signed ai-2
package, the only list a pack is fetched by name from. `ai-2 update` brings a
newer copy, which is how a changed pack becomes known here; installing it stays
a person's decision, so nothing updates itself, but every place a person meets
their packs now says when a newer version exists.

The logic is kept free of stdin/stdout and of the download itself (`install` is
passed in), so tests drive it with canned answers.
"""

from __future__ import annotations

import textwrap
from typing import Callable

from . import pack
from .i18n import tr

WINDOW = "Applications > AI-2 > Knowledge Packs"


def installed_by_id() -> dict[str, dict]:
    """Installed packs keyed by the id in their manifest (the collection name
    can differ when a pack was installed `--as` something else)."""
    found: dict[str, dict] = {}
    for name, manifest in pack.installed_packs():
        found[str(manifest.get("id") or name)] = dict(manifest, _collection=name)
    return found


def state_of(entry: dict, installed: dict[str, dict]) -> str:
    """"" (not installed), "installed", or "update" when the catalog's
    revision is higher than the one on this computer."""
    here = installed.get(entry.get("id"))
    if here is None:
        return ""
    return "update" if pack.revision_of(entry) > pack.revision_of(here) else "installed"


def outdated(catalog: list[dict] | None = None, installed: dict[str, dict] | None = None) -> list[dict]:
    """Catalog entries whose installed copy is an older revision. Never raises:
    a notice about updates must not break the window that shows it."""
    try:
        catalog = pack.load_catalog() if catalog is None else catalog
        installed = installed_by_id() if installed is None else installed
        return [e for e in catalog if state_of(e, installed) == "update"]
    except Exception:                                   # noqa: BLE001
        return []


def update_notice(entries: list[dict]) -> str:
    """One sentence for the places a person meets their packs (Search
    Knowledge, the end of `ai-2 update`). Empty when there is nothing to say."""
    if not entries:
        return ""
    names = ", ".join(str(e.get("title") or e["id"]) for e in entries)
    if len(entries) == 1:
        return tr("A newer version is available for: {names}.\nUpdate in  {window} , or with  ai-2 knowledge update").format(
            names=names, window=WINDOW)
    return tr("Newer versions are available for: {names}.\nUpdate in  {window} , or with  ai-2 knowledge update").format(
        names=names, window=WINDOW)


def describe(entry: dict) -> str:
    size_kb = int(entry.get("size_bytes") or 0) // 1024
    size = f"{size_kb / 1024:.1f} MB" if size_kb >= 1024 else f"{max(1, size_kb)} KB"
    bits = [f"{entry.get('parts')} parts", size, ", ".join(entry.get("languages") or []), str(entry.get("license"))]
    if entry.get("contact"):
        bits.append(tr("by {contact}").format(contact=entry["contact"]))
    return ", ".join(b for b in bits if b and b != "None")


def render(catalog: list[dict], installed: dict[str, dict], width: int = 96) -> str:
    """The numbered list. Each pack gets its sentence of description, because
    an id and a title do not tell a person whether they want it."""
    labels = {"": "", "installed": tr("[installed]"),
              "update": tr("[installed, newer version available]")}
    lines: list[str] = []
    for n, entry in enumerate(catalog, 1):
        head = f"  {n:>2}  {entry['id']:<20} {entry.get('title') or ''}"
        label = labels[state_of(entry, installed)]
        lines.append(f"{head}  {label}".rstrip())
        if entry.get("description"):
            lines += textwrap.wrap(str(entry["description"]), width=width - 6,
                                   initial_indent="      ", subsequent_indent="      ")
        lines.append(f"      {describe(entry)}")
        lines.append("")
    cataloged = {e.get("id") for e in catalog}
    others = [(pid, m) for pid, m in installed.items() if pid not in cataloged]
    if others:
        lines.append(tr("Also installed here, from a file:  {names}").format(
            names=", ".join(f"{m['_collection']} ({m.get('title')})" for pid, m in others)))
        lines.append("")
    return "\n".join(lines).rstrip("\n")


def parse_choice(text: str, count: int) -> tuple[list[int], bool, list[str]]:
    """What a person typed, as (numbers, update_all, what was not understood).
    "2 3", "2,3" and "2, 3" all mean the same; "u" means every pack with a newer
    version; "a" means everything listed."""
    numbers: list[int] = []
    update_all = False
    unknown: list[str] = []
    for token in text.replace(",", " ").split():
        word = token.lower()
        if word in ("u", "update"):
            update_all = True
        elif word in ("a", "all"):
            numbers += [n for n in range(1, count + 1) if n not in numbers]
        elif word.isdigit() and 1 <= int(word) <= count:
            if int(word) not in numbers:
                numbers.append(int(word))
        else:
            unknown.append(token)
    return numbers, update_all, unknown


def browse(install: Callable[[dict], int], model_cost: Callable[[dict], str | None],
           ask: Callable[[str], str] = input, say: Callable[[str], None] = print,
           interactive: bool = True, width: int = 96, banner: str = "") -> int:
    """The window. `install(entry)` fetches and installs one cataloged pack and
    returns 0 when it is searchable; `model_cost(entry)` returns a sentence
    about the embedding model when this computer still has to download it (the
    real cost of a first pack, said before anything is fetched), else None."""
    catalog = pack.load_catalog()
    if banner:
        say(banner)
    say(textwrap.fill(tr("Knowledge Packs are sets of documents this computer searches and answers from, "
                         "with no internet, naming the document every answer came from. These are the packs "
                         "of the community catalog that this AI-2 knows."), width=width))
    if not catalog:
        say(tr("\nThe list is empty. Packs, and how to share one you made:  {url}").format(url=pack.CATALOG_URL))
        return 0
    failed = 0
    while True:
        installed = installed_by_id()
        say("\n" + render(catalog, installed, width))
        say(tr("\nMore packs, and how to share one you made:  {url}").format(url=pack.CATALOG_URL))
        say(tr("A pack file you downloaded:                 ai-2 knowledge install FILE.ai2pack"))
        say(tr("Remove a pack:                              ai-2 knowledge remove NAME"))
        if not interactive:
            return 0
        newer = [e for e in catalog if state_of(e, installed) == "update"]
        missing = [e for e in catalog if state_of(e, installed) == ""]
        if not newer and not missing:
            prompt = tr("\nEvery pack listed is installed and up to date. Press Enter to close. ")
        else:
            # said, not packed into the prompt: a prompt longer than the window
            # wraps, and line editing then misplaces the cursor
            say(tr("\nTo install packs, type their numbers, for example  1 3"))
            if newer:
                say(tr("To update the ones that have a newer version, type  u"))
            prompt = tr("Numbers, or just Enter to close: ")
        try:
            answer = ask(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            say("")
            return 1 if failed else 0
        if not answer:
            return 1 if failed else 0
        numbers, update_all, unknown = parse_choice(answer, len(catalog))
        if unknown:
            say(tr("Not understood: {what}. Use the numbers on the left.").format(what=" ".join(unknown)))
        wanted = [catalog[n - 1] for n in numbers]
        if update_all:
            wanted += [e for e in newer if e not in wanted]
        todo = []
        for entry in wanted:
            if state_of(entry, installed) == "installed":
                say(tr("{id} is already installed and up to date.").format(id=entry["id"]))
            else:
                todo.append(entry)
        if not todo:
            continue
        costs = {c for c in (model_cost(e) for e in todo) if c}
        if costs:
            say("\n" + textwrap.fill(" ".join(sorted(costs)), width=width))
            try:
                go = ask(tr("Go ahead? [Y/n]: ")).strip().lower()
            except (EOFError, KeyboardInterrupt):
                say("")
                return 1 if failed else 0
            if go and not go.startswith(("y", "s", "j")):
                say(tr("Nothing installed."))
                continue
        for entry in todo:
            say("")
            try:
                if install(entry) != 0:
                    failed += 1
            except (pack.PackError, OSError) as exc:
                failed += 1
                say(f"error: {entry['id']}: {exc}")
