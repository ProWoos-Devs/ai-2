"""Knowledge packs (`ai-2 knowledge`): an `ai-2 doc` collection in one file, so
a computer that indexes fast can do the slow part for one that does not.

A pack is a zip with exactly two members. `index.sqlite` is the collection's
store with every document path blanked (it would name the builder's home
directory), and `manifest.yml` says what it is: id, version, title, license,
attribution, the sources with their URLs, the embedding model with the
SHA-256 of its file (vectors only compare with the exact model that made
them), and the SHA-256 of the index. Installing one makes a collection like
any other, so `ai-2 doc search` and `ask` find it with no extra step.

Two fields carry the version: `version` is what a person reads, and
`revision`, a whole number, is what the code orders by, because arbitrary
version strings cannot be compared reliably. A pack replaces an installed one
of the same id when its revision is the same or higher; an older revision is
refused unless the caller forces it.

A pack is a SQLite file made on someone else's computer, so install follows
https://www.sqlite.org/security.html for untrusted database files: cell size
checks on, schema functions untrusted, no memory-mapped I/O, no triggers or
views, `PRAGMA quick_check` before anything else reads it, and then the
schema must be exactly the `ai-2 doc` tables. Retrieval quality and query
speed were measured before this format was fixed: vectors only, no keyword
table (knowledge packs review 2026-09-15, section 2.3).
"""

from __future__ import annotations

import hashlib
import importlib.resources
import os
import shutil
import sqlite3
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

import yaml

from . import doc, safefetch
from .models import embedding_models
from .safefetch import is_safe_url

FORMAT = 1
SUFFIX = ".ai2pack"
MANIFEST = "manifest.yml"
ORIGIN = "origin.yml"        # where an installed pack came from; local, not part of the pack
MANIFEST_MAX = 1 << 20      # a manifest is a page of YAML; a "manifest" that
                            # unpacks to more than a megabyte is not one, and
                            # reading it first is how a zip bomb gets in
INDEX = "index.sqlite"
_TEMPLATE_KEYS = ("id", "version", "title", "languages", "license", "attribution", "modified", "sources",
                  "revision")
# `version` is what a person reads ("2026-09-16"); `revision` is what the code
# orders by, because arbitrary version strings cannot be compared reliably. A
# pack without one counts as revision 1.
DEFAULT_REVISION = 1
# what `ai-2 doc` creates, nothing else (autoindexes back the UNIQUE and TEXT PRIMARY KEY columns)
_SCHEMA = {("table", "meta"), ("table", "docs"), ("table", "chunks"), ("index", "chunks_doc"),
           ("index", "sqlite_autoindex_meta_1"), ("index", "sqlite_autoindex_docs_1")}


class PackError(Exception):
    pass


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def origin_of(collection: str) -> dict | None:
    """Where an installed pack came from, recorded on this machine at install
    time: a file someone handed over, or a catalog entry with the URL and the
    SHA-256 that was fetched. Kept beside the pack rather than inside it, so
    the artifact stays exactly manifest.yml + index.sqlite, and so the answer
    survives the catalog changing or the machine being offline."""
    path = os.path.join(doc.doc_root(), collection, ORIGIN)
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def manifest_of(collection: str) -> dict | None:
    """The manifest of an installed pack, None for a collection of one's own."""
    path = os.path.join(doc.doc_root(), collection, MANIFEST)
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def source_url(manifest: dict | None, doc_name: str) -> str | None:
    for s in (manifest or {}).get("sources") or []:
        if isinstance(s, dict) and s.get("file") == doc_name and s.get("url"):
            return str(s["url"])
    return None


# ------------------------------------------------------------------ export

def export_pack(collection: str, out_path: str, template: dict | None = None) -> dict:
    """Write the collection as a pack file; returns its manifest. The template
    supplies what a person has to say (title, license, attribution, sources);
    what the store knows (model, counts, hashes) is filled in here and wins."""
    src = doc.index_path(collection)
    if not os.path.isfile(src):
        raise PackError(f"no collection named {collection!r}")
    doc.open_store(src).close()             # a store made by 0.14/0.15 gains the page columns first
    template = template or {}
    unknown = sorted(set(template) - set(_TEMPLATE_KEYS))
    if unknown:
        raise PackError(f"unknown manifest keys: {', '.join(unknown)} (allowed: {', '.join(_TEMPLATE_KEYS)})")
    with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.abspath(out_path)) or ".") as tmp:
        copy = os.path.join(tmp, INDEX)
        live = sqlite3.connect(src)
        dst = sqlite3.connect(copy)
        live.backup(dst)                    # a consistent copy even while the store is open elsewhere
        live.close()
        dst.execute("UPDATE docs SET path = name")
        dst.commit()
        docs = doc.list_documents(dst)
        model_id = doc.store_model(dst)
        dst.execute("VACUUM")
        dst.close()
        if not docs or not model_id:
            raise PackError(f"the collection {collection!r} is empty")
        model = next((m for m in embedding_models() if m["id"] == model_id), None)
        if model is None:
            raise PackError(f"the collection was built with {model_id}, which is not in the catalog")
        manifest = {
            "format": FORMAT,
            "id": template.get("id", collection),
            "version": str(template.get("version", time.strftime("%Y-%m-%d"))),
            "revision": int(template.get("revision", DEFAULT_REVISION)),
            "title": template.get("title", collection),
            "languages": template.get("languages", []),
            "license": template.get("license", "unspecified"),
            "attribution": template.get("attribution", ""),
            "modified": template.get("modified", "Split into parts of about "
                                                 f"{doc.CHUNK_WORDS} words and embedded for search by AI-2."),
            "sources": template.get("sources") or [{"file": d["name"]} for d in docs],
            "embedder": {"id": model["id"], "sha256": model["sha256"]},
            "chunks": {"words": doc.CHUNK_WORDS, "overlap": doc.OVERLAP_WORDS},
            "index": {"sha256": sha256_file(copy), "documents": len(docs),
                      "parts": sum(d["chunks"] for d in docs)},
        }
        problems = check_manifest(manifest)
        if problems:
            raise PackError("; ".join(problems))
        tmp_out = out_path + ".part"
        with zipfile.ZipFile(tmp_out, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(MANIFEST, yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False))
            z.write(copy, INDEX)
        os.replace(tmp_out, out_path)
    return manifest


# ----------------------------------------------------------------- install

def check_manifest(m: object) -> list[str]:
    """Everything wrong with a manifest, as sentences; empty when it is usable."""
    if not isinstance(m, dict):
        return ["manifest.yml is not a mapping"]
    problems = []
    if m.get("format") != FORMAT:
        problems.append(f"pack format {m.get('format')!r}, this AI-2 reads format {FORMAT} (update ai-2)")
    if not isinstance(m.get("id"), str) or not doc.valid_collection(m["id"]):
        problems.append(f"pack id {m.get('id')!r} is not a valid collection name")
    for key in ("version", "title"):
        if not isinstance(m.get(key), str) or not m[key]:
            problems.append(f"{key} is missing")
    emb = m.get("embedder") if isinstance(m.get("embedder"), dict) else {}
    model = next((x for x in embedding_models() if x["id"] == emb.get("id")), None)
    if model is None:
        problems.append(f"embedding model {emb.get('id')!r} is not in this AI-2's catalog")
    elif emb.get("sha256") != model["sha256"]:
        problems.append(f"the pack was built with a different file of {model['id']} than the catalog's")
    revision = m.get("revision", DEFAULT_REVISION)
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        problems.append(f"revision {revision!r} is not a positive whole number")
    idx = m.get("index") if isinstance(m.get("index"), dict) else {}
    if not isinstance(idx.get("sha256"), str) or len(idx["sha256"]) != 64:
        problems.append("index sha256 is missing")
    if not isinstance(m.get("sources", []), list):
        problems.append("sources is not a list")
    return problems


# sqlite.org/security.html for an untrusted database: DEFENSIVE on, the
# schema/trigger/view switches off. A missing setconfig (Python before 3.12)
# still has the PRAGMAs below and the schema allowlist in check_index.
_UNTRUSTED_DBCONFIG = (
    ("SQLITE_DBCONFIG_DEFENSIVE", True),
    ("SQLITE_DBCONFIG_TRUSTED_SCHEMA", False),
    ("SQLITE_DBCONFIG_ENABLE_TRIGGER", False),
    ("SQLITE_DBCONFIG_ENABLE_VIEW", False),
)


def _open_untrusted(path: str) -> sqlite3.Connection:
    """Connection settings first (they read nothing from the file), then
    quick_check as the first statement that does."""
    conn = sqlite3.connect(path)
    for name, on in _UNTRUSTED_DBCONFIG:
        if hasattr(conn, "setconfig") and hasattr(sqlite3, name):      # Python 3.12 and later
            conn.setconfig(getattr(sqlite3, name), on)
    for pragma in ("PRAGMA cell_size_check=ON", "PRAGMA trusted_schema=OFF", "PRAGMA mmap_size=0"):
        conn.execute(pragma)
    ok = conn.execute("PRAGMA quick_check").fetchone()
    if not ok or ok[0] != "ok":
        conn.close()
        raise PackError("the index inside the pack is damaged (quick_check failed)")
    return conn


def check_index(path: str, manifest: dict) -> None:
    """The index inside a pack is an `ai-2 doc` store and agrees with its
    manifest, or PackError says what is wrong."""
    try:
        conn = _open_untrusted(path)
    except sqlite3.DatabaseError as exc:
        raise PackError(f"the index inside the pack is not a usable SQLite file ({exc})") from exc
    try:
        found = {(t, n) for t, n in conn.execute("SELECT type, name FROM sqlite_master")}
        extra = sorted(f"{t} {n}" for t, n in found - _SCHEMA)
        if extra or not {("table", "meta"), ("table", "docs"), ("table", "chunks")} <= found:
            raise PackError("the index inside the pack has an unexpected schema"
                            + (f" ({', '.join(extra)})" if extra else ""))
        row = conn.execute("SELECT value FROM meta WHERE key = 'model'").fetchone()
        if not row or row[0] != manifest["embedder"]["id"]:
            raise PackError("the index and the manifest name different embedding models")
        docs, parts = conn.execute("SELECT COUNT(*), COALESCE(SUM(chunks), 0) FROM docs").fetchone()
        n_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        idx = manifest["index"]
        if docs != idx.get("documents") or parts != idx.get("parts") or n_chunks != parts:
            raise PackError("the index does not hold the documents and parts the manifest lists")
    except sqlite3.DatabaseError as exc:
        raise PackError(f"the index inside the pack is not an ai-2 doc index ({exc})") from exc
    finally:
        conn.close()


def read_manifest(pack_path: str) -> dict:
    """The manifest of a pack file, checked, without unpacking the index."""
    try:
        with zipfile.ZipFile(pack_path) as z:
            names = set(z.namelist())
            if names != {MANIFEST, INDEX}:
                raise PackError(f"not an AI-2 pack (members {', '.join(sorted(names)) or 'none'}; "
                                f"expected {MANIFEST} and {INDEX})")
            declared = z.getinfo(MANIFEST).file_size
            if declared > MANIFEST_MAX:
                raise PackError(f"the manifest in this file unpacks to {declared} bytes; "
                                f"a manifest is a page of YAML (limit {MANIFEST_MAX})")
            with z.open(MANIFEST) as fh:
                raw = fh.read(MANIFEST_MAX + 1)        # the declared size is the zip's word, not the truth
            if len(raw) > MANIFEST_MAX:
                raise PackError("the manifest in this file is larger than it declares")
            manifest = yaml.safe_load(raw.decode("utf-8"))
    except (zipfile.BadZipFile, OSError, yaml.YAMLError, UnicodeDecodeError) as exc:
        raise PackError(f"not an AI-2 pack ({exc})") from exc
    problems = check_manifest(manifest)
    if problems:
        raise PackError("; ".join(problems))
    return manifest


def revision_of(manifest: dict | None) -> int:
    """The revision a manifest declares, or 1 when it does not."""
    try:
        return int((manifest or {}).get("revision", DEFAULT_REVISION))
    except (TypeError, ValueError):
        return DEFAULT_REVISION


def install_pack(pack_path: str, name: str | None = None, force: bool = False,
                 origin: dict | None = None) -> tuple[str, dict, dict | None]:
    """Unpack, check and install a pack as a collection. Returns (collection,
    manifest, manifest of the version it replaced or None). A pack replaces an
    installed pack of the same id when its revision is the same or higher; an
    older revision is refused unless `force`, so a file handed over by another
    route cannot quietly put a pack back. It never overwrites a collection of
    one's own or a different pack."""
    manifest = read_manifest(pack_path)
    target = name or manifest["id"]
    if not doc.valid_collection(target):
        raise PackError(f"{target!r} is not a collection name (lower-case letters, digits, '.', '-', '_')")
    previous = None
    if target in doc.list_collections():
        previous = manifest_of(target)
        if previous is None or previous.get("id") != manifest["id"]:
            raise PackError(f"a collection named {target!r} already exists and is not this pack; "
                            "install under another name with --as NAME")
        here, incoming = revision_of(previous), revision_of(manifest)
        if incoming < here and not force:
            raise PackError(f"{target} is at revision {here} ({previous.get('version')}) and this file is "
                            f"revision {incoming} ({manifest.get('version')}), which is older; "
                            "install it anyway with --force")
    root = doc.doc_root()
    os.makedirs(root, exist_ok=True)
    with zipfile.ZipFile(pack_path) as z:
        size = z.getinfo(INDEX).file_size
        if shutil.disk_usage(root).free < size + (64 << 20):
            raise PackError(f"not enough free disk space for the index ({size // (1 << 20)} MB)")
        staging = tempfile.mkdtemp(prefix=".install-", dir=root)     # a leading dot is never a collection
        try:
            dest = os.path.join(staging, INDEX)
            h = hashlib.sha256()
            with z.open(INDEX) as src, open(dest, "wb") as out:
                for block in iter(lambda: src.read(1 << 20), b""):
                    h.update(block)
                    out.write(block)
            if h.hexdigest() != manifest["index"]["sha256"]:
                raise PackError("the index inside the pack does not match its manifest (sha256)")
            check_index(dest, manifest)
            with open(os.path.join(staging, MANIFEST), "w", encoding="utf-8") as fh:
                yaml.safe_dump(manifest, fh, allow_unicode=True, sort_keys=False)
            record = dict(origin or {"from": "file", "file": os.path.basename(pack_path)})
            record.setdefault("installed", time.strftime("%Y-%m-%d %H:%M"))
            record.setdefault("sha256", sha256_file(pack_path))
            with open(os.path.join(staging, ORIGIN), "w", encoding="utf-8") as fh:
                yaml.safe_dump(record, fh, allow_unicode=True, sort_keys=False)
            final = os.path.join(root, target)
            old = None
            if os.path.exists(final):
                old = tempfile.mkdtemp(prefix=".old-", dir=root)
                os.replace(final, os.path.join(old, target))
            try:
                os.replace(staging, final)
            except OSError:
                if old:
                    os.replace(os.path.join(old, target), final)    # put the installed version back
                raise
            staging = None
            if old:
                shutil.rmtree(old, ignore_errors=True)
        finally:
            if staging:
                shutil.rmtree(staging, ignore_errors=True)
    return target, manifest, previous


def installed_packs() -> list[tuple[str, dict]]:
    return [(n, m) for n in doc.list_collections() if (m := manifest_of(n)) is not None]


# ----------------------------------------------------------------- catalog

# The community catalog: where every Knowledge Pack is listed, the project's own
# included, where a person downloads one and where they share one they made.
# Every surface that mentions packs points here (Rafael, 2026-09-19: "point
# there from EVERYWHERE").
CATALOG_URL = "https://github.com/ProWoos-Devs/ai2-knowledge"

# What the origin record calls a pack installed by name. Records written before
# 0.18.7 say "official catalog"; there is one catalog now, the community's, so
# they are read as the same thing.
CATALOG_ORIGIN = "community catalog"
_OLD_CATALOG_ORIGINS = ("official catalog",)


def origin_label(origin: dict | None) -> str:
    where = str((origin or {}).get("from") or "unknown source")
    return CATALOG_ORIGIN if where in _OLD_CATALOG_ORIGINS else where


def load_catalog() -> list[dict]:
    """The packs AI-2 knows how to fetch by name: the copy of the community
    catalog that ships inside the ai-2 package, so the SHA-256 of every entry
    is covered by the signature on the package itself; a pack is only as
    trustworthy as where its hash came from."""
    data = yaml.safe_load(importlib.resources.files("ai2").joinpath("data/packs.yml").read_text())
    return list((data or {}).get("packs") or [])


def catalog_entry(pack_id: str) -> dict | None:
    return next((p for p in load_catalog() if p.get("id") == pack_id), None)


class HttpsOnlyRedirect(safefetch.HttpsOnlyRedirect):
    """The shared rule (safefetch), reported as a pack error."""

    error = PackError


def download_pack(entry: dict, dest_dir: str, progress=None) -> str:
    """Fetch a cataloged pack into dest_dir and return the file. Resumes an
    interrupted attempt with a Range request (old laptops on wifi), checks the
    size and the SHA-256, and keeps nothing that does not match."""
    os.makedirs(dest_dir, exist_ok=True)
    final = os.path.join(dest_dir, f"{entry['id']}-{entry['version']}{SUFFIX}")
    if os.path.isfile(final) and sha256_file(final) == entry["sha256"]:
        return final
    part = final + ".part"
    have = os.path.getsize(part) if os.path.isfile(part) else 0
    headers = {"User-Agent": "ai-2"}
    if have:
        headers["Range"] = f"bytes={have}-"
    if not is_safe_url(entry.get("url", "")):
        raise PackError(f"{entry.get('id')} has a url that is not https")
    limit = int(entry.get("size_bytes") or 0)
    req = urllib.request.Request(entry["url"], headers=headers)
    opener = urllib.request.build_opener(HttpsOnlyRedirect)
    with opener.open(req, timeout=60) as resp:
        mode = "ab" if (have and resp.status == 206) else "wb"
        if mode == "wb":
            have = 0
        length = int(resp.headers.get("Content-Length") or 0)
        total = have + length if length else int(entry.get("size_bytes") or 0)
        done = have
        with open(part, mode) as out:
            for chunk in iter(lambda: resp.read(1 << 20), b""):
                out.write(chunk)
                done += len(chunk)
                if limit and done > limit:
                    out.close()
                    os.remove(part)
                    raise PackError(f"the download is larger than the catalog says ({limit} bytes); stopped")
                if progress:
                    progress(done, total)
    size = os.path.getsize(part)
    if entry.get("size_bytes") and size != entry["size_bytes"]:
        raise PackError(f"download incomplete: {size} of {entry['size_bytes']} bytes "
                        "(run the same command again to resume)")
    got = sha256_file(part)
    if got != entry["sha256"]:
        os.remove(part)
        raise PackError(f"checksum mismatch for {entry['id']}: expected {entry['sha256'][:12]}..., "
                        f"got {got[:12]}... (file removed)")
    os.replace(part, final)
    return final
