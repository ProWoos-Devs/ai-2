#!/usr/bin/env python3
"""Translation tooling: build the installer catalogs, check them, and report
how far each language has got.

    tools/translations.py build                 compile every lang/*.ts to .qm (needs lrelease)
    tools/translations.py check [--template T]  structure and placeholders; with T, strings
                                                missing from or stale in each .ts
    tools/translations.py coverage [--template T] [--markdown]

The .qm files are build output, never committed: a translator sends the .ts,
CI compiles it to prove it compiles, and the ISO build compiles it again
(iso/stage-profile.sh refuses to stage without a current .qm). T is a .ts
made by `lupdate <branding>/*.qml -ts T`, the list of strings the installer
actually asks for; CI makes one, so a new or changed slide shows up as
missing in every language."""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRANDING = ROOT / "iso/profiles/ai2/live-overlay/usr/share/calamares/branding/ai2"
LANG_DIR = BRANDING / "lang"
DESKTOP_DIR = ROOT / "branding/desktop"
LANGUAGES_JSON = ROOT / "ai2/data/languages.json"
I18N_DIR = ROOT / "ai2/data/i18n"

# The source files whose tr() templates make up the app catalog.
TR_SOURCES = ["ai2/wizard.py", "ai2/chatterm.py", "ai2/updates.py", "ai2/about.py",
              "ai2/packbrowse.py", "ai2/knowledgecli.py", "ai2/cli.py"]
DESKTOP_KEYS = ("Name", "GenericName", "Comment")


def ts_files() -> list[pathlib.Path]:
    return sorted(LANG_DIR.glob("calamares-ai2_*.ts"))


def ts_code(path: pathlib.Path) -> str:
    return path.stem.split("_", 1)[1]


def ts_messages(path: pathlib.Path) -> list[tuple[str, str, bool]]:
    """(source, translation, finished) for every message. Raises on bad XML."""
    out = []
    for message in ET.parse(path).iter("message"):
        source = message.findtext("source") or ""
        tr = message.find("translation")
        text = (tr.text or "") if tr is not None else ""
        unfinished = tr is not None and tr.get("type") in ("unfinished", "vanished", "obsolete")
        out.append((source, text, bool(text) and not unfinished))
    return out


def ts_problems(path: pathlib.Path) -> list[str]:
    """What is wrong with one .ts that no translator should have to guess."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return [f"{path.name}: not valid XML ({exc})"]
    problems = []
    code = ts_code(path)
    if root.get("language") != code:
        problems.append(f'{path.name}: language="{root.get("language")}" should be language="{code}"')
    for source, text, finished in ts_messages(path):
        if not finished:
            continue
        want = sorted(re.findall(r"%\d", source))
        got = sorted(re.findall(r"%\d", text))
        if want != got:
            problems.append(f"{path.name}: placeholders {want} in the English, {got} in the translation of {source[:60]!r}")
    return problems


def template_sources(template: pathlib.Path) -> set[str]:
    return {source for source, _, _ in ts_messages(template)}


def tr_keys() -> set[str]:
    """Every literal template the app sends through tr(): direct tr(...)
    calls, and head(n, title) titles (head applies tr itself), including
    conditional titles like ("Ready" if ... else "Almost ready")."""
    from ai2.benchmark import STAR_LABELS, feel
    keys: set[str] = set()
    for rel in TR_SOURCES:
        tree = ast.parse((ROOT / rel).read_text())
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
    return keys | set(STAR_LABELS.values()) | {feel(t) for t in (1, 3, 8, 20)}


def desktop_entries() -> dict[str, dict[str, str]]:
    """{file name: {key: value}} for the [Desktop Entry] group of each file."""
    out = {}
    for path in sorted(DESKTOP_DIR.glob("*.desktop")):
        entries, group = {}, None
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("["):
                group = line.strip()
            elif group == "[Desktop Entry]" and "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                entries[key.strip()] = value
        out[path.name] = entries
    return out


def languages() -> list[str]:
    codes = set(json.loads(LANGUAGES_JSON.read_text(encoding="utf-8")))
    codes |= {ts_code(p) for p in ts_files()}
    codes |= {p.stem for p in I18N_DIR.glob("*.json")}
    for entries in desktop_entries().values():
        for key in entries:
            m = re.fullmatch(r"\w+\[([^\]]+)\]", key)
            if m:
                codes.add(m.group(1))
    codes.discard("en")
    return sorted(codes)


def coverage(template: pathlib.Path | None) -> list[dict]:
    langs_json = json.loads(LANGUAGES_JSON.read_text(encoding="utf-8"))
    wanted_ts = template_sources(template) if template else None
    keys = tr_keys()
    desktop = desktop_entries()
    # The keys the project translates at all (some are left English on purpose,
    # a product name like "AI-2 Chat", or an autostart entry no menu shows).
    wanted_desktop = [(f, k) for f, e in desktop.items() for k in DESKTOP_KEYS
                      if k in e and any(key.startswith(k + "[") for key in e)]
    rows = []
    for code in languages():
        ts = LANG_DIR / f"calamares-ai2_{code}.ts"
        row = {"lang": code}
        if ts.is_file():
            done = {s for s, _, finished in ts_messages(ts) if finished}
            total = wanted_ts if wanted_ts is not None else {s for s, _, _ in ts_messages(ts)}
            row["installer"] = (len(done & total), len(total))
            row["stale"] = len(done - total) if wanted_ts is not None else 0
        else:
            row["installer"] = (0, len(wanted_ts) if wanted_ts is not None else None)
            row["stale"] = 0
        catalog_path = I18N_DIR / f"{code}.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.is_file() else {}
        row["app"] = (len(keys & set(catalog)), len(keys))
        row["menu"] = (sum(f"{k}[{code}]" in desktop[f] for f, k in wanted_desktop), len(wanted_desktop))
        row["guides"] = code in langs_json
        rows.append(row)
    return rows


def _frac(pair) -> str:
    done, total = pair
    return f"{done}/{total}" if total is not None else f"{done}/?"


def cmd_build(_args) -> int:
    lrelease = shutil.which("lrelease") or next(
        (p for p in ("/usr/lib/qt6/bin/lrelease", "/usr/lib/qt5/bin/lrelease") if pathlib.Path(p).is_file()), None)
    if not lrelease:
        print("lrelease not found (Arch: qt6-tools, Debian/Ubuntu: qt6-l10n-tools)", file=sys.stderr)
        return 2
    failed = 0
    for ts in ts_files():
        rc = subprocess.run([lrelease, "-silent", str(ts), "-qm", str(ts.with_suffix(".qm"))]).returncode
        print(f"{'ok  ' if rc == 0 else 'FAIL'} {ts.name}")
        failed += rc != 0
    return 1 if failed else 0


def cmd_check(args) -> int:
    problems = [p for ts in ts_files() for p in ts_problems(ts)]
    if args.template:
        wanted = template_sources(args.template)
        for ts in ts_files():
            try:
                have = {s for s, _, _ in ts_messages(ts)}
            except ET.ParseError:
                continue
            for source in sorted(wanted - have):
                print(f"note {ts.name}: not translated yet: {source[:70]!r}")
    for p in problems:
        print(f"ERROR {p}")
    return 1 if problems else 0


def cmd_coverage(args) -> int:
    rows = coverage(args.template)
    head = ["Language", "Installer", "App", "Menu entries", "Guides"]
    lines = [[r["lang"], _frac(r["installer"]) + (f" ({r['stale']} stale)" if r["stale"] else ""),
              _frac(r["app"]), _frac(r["menu"]), "yes" if r["guides"] else "no"] for r in rows]
    if args.markdown:
        print("### Translations\n")
        print("| " + " | ".join(head) + " |")
        print("|" + "---|" * len(head))
        for line in lines:
            print("| " + " | ".join(line) + " |")
        print("\nInstaller = calamares-ai2_<lang>.ts, App = ai2/data/i18n/<lang>.json, "
              "Menu entries = Name/GenericName/Comment[<lang>] in branding/desktop, "
              "Guides = an entry in ai2/data/languages.json. Anything missing shows in English.")
    else:
        widths = [max(len(x) for x in col) for col in zip(head, *lines)]
        for line in [head, *lines]:
            print("  ".join(x.ljust(w) for x, w in zip(line, widths)))
    return 0


def main(argv=None) -> int:
    sys.path.insert(0, str(ROOT))
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build").set_defaults(func=cmd_build)
    for name, func in (("check", cmd_check), ("coverage", cmd_coverage)):
        p = sub.add_parser(name)
        p.add_argument("--template", type=pathlib.Path)
        if name == "coverage":
            p.add_argument("--markdown", action="store_true")
        p.set_defaults(func=func)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
