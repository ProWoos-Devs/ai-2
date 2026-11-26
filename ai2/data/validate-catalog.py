#!/usr/bin/env python3
"""Check the community catalog, which lists every pack, the AI-2 project's own
included.

Three layers, each stricter than the last:

  (none)     every entry complete, licences redistributable, ids unique,
             hashes the right shape, the maker named, categories, audience
             and ages taken from catalog/categories.yml; the pack's file
             is in this repository under packs/, in the right place, and
             matches the entry's size and SHA-256
  --install  install the pack with AI-2 itself and compare the manifest
             inside it against what the catalog entry claims

Every pack's file lives in this repository. Nothing is downloaded: on a pull
request the file is read from the checkout. (--fetch is still accepted and
does nothing more than the plain check.)

The third layer is the one that matters for a contributed pack: the hash only
proves the bytes are the ones the entry described, not that the entry
describes them truthfully. It needs the `ai2` package importable.

CI installs **v0.18.0 on purpose**, which is the oldest released ai-2 that
understands a pack's `revision`, so the check answers "does this artifact
install on the oldest AI-2 that knows about packs as they are now", not merely
"does it install here". Contributors build with a newer one (0.18.1 added
`ai-2 doc index --embedder`); that difference is the point, not an oversight.
Raise this baseline only when a pack-format change makes an older AI-2 unable
to install a current pack at all.

  pip install "ai2 @ git+https://github.com/ProWoos-Devs/ai-2@v0.18.0"

  python3 tools/validate-catalog.py [--install] [catalog/*.yml]
"""
import hashlib
import os
import re
import shutil
import sqlite3
import sys
import tempfile

import yaml

REQUIRED = ("id", "title", "version", "revision", "languages", "license", "embedder", "url",
            "size_bytes", "sha256", "documents", "parts", "contact", "categories")
# `revision` is required even though a missing one would be read as 1: it is the
# field AI-2 orders by, and a contributor who never wrote it down is a
# contributor who will forget to raise it on the next rebuild. `contact` is
# required because one catalog holds everybody's packs, the project's included,
# and who made a pack is what a person goes by when deciding to trust it.

# Redistribution allowed, and any attribution the licence wants goes in the
# manifest, where AI-2 prints it with every answer. Non-commercial and
# no-derivatives licences are not here on purpose.
LICENCES = {"CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "CC-BY-SA-3.0", "CC-BY-SA-2.5", "CC-BY-3.0",
            "MIT", "Apache-2.0", "GFDL-1.3-or-later", "public-domain", "PSF-2.0", "OGL-3.0"}
ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SHA = re.compile(r"^[0-9a-f]{64}$")
ATTRIBUTION_NEEDED = ("CC-BY", "GFDL", "PSF", "OGL", "MIT", "Apache")
# These two require the recipient to RECEIVE the licence (Apache-2.0 §4a, and
# GFDL's requirement to include a copy), which no attribution line can do. The
# pack is the distribution, so the licence text has to travel inside it as one
# of its documents. Being on this list does not make a pack compliant; it makes
# the one obligation we can check mechanically checkable.
LICENCE_TEXT_NEEDED = ("Apache-2.0", "GFDL")
LICENCE_DOC = re.compile(r"(licen[cs]e|notice|copying)", re.I)


# Every pack's file lives in this repository, under packs/, and comes in the
# same pull request as its entry. Its url is the address that file has once
# the pull request is merged. No file hosted anywhere else is listed: a link
# to someone else's server can die or change hands, and then the catalog
# points at nothing. The file name carries the revision and an old revision
# is never overwritten or removed, because every released ai-2 carries a copy
# of the catalog and goes on asking for the file that copy names. The limit
# is there because whatever is committed stays in the history for good.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN_REPO = "https://raw.githubusercontent.com/ProWoos-Devs/ai2-knowledge/main/"
IN_REPO_LIMIT = 10 * 1024 * 1024


def in_repo_file(p: dict) -> str | None:
    """Where the pack's file is in the checkout, if its url says it lives in
    this repository; None otherwise, which the catalog does not accept."""
    url = str(p.get("url", ""))
    return os.path.join(ROOT, *url[len(IN_REPO):].split("/")) if url.startswith(IN_REPO) else None


def in_repo_check(where: str, p: dict) -> list[str]:
    """The file is where its id and revision say, and is the one the entry
    describes. No network: on a pull request the url does not exist yet."""
    expected = f"packs/{p.get('id')}/{p.get('id')}-r{p.get('revision')}.ai2pack"
    if str(p.get("url", ""))[len(IN_REPO):] != expected:
        return [f"{where}: a pack kept in this repository goes at {expected}, so its url is {IN_REPO}{expected}"]
    path = os.path.join(ROOT, *expected.split("/"))
    if not os.path.isfile(path):
        return [f"{where}: {expected} is not in the repository; add the file to the pull request"]
    problems = []
    size = os.path.getsize(path)
    if size > IN_REPO_LIMIT:
        problems.append(f"{where}: {size} bytes is over the {IN_REPO_LIMIT} bytes a file in this repository "
                        "may be; open an issue before sending a pack this large")
    if size != p.get("size_bytes"):
        problems.append(f"{where}: {expected} is {size} bytes, the entry says {p.get('size_bytes')}")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    if h.hexdigest() != p.get("sha256"):
        problems.append(f"{where}: sha256 of {expected} is {h.hexdigest()}, the entry says {p.get('sha256')}")
    return problems


# What the catalog entry and the pack's own manifest must agree on. Everything
# here is what a person reads before deciding to install, so a catalog that
# says one thing while the artifact says another is the failure this catches.
# `attribution` is deliberately not here: the catalog may word it more briefly
# than the pack does, and what matters (that the pack carries one at all) is
# checked below.
COMPARED = ("id", "title", "version", "license", "languages", "revision")

# Categories, audiences and age ranges live in one file beside the catalog.
# They are catalog fields only: a pack's manifest does not carry them, so a
# pack can be moved to a better branch without being rebuilt.
TAXONOMY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "catalog", "categories.yml")
CODE = re.compile(r"^[0-9]{2}(\.[0-9]{2})*$")


def load_taxonomy(path: str = TAXONOMY) -> tuple[dict, list[str]]:
    """Read categories.yml and check it is a tree: every code well formed and
    quoted, none twice, every branch under a class that exists, every name
    present. Returns the known codes, audiences and ages, and what is wrong."""
    problems = []
    data = yaml.safe_load(open(path, encoding="utf-8")) or {}
    if data.get("version") != 1:
        problems.append(f"{path}: version {data.get('version')!r}, expected 1")
    known = {"categories": {}, "audiences": set(), "ages": set()}
    for i, c in enumerate(data.get("categories") or []):
        code = c.get("code") if isinstance(c, dict) else None
        where = f"{path} categories[{i}]"
        if not isinstance(code, str) or not CODE.match(code):
            problems.append(f"{where}: code {code!r} is not two digits per level in quotes, like '11.01'")
            continue
        if code in known["categories"]:
            problems.append(f"{where}: code {code} appears twice")
        if "." in code and code.rsplit(".", 1)[0] not in known["categories"]:
            problems.append(f"{where}: {code} is listed before its parent {code.rsplit('.', 1)[0]}, "
                            "or the parent does not exist")
        if not str(c.get("en", "")).strip():
            problems.append(f"{where}: {code} has no English name")
        known["categories"][code] = str(c.get("en", ""))
    for field in ("audiences", "ages"):
        for i, a in enumerate(data.get(field) or []):
            ident = a.get("id") if isinstance(a, dict) else None
            if not ident or not str(a.get("en", "")).strip():
                problems.append(f"{path} {field}[{i}]: needs an id and an English name")
            elif ident in known[field]:
                problems.append(f"{path} {field}[{i}]: {ident} appears twice")
            known[field].add(ident)
    if "general" not in known["audiences"] or "children" not in known["audiences"]:
        problems.append(f"{path}: audiences must include general and children")
    return known, problems


def check_classification(where: str, p: dict, known: dict) -> list[str]:
    """The entry's categories, audience and ages, against categories.yml."""
    problems = []
    cats = p.get("categories")
    if cats in (None, "", []):
        return problems                                 # reported as missing already
    if not isinstance(cats, list):
        return [f"{where}: categories is not a list"]
    for c in cats:
        if not isinstance(c, str):
            problems.append(f"{where}: category {c!r} is not in quotes; write codes as strings, "
                            "like '11.10', because YAML turns 11.10 unquoted into the number 11.1")
        elif c not in known["categories"]:
            problems.append(f"{where}: category {c} is not in catalog/categories.yml; "
                            "propose a new branch in the same pull request if none fits")
    if len(set(map(str, cats))) != len(cats):
        problems.append(f"{where}: a category is listed twice")
    audience = p.get("audience", "general")
    if audience not in known["audiences"]:
        problems.append(f"{where}: audience {audience!r} is not one of {', '.join(sorted(known['audiences']))}")
    ages = p.get("ages")
    if audience == "children":
        if not isinstance(ages, list) or not ages:
            problems.append(f"{where}: a pack for children names its ages, one or more of "
                            f"{', '.join(sorted(known['ages']))}")
        else:
            for a in ages:
                if a not in known["ages"]:
                    problems.append(f"{where}: age range {a!r} is not one of {', '.join(sorted(known['ages']))}")
            if len(set(map(str, ages))) != len(ages):
                problems.append(f"{where}: an age range is listed twice")
    elif ages is not None:
        problems.append(f"{where}: ages is only for a pack whose audience is children")
    return problems


def check(path: str, fetch: bool, install: bool = False, seen_ids: set | None = None,
          known: dict | None = None) -> list[str]:
    problems = []
    if known is None:
        known, trouble = load_taxonomy()
        problems += trouble
    data = yaml.safe_load(open(path, encoding="utf-8")) or {}
    if data.get("version") != 1:
        problems.append(f"{path}: catalog version {data.get('version')!r}, expected 1")
    seen = set()
    for i, p in enumerate(data.get("packs") or []):
        where = f"{path}[{i}]"
        if not isinstance(p, dict):
            problems.append(f"{where}: not a mapping")
            continue
        where = f"{path} {p.get('id', '?')}"
        for field in REQUIRED:
            if p.get(field) in (None, "", []):
                problems.append(f"{where}: {field} is missing")
        if not ID.match(str(p.get("id", ""))):
            problems.append(f"{where}: id is not usable as a collection name")
        if p.get("id") in seen:
            problems.append(f"{where}: id appears twice")
        seen.add(p.get("id"))
        if seen_ids is not None:
            if p.get("id") in seen_ids:
                problems.append(f"{where}: id is already used in another catalog file; ids are global, "
                                "so one pack can never be installed in place of another")
            seen_ids.add(p.get("id"))
        if p.get("license") not in LICENCES:
            problems.append(f"{where}: licence {p.get('license')!r} is not one this catalog carries "
                            f"({', '.join(sorted(LICENCES))})")
        elif any(p["license"].startswith(k) for k in ATTRIBUTION_NEEDED) and not str(p.get("attribution", "")).strip():
            problems.append(f"{where}: {p['license']} needs an attribution line")
        if not SHA.match(str(p.get("sha256", ""))):
            problems.append(f"{where}: sha256 is not 64 hex characters")
        if p.get("url") and not in_repo_file(p):
            problems.append(f"{where}: the file must be in this repository, at "
                            f"packs/{p.get('id')}/{p.get('id')}-r{p.get('revision')}.ai2pack, with the url "
                            f"{IN_REPO}packs/{p.get('id')}/{p.get('id')}-r{p.get('revision')}.ai2pack; "
                            "a file hosted anywhere else is not listed")
        if not isinstance(p.get("languages"), list):
            problems.append(f"{where}: languages is not a list")
        problems += check_classification(where, p, known)
        if not problems:
            problems += in_repo_check(where, p)
        if fetch and not problems:
            downloaded, trouble = fetch_check(where, p)
            problems += trouble
            if install and downloaded and not trouble:
                problems += install_check(where, p, downloaded)
            if downloaded:
                os.remove(downloaded)
    return problems


def fetch_check(where: str, p: dict) -> tuple[str | None, list[str]]:
    """A copy of the pack's file for the install check, which installs it and
    then deletes it. The file itself was checked by in_repo_check already."""
    local = in_repo_file(p)
    fd, path = tempfile.mkstemp(suffix=".ai2pack")
    os.close(fd)
    shutil.copyfile(local, path)
    print(f"  read {os.path.relpath(local, ROOT)}", flush=True)
    return path, []


def install_check(where: str, p: dict, path: str) -> list[str]:
    """Install the downloaded pack with AI-2 itself and compare the manifest
    inside it with the catalog entry. This is what a hash cannot do: the hash
    says the bytes are the ones described, not that the description is true."""
    try:
        from ai2 import doc, pack
    except ImportError:
        return [f"{where}: --install needs the ai2 package "
                "(pip install \"git+https://github.com/ProWoos-Devs/ai-2@v0.18.0\")"]
    before = os.environ.get("XDG_DATA_HOME")
    with tempfile.TemporaryDirectory() as home:
        os.environ["XDG_DATA_HOME"] = home          # install into a machine of its own
        try:
            collection, manifest, _ = pack.install_pack(path)
            index_file = doc.index_path(collection)     # while XDG_DATA_HOME still points here
        except pack.PackError as exc:
            return [f"{where}: AI-2 refuses this pack ({exc})"]
        finally:
            if before is None:
                os.environ.pop("XDG_DATA_HOME", None)
            else:
                os.environ["XDG_DATA_HOME"] = before
        problems = []
        for field in COMPARED:
            fallback = pack.DEFAULT_REVISION if field == "revision" else None
            claimed, actual = p.get(field, fallback), manifest.get(field, fallback)
            if claimed is not None and actual != claimed:
                problems.append(f"{where}: the catalog says {field}={claimed!r}, the pack says {actual!r}")
        # The manifest names the embedder as an id with the SHA-256 of the model
        # file; the catalog entry carries only the id, which is what a person
        # needs to know (a pack is only searchable by the model that built it).
        built_with = (manifest.get("embedder") or {}).get("id")
        if p.get("embedder") != built_with:
            problems.append(f"{where}: the catalog says embedder={p.get('embedder')!r}, "
                            f"the pack was built with {built_with!r}")
        index = manifest.get("index") or {}
        for field in ("documents", "parts"):
            if p.get(field) is not None and index.get(field) != p[field]:
                problems.append(f"{where}: the catalog says {field}={p[field]}, the pack says {index.get(field)}")
        conn = sqlite3.connect(index_file)
        rows = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        if index.get("parts") is not None and rows != index["parts"]:
            problems.append(f"{where}: the installed index holds {rows} parts, "
                            f"the manifest says {index['parts']}")
        licence = str(manifest.get("license", ""))
        if any(licence.startswith(k) for k in LICENCE_TEXT_NEEDED):
            names = [r[0] for r in conn.execute("SELECT name FROM docs")]
            if not any(LICENCE_DOC.search(n or "") for n in names):
                problems.append(f"{where}: {licence} requires the recipient to receive the licence, so the pack "
                                "must carry its text as one of its documents (a file named LICENSE, NOTICE or "
                                "COPYING). None of these is in it: " + ", ".join(names[:8]))
        if not str(manifest.get("attribution", "")).strip() and \
                any(licence.startswith(k) for k in ATTRIBUTION_NEEDED):
            problems.append(f"{where}: {manifest.get('license')} needs an attribution line in the manifest, "
                            "which is where AI-2 reads it from when it prints an answer")
        conn.close()
        print(f"  installed as {collection}: {rows} parts, {manifest.get('license')}", flush=True)
        return problems


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    fetch = "--fetch" in sys.argv or "--install" in sys.argv
    install = "--install" in sys.argv
    known, problems = load_taxonomy()
    seen_ids: set = set()
    for path in args or ["catalog/community.yml"]:
        problems += check(path, fetch, install, seen_ids, known)
    for line in problems:
        print("error:", line)
    print(f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
