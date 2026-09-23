#!/usr/bin/env python3
"""Translation tooling: build the installer catalogs, check them, and report
how far each language has got.

    tools/translations.py build                 compile every lang/*.ts to .qm (needs lrelease)
    tools/translations.py check [--template T]  structure and placeholders; with T, strings
                                                missing from or stale in each .ts
    tools/translations.py coverage [--template T] [--markdown]
    tools/translations.py credits               the README's table of translators, from translators.json
    tools/translations.py readme [--write]      the generated blocks in README.md and TRANSLATING.md
                                                (installer languages, translators); without
                                                --write, exit 1 if they are out of date
    tools/translations.py stale --template T    per language, the texts of the parts it has
                                                started that are not translated yet
    tools/translations.py issues --template T [--dry-run]
                                                open or update one issue per language with
                                                stale texts, mentioning its translators (CI,
                                                when a release is published)

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
TRANSLATORS_JSON = ROOT / "translators.json"
README = ROOT / "README.md"
ISSUE_TITLE = "Translation update: {name} ({code})"

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


def translators() -> dict[str, dict]:
    """{code: {"language": its own name, "translators": [{name, github, url?}]}}"""
    return json.loads(TRANSLATORS_JSON.read_text(encoding="utf-8"))


def language_name(code: str) -> str:
    return translators().get(code, {}).get("language", code)


def credits_rows() -> list[str]:
    """One README table row per language, English first, in the order of
    translators.json."""
    rows = []
    for code, entry in translators().items():
        people = entry["translators"]
        names = ", ".join(f"[{p['name']}]({p.get('url') or 'https://github.com/' + p['github']})" for p in people)
        rows.append(f"| {language_name(code)} | `{code}` | {names} |")
    return rows


def installer_languages() -> list[str]:
    """English plus every language with an installer catalog, in the order
    of translators.json, by their English names."""
    have = {"en"} | {ts_code(p) for p in ts_files()}
    listed = translators()
    order = [c for c in listed if c in have] + sorted(have - set(listed))
    return [listed.get(c, {}).get("english", c) for c in order]


GENERATED = {
    "installer-languages": lambda: "\n".join(f"- {name}" for name in installer_languages()),
    "translators": lambda: "| Language | Code | Translated by |\n|---|---|---|\n" + "\n".join(credits_rows()),
}
GENERATED_IN = {"installer-languages": [README, ROOT / "TRANSLATING.md"], "translators": [README]}


def render_generated(text: str, block: str) -> str:
    start, end = f"<!-- {block}:start -->", f"<!-- {block}:end -->"
    before, rest = text.split(start, 1)
    _, after = rest.split(end, 1)
    return f"{before}{start}\n{GENERATED[block]()}\n{end}{after}"


def stale(template: pathlib.Path) -> dict[str, dict[str, list[str]]]:
    """Per language, what is untranslated in the parts it has started: the
    installer if it has a .ts, the app if it has a catalog, and each menu
    file where it has at least one key. A part nobody has taken on is not
    stale, it is simply not translated, and nobody is chased about it."""
    wanted_ts = template_sources(template)
    keys = tr_keys()
    desktop = desktop_entries()
    out: dict[str, dict[str, list[str]]] = {}
    for code in languages():
        found: dict[str, list[str]] = {}
        ts = LANG_DIR / f"calamares-ai2_{code}.ts"
        if ts.is_file():
            done = {s for s, _, finished in ts_messages(ts) if finished}
            if missing := sorted(wanted_ts - done):
                found[f"iso/profiles/ai2/live-overlay/usr/share/calamares/branding/ai2/lang/{ts.name}"] = missing
        catalog_path = I18N_DIR / f"{code}.json"
        if catalog_path.is_file():
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            if missing := sorted(keys - set(catalog)):
                found[f"ai2/data/i18n/{code}.json"] = missing
        for name, entries in desktop.items():
            if not any(k.endswith(f"[{code}]") for k in entries):
                continue
            missing = [f"{k}={entries[k]}" for k in DESKTOP_KEYS
                       if k in entries and any(key.startswith(k + "[") for key in entries)
                       and f"{k}[{code}]" not in entries]
            if missing:
                found[f"branding/desktop/{name}"] = missing
        if found:
            out[code] = found
    return out


def issue_body(code: str, found: dict[str, list[str]]) -> str:
    people = translators().get(code, {}).get("translators", [])
    mentions = " ".join(f"@{p['github']}" for p in people)
    lines = [f"{mentions} English texts changed in this release, and these are not in {language_name(code)} yet. "
             "Until they are, they show in English, so nothing is broken.", ""]
    for path, items in found.items():
        # a fenced block per file: the texts carry line breaks, backticks do not
        lines += [f"**{path}**, {len(items)} text{'s' if len(items) != 1 else ''}", "```text"]
        lines.append("\n\n".join(item.strip("\n") for item in items))
        lines += ["```", ""]
    lines.append("How to add them is in https://github.com/ProWoos-Devs/ai-2/blob/main/TRANSLATING.md. "
                 "One pull request for all of them is fine, and so is saying here that you cannot do it now.")
    return "\n".join(lines)


def _github(method: str, path: str, payload: dict | None = None):
    import os
    import urllib.request
    req = urllib.request.Request(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}{path}",
        method=method, data=json.dumps(payload).encode() if payload else None,
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"null")


def cmd_credits(_args) -> int:
    print("\n".join(credits_rows()))
    return 0


def cmd_readme(args) -> int:
    outdated = []
    for block, paths in GENERATED_IN.items():
        for path in paths:
            text = path.read_text(encoding="utf-8")
            new = render_generated(text, block)
            if new != text:
                outdated.append(f"{path.name}: {block}")
                if args.write:
                    path.write_text(new, encoding="utf-8")
    for item in outdated:
        print(("rewrote " if args.write else "out of date: ") + item)
    return 1 if outdated and not args.write else 0


def cmd_stale(args) -> int:
    print(json.dumps(stale(args.template), ensure_ascii=False, indent=1))
    return 0


def cmd_issues(args) -> int:
    found_all = stale(args.template)
    if not found_all:
        print("every started translation is complete")
        return 0
    open_issues = [] if args.dry_run else _github("GET", "/issues?state=open&per_page=100")
    for code, found in found_all.items():
        title = ISSUE_TITLE.format(name=language_name(code), code=code)
        body = issue_body(code, found)
        existing = next((i for i in open_issues if i["title"] == title and "pull_request" not in i), None)
        if args.dry_run:
            print(f"== {'update' if existing else 'open'}: {title}\n{body}\n")
        elif existing:
            _github("POST", f"/issues/{existing['number']}/comments",
                    {"body": "Still missing after this release:\n\n" + body})
            print(f"commented on #{existing['number']} {title}")
        else:
            issue = _github("POST", "/issues", {"title": title, "body": body})
            print(f"opened #{issue['number']} {title}")
    return 0


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
    sub.add_parser("credits").set_defaults(func=cmd_credits)
    p = sub.add_parser("readme")
    p.add_argument("--write", action="store_true")
    p.set_defaults(func=cmd_readme)
    p = sub.add_parser("stale")
    p.add_argument("--template", type=pathlib.Path, required=True)
    p.set_defaults(func=cmd_stale)
    p = sub.add_parser("issues")
    p.add_argument("--template", type=pathlib.Path, required=True)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_issues)
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
