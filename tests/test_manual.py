"""The manual (manual/, one file per wiki page) and the links into it. The
GitHub wiki is a copy pushed by tools/wiki-sync.sh; a broken link between
pages, or a README or code address naming a page that does not exist, used
to be found by a reader."""
import pathlib
import re

MANUAL = pathlib.Path("manual")
WIKI_URL = re.compile(r"https://github\.com/ProWoos-Devs/ai-2/wiki/([A-Za-z0-9._-]+)")
WIKI_LINK = re.compile(r"\[\[([^\]]+)\]\]")


def _pages() -> set[str]:
    return {p.stem for p in MANUAL.glob("*.md")}


def _page_name(target: str) -> str:
    """GitHub names a wiki page's file after its title with spaces as
    hyphens; [[Knowledge Packs]] and [[Knowledge-Packs]] are the same page."""
    return target.strip().replace(" ", "-")


def test_the_manual_has_a_home_page_and_only_pages():
    pages = _pages()
    assert "Home" in pages
    assert all(p.suffix == ".md" for p in MANUAL.iterdir()), "only pages in manual/"


def test_every_link_between_pages_resolves():
    pages = _pages()
    broken = []
    for path in sorted(MANUAL.glob("*.md")):
        for link in WIKI_LINK.findall(path.read_text(encoding="utf-8")):
            target = link.split("|")[-1]      # [[shown text|Page]] or [[Page]]
            if _page_name(target) not in pages:
                broken.append(f"{path.name}: [[{link}]]")
    assert broken == []


def test_every_wiki_address_in_the_repo_names_a_page():
    pages = _pages()
    sources = [pathlib.Path("README.md"), pathlib.Path("CONTRIBUTING.md"), pathlib.Path("TRANSLATING.md"),
               pathlib.Path("CHANGELOG.md")]
    sources += sorted(pathlib.Path("ai2").glob("*.py")) + sorted(pathlib.Path("branding").glob("*.txt"))
    sources += sorted(MANUAL.glob("*.md")) + sorted(pathlib.Path("ai2/data/i18n").glob("*"))
    broken = []
    for path in sources:
        if not path.is_file():
            continue
        for name in WIKI_URL.findall(path.read_text(encoding="utf-8", errors="replace")):
            if name not in pages:
                broken.append(f"{path}: wiki/{name}")
    assert broken == []


def test_the_sync_script_is_the_only_way_pages_reach_the_wiki():
    import subprocess
    script = pathlib.Path("tools/wiki-sync.sh")
    text = script.read_text(encoding="utf-8")
    assert "--delete" in text and "--check" in text and "ai-2.wiki.git" in text
    assert subprocess.run(["bash", "-n", str(script)]).returncode == 0

