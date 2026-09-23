"""The translation catalogs must stay complete and sound: every template the
wizard passes to tr() exists in every language, and every translation keeps
exactly the placeholders of its English key. This is what keeps the catalogs
from rotting silently when a wizard string changes."""
import importlib.util
import pathlib
import re

from ai2 import i18n

_spec = importlib.util.spec_from_file_location(
    "translations", pathlib.Path(__file__).resolve().parent.parent / "tools" / "translations.py")
translations = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(translations)


def required_keys() -> set[str]:
    return translations.tr_keys()


def test_catalogs_cover_every_wizard_string():
    required = required_keys()
    assert required, "found no tr() templates in the source files"
    for lang in i18n.LANGUAGES:
        catalog = i18n.load_catalog(lang)
        assert catalog, f"catalog {lang} missing or empty"
        missing = required - set(catalog)
        assert not missing, f"{lang}.json missing {len(missing)} keys: {sorted(missing)[:3]}"


def test_catalog_values_keep_placeholders():
    for lang in i18n.LANGUAGES:
        for key, value in i18n.load_catalog(lang).items():
            assert isinstance(value, str) and value, f"{lang}: empty value for {key!r}"
            want = set(re.findall(r"\{(\w+)\}", key))
            got = set(re.findall(r"\{(\w+)\}", value))
            assert want == got, f"{lang}: placeholders drifted for {key!r}: {want} vs {got}"


def test_tr_falls_back_to_english(monkeypatch):
    monkeypatch.setattr(i18n, "_catalog", {"known": "bekannt"})
    assert i18n.tr("known") == "bekannt"
    assert i18n.tr("not in any catalog") == "not in any catalog"


def test_lang_from_environment(monkeypatch):
    monkeypatch.setenv("LC_ALL", "es_ES.UTF-8")
    assert i18n._lang() == "es"
    monkeypatch.delenv("LC_ALL")
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    assert i18n._lang() == "de"
