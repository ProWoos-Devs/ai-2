"""The translation catalogs must stay complete and sound: every template the
wizard passes to tr() exists in every language, and every translation keeps
exactly the placeholders of its English key. This is what keeps the catalogs
from rotting silently when a wizard string changes."""
import ast
import pathlib
import re

from ai2 import i18n
from ai2.benchmark import STAR_LABELS, feel

SOURCES = [pathlib.Path("ai2/wizard.py"), pathlib.Path("ai2/chatterm.py")]

FEEL_STRINGS = [feel(t) for t in (1, 3, 8, 20)]


def _file_keys(path: pathlib.Path) -> set[str]:
    """Every literal template a source file sends through tr(): direct
    tr(...) calls, and head(n, title) titles (head applies tr itself),
    including conditional titles like ("Ready" if ... else "Almost ready")."""
    keys = set()
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", getattr(node.func, "attr", None))
        if name == "tr" and node.args and isinstance(node.args[0], ast.Constant):
            keys.add(node.args[0].value)
        if name == "head" and len(node.args) == 2:
            arg = node.args[1]
            if isinstance(arg, ast.Constant):
                keys.add(arg.value)
            elif isinstance(arg, ast.IfExp):
                for part in (arg.body, arg.orelse):
                    if isinstance(part, ast.Constant):
                        keys.add(part.value)
    return keys


def required_keys() -> set[str]:
    keys = set().union(*(_file_keys(p) for p in SOURCES))
    return keys | set(STAR_LABELS.values()) | set(FEEL_STRINGS)


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
