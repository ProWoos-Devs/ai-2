"""Knowledge packs (`ai-2 doc pack`): an `ai-2 doc` collection in one file, so
a computer that indexes fast can do the slow part for one that does not.

A pack is a zip with exactly two members. `index.sqlite` is the collection's
store with every document path blanked (it would name the builder's home
directory), and `manifest.yml` says what it is: id, version, title, license,
attribution, the sources with their URLs, the embedding model with the
SHA-256 of its file (vectors only compare with the exact model that made
them), and the SHA-256 of the index. Installing one makes a collection like
any other, so `ai-2 doc search` and `ask` find it with no extra step.

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
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile

import yaml

from . import doc
from .models import embedding_models

FORMAT = 1
SUFFIX = ".ai2pack"
MANIFEST = "manifest.yml"
INDEX = "index.sqlite"
_TEMPLATE_KEYS = ("id", "version", "title", "languages", "license", "attribution", "modified", "sources")
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
    idx = m.get("index") if isinstance(m.get("index"), dict) else {}
    if not isinstance(idx.get("sha256"), str) or len(idx["sha256"]) != 64:
        problems.append("index sha256 is missing")
    if not isinstance(m.get("sources", []), list):
        problems.append("sources is not a list")
    return problems


def _open_untrusted(path: str) -> sqlite3.Connection:
    """Connection settings first (they read nothing from the file), then
    quick_check as the first statement that does."""
    conn = sqlite3.connect(path)
    for flag in ("SQLITE_DBCONFIG_TRUSTED_SCHEMA", "SQLITE_DBCONFIG_ENABLE_TRIGGER", "SQLITE_DBCONFIG_ENABLE_VIEW"):
        if hasattr(conn, "setconfig") and hasattr(sqlite3, flag):      # Python 3.12 and later
            conn.setconfig(getattr(sqlite3, flag), False)
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
            manifest = yaml.safe_load(z.read(MANIFEST).decode("utf-8"))
    except (zipfile.BadZipFile, OSError, yaml.YAMLError, UnicodeDecodeError) as exc:
        raise PackError(f"not an AI-2 pack ({exc})") from exc
    problems = check_manifest(manifest)
    if problems:
        raise PackError("; ".join(problems))
    return manifest


def install_pack(pack_path: str, name: str | None = None) -> tuple[str, dict, dict | None]:
    """Unpack, check and install a pack as a collection. Returns (collection,
    manifest, manifest of the version it replaced or None). A pack replaces an
    installed pack of the same id (an update); it never overwrites a
    collection of one's own or a different pack."""
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
