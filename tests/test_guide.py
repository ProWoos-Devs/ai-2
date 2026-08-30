"""The guide for the installed system: it exists in every language the
installer offers, the right one is picked from the locale, and it lands on the
desktop exactly once."""
import os
import pathlib

import pytest

from ai2 import guide

BRANDING = pathlib.Path("branding")


def test_a_guide_exists_for_every_language():
    for lang, name in guide.FILES.items():
        path = BRANDING / name
        assert path.is_file(), f"{lang}: {name} is missing"
        assert path.read_text(encoding="utf-8").strip(), f"{lang}: {name} is empty"


def test_every_guide_covers_the_two_questions_it_exists_for():
    """Adding software and updating. A translation that quietly loses one of
    them leaves that language's users with no answer."""
    for name in guide.FILES.values():
        text = (BRANDING / name).read_text(encoding="utf-8")
        for command in ("ai-2 install", "ai-2 update", "ai-2 chat", "ai-2 guide"):
            assert command in text, f"{name} never mentions {command}"


def test_guides_stay_narrow_enough_for_a_terminal():
    for name in guide.FILES.values():
        for n, line in enumerate((BRANDING / name).read_text(encoding="utf-8").splitlines(), 1):
            assert len(line) <= 80, f"{name}:{n} is {len(line)} characters"


def test_language_falls_back_to_english(monkeypatch):
    monkeypatch.setenv("LC_ALL", "es_ES.UTF-8")
    assert guide.language() == "es"
    monkeypatch.setenv("LC_ALL", "fr_FR.UTF-8")
    assert guide.language() == "en"
    assert guide.language("de") == "de"
    assert guide.language("pl") == "en"


def test_guide_path_finds_the_source_tree(monkeypatch):
    monkeypatch.setenv("LC_ALL", "de_DE.UTF-8")
    path = guide.guide_path()
    assert path and path.endswith(guide.FILES["de"])
    assert guide.read().strip()


def test_missing_documentation_is_reported_not_guessed(monkeypatch, tmp_path):
    monkeypatch.setattr(guide, "DOC_DIR", str(tmp_path / "nothing"))
    monkeypatch.setattr(guide, "_source_dir", lambda: str(tmp_path / "nothing"))
    assert guide.guide_path() is None
    assert guide.read() is None


def test_place_on_desktop_happens_once(tmp_path, monkeypatch):
    home = tmp_path / "home"
    desktop = home / "Desktop"
    desktop.mkdir(parents=True)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(guide, "_desktop_dir", lambda h: str(desktop))
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")

    written = guide.place_on_desktop(str(home))
    assert written and os.path.isfile(written)
    assert os.path.basename(written) == guide.FILES["en"]
    assert os.path.exists(guide.marker_path(str(home)))

    # deleted by the user: it does not come back at the next login
    os.remove(written)
    assert guide.place_on_desktop(str(home)) is None
    assert not os.path.exists(written)


def test_place_on_desktop_survives_a_missing_desktop_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(guide, "_desktop_dir", lambda h: str(home / "no-desktop-here"))
    assert guide.place_on_desktop(str(home)) is None
    assert os.path.exists(guide.marker_path(str(home)))


def test_cli_guide_prints_and_reports_the_path(capsys, monkeypatch):
    from ai2 import cli
    monkeypatch.setenv("LC_ALL", "es_ES.UTF-8")
    assert cli.main(["guide", "--path"]) == 0
    assert capsys.readouterr().out.strip().endswith(guide.FILES["es"])
    assert cli.main(["guide", "--lang", "en"]) == 0
    assert "AI-2 GUIDE" in capsys.readouterr().out
