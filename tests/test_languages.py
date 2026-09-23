"""ai2/data/languages.json is the one list a translator adds a language to.
Everything else (the tr() catalogs, `ai-2 guide`, its --lang choices, the
files the package installs) reads it, so these checks are what tells a
translator what a new entry still needs."""
import json
import pathlib
import re

from ai2 import guide, i18n

ROOT = pathlib.Path(__file__).resolve().parent.parent
LANGS = json.loads((ROOT / "ai2/data/languages.json").read_text(encoding="utf-8"))
BRANDING = ROOT / "branding"


def test_english_is_the_base_and_every_entry_is_complete():
    assert "en" in LANGS
    for code, info in LANGS.items():
        assert re.fullmatch(r"[a-z]{2,3}(_[A-Z]{2})?", code), f"{code}: not a locale code"
        need = {"name", "start_here", "guide"} | ({"start_here_line"} if code != "en" else set())
        missing = need - info.keys()
        assert not missing, f"{code}: missing {sorted(missing)}"


def test_every_language_has_its_two_guides():
    for code, info in LANGS.items():
        for key in ("start_here", "guide"):
            path = BRANDING / info[key]
            assert path.is_file(), f"{code}: branding/{info[key]} is missing"
            assert path.read_text(encoding="utf-8").strip(), f"{code}: branding/{info[key]} is empty"


def test_file_names_are_unique():
    names = [info[k] for info in LANGS.values() for k in ("start_here", "guide")]
    assert len(names) == len(set(names))


def test_every_other_language_has_a_catalog():
    for code in LANGS:
        if code == "en":
            continue
        assert (ROOT / f"ai2/data/i18n/{code}.json").is_file(), f"{code}: ai2/data/i18n/{code}.json is missing"


def test_english_start_here_points_at_every_language():
    """A person on the live stick who does not read English finds their own
    START-HERE through this line at the top of the English one."""
    text = (BRANDING / LANGS["en"]["start_here"]).read_text(encoding="utf-8")
    for code, info in LANGS.items():
        if code == "en":
            continue
        line = info["start_here_line"]
        assert line in text, f"{code}: add this line to branding/{LANGS['en']['start_here']}: {line}"
        assert f"/usr/share/doc/ai2/{info['start_here']}" in line, f"{code}: start_here_line names another file"


def test_the_code_reads_the_same_list():
    assert set(i18n.LANGUAGES) == set(LANGS) - {"en"}
    assert guide.FILES == {code: info["guide"] for code, info in LANGS.items()}


def test_the_package_installs_the_guides_from_the_list():
    pkgbuild = (ROOT / "packaging/ai-2/PKGBUILD").read_text(encoding="utf-8")
    assert "ai2/data/languages.json" in pkgbuild
    for info in LANGS.values():
        for key in ("start_here", "guide"):
            assert f"branding/{info[key]}" not in pkgbuild, f"PKGBUILD still names {info[key]} by hand"
