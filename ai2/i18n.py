"""Translation of the user-facing prose (the setup wizard, the score
display) into the languages the installer offers. Deliberately not gettext:
no build step, no compiled catalogs, no new dependency. Catalogs are JSON in
ai2/data/i18n/<lang>.json, keyed by the exact English template; tr() returns
the English text unchanged when the language is English or a key is missing,
so a drifted string shows English instead of failing. The language comes
from the process locale, which the installer sets system-wide, so the wizard
speaks the language the user picked in the installer.

Placeholders use str.format ({name}); tests/test_i18n.py enforces that every
catalog value keeps exactly the placeholders of its key, and that every
template the wizard passes to tr() exists in every catalog."""

from __future__ import annotations

import importlib.resources
import json
import os

LANGUAGES = ("es", "de")

_catalog: dict[str, str] | None = None


def _lang() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return value.split("_")[0].split(".")[0].lower()
    return "en"


def load_catalog(lang: str) -> dict[str, str]:
    if lang not in LANGUAGES:
        return {}
    try:
        text = importlib.resources.files("ai2").joinpath(f"data/i18n/{lang}.json").read_text()
        return json.loads(text)
    except (OSError, ValueError):
        return {}


def tr(text: str) -> str:
    global _catalog
    if _catalog is None:
        _catalog = load_catalog(_lang())
    return _catalog.get(text, text)
