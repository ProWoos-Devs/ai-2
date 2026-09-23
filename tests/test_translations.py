"""The installer catalogs (calamares-ai2_<lang>.ts) and the translated keys in
the .desktop files: what a translator's pull request must get right. Compiling
the .ts and checking it against the strings the installer really asks for
need Qt's tools, so CI's translations job does that; these run anywhere."""
import importlib.util
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("translations", ROOT / "tools" / "translations.py")
translations = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(translations)


def test_there_are_installer_catalogs():
    assert translations.ts_files()


def test_every_installer_catalog_is_sound():
    problems = [p for ts in translations.ts_files() for p in translations.ts_problems(ts)]
    assert not problems, "\n".join(problems)


def test_slide_texts_fit_the_slide():
    assert len(translations.slide_font_sizes()) >= 20, "show.qml texts not found"
    problems = [p for ts in translations.ts_files() for p in translations.slide_overflows(ts)]
    assert not problems, "\n".join(problems)


def test_a_broken_catalog_is_reported(tmp_path):
    bad = tmp_path / "calamares-ai2_xx.ts"
    bad.write_text('<?xml version="1.0"?><TS version="2.1" language="yy"><context><name>c</name>'
                   '<message><source>Install %1</source><translation>Instaluj</translation></message>'
                   '</context></TS>', encoding="utf-8")
    problems = translations.ts_problems(bad)
    assert any('language="xx"' in p for p in problems)
    assert any("placeholders" in p for p in problems)
    bad.write_text("<TS", encoding="utf-8")
    assert any("not valid XML" in p for p in translations.ts_problems(bad))


def test_compiled_catalogs_are_not_committed():
    """The .qm is build output: CI and the ISO build make it from the .ts."""
    tracked = subprocess.run(["git", "ls-files", str(translations.LANG_DIR)], cwd=ROOT,
                             capture_output=True, text=True).stdout.split()
    if not tracked:  # not a git checkout (a release tarball)
        return
    assert not [f for f in tracked if f.endswith(".qm")]


def test_desktop_translations_are_well_formed():
    for name, entries in translations.desktop_entries().items():
        for key, value in entries.items():
            m = re.fullmatch(r"(\w+)\[([^\]]+)\]", key)
            if not m:
                continue
            base, code = m.groups()
            assert base in entries, f"{name}: {key} has no untranslated {base}"
            assert re.fullmatch(r"[a-z]{2,3}(_[A-Z]{2})?(@\w+)?", code), f"{name}: {key} is not a locale code"
            assert value.strip(), f"{name}: {key} is empty"


def test_coverage_report_runs():
    out = subprocess.run([sys.executable, "tools/translations.py", "coverage", "--markdown"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert "| Language |" in out
    for code in ("es", "de"):
        assert f"| {code} |" in out


def test_every_language_has_its_translators():
    """translators.json names who did each language: the README credits them
    and the release issues mention them."""
    listed = translations.translators()
    for code in ["en", *translations.languages()]:
        assert code in listed, f"{code}: add your language and your name to translators.json"
    for code, entry in listed.items():
        assert entry.get("language"), f"{code}: translators.json needs the language's own name"
        assert entry.get("english"), f"{code}: translators.json needs the language's name in English"
        assert entry.get("translators"), f"{code}: translators.json lists nobody"
        for person in entry["translators"]:
            assert person.get("name") and re.fullmatch(r"[A-Za-z0-9-]+", person.get("github", "")), \
                f"{code}: each translator needs a name and a GitHub username"


def test_generated_lists_are_current():
    """The installer languages (README.md, TRANSLATING.md) and the
    translators table (README.md) are made from the files; the message gives
    the exact text, so it can be pasted in the web editor."""
    for block, paths in translations.GENERATED_IN.items():
        for path in paths:
            text = path.read_text(encoding="utf-8")
            assert f"<!-- {block}:start -->" in text, f"{path.name} lost its {block} markers"
            assert translations.render_generated(text, block) == text, (
                f"{path.name}: between <!-- {block}:start --> and <!-- {block}:end --> put exactly\n"
                f"{translations.GENERATED[block]()}\n(or run tools/translations.py readme --write)")


def test_release_issue_mentions_the_translators():
    body = translations.issue_body("pl", {"branding/desktop/x.desktop": ["Name=Search Knowledge"]})
    for person in translations.translators()["pl"]["translators"]:
        assert f"@{person['github']}" in body
    assert "Name=Search Knowledge" in body and "TRANSLATING.md" in body


def test_nothing_is_stale_against_the_committed_strings():
    """With the installer strings each catalog already has as the template,
    a language only shows up when a part it started lost texts."""
    import tempfile
    sources = sorted({s for ts in translations.ts_files() for s, _, _ in translations.ts_messages(ts)})
    with tempfile.NamedTemporaryFile("w", suffix=".ts", delete=False, encoding="utf-8") as fh:
        from xml.sax.saxutils import escape
        fh.write('<?xml version="1.0"?><TS version="2.1"><context><name>t</name>'
                 + "".join(f"<message><source>{escape(s)}</source></message>" for s in sources)
                 + "</context></TS>")
    assert translations.stale(pathlib.Path(fh.name)) == {}
