"""Build personal collections using the ordinary AI-2 indexer and pack format."""
from __future__ import annotations

from contextlib import closing
import errno
import importlib.resources
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata

import yaml

from . import __version__, doc, pack, runtime
from .i18n import tr
from .models import embedding_models

DETAILS = "creator.json"
LICENSES = ("CC-BY-4.0", "CC-BY-SA-4.0", "CC0-1.0", "public-domain", "MIT",
            "CC-BY-SA-3.0", "CC-BY-SA-2.5", "CC-BY-3.0", "Apache-2.0",
            "GFDL-1.3-or-later", "PSF-2.0", "OGL-3.0")


def _segments(stream):
    """The text of a child's output, a piece at a time, split at a newline or a
    carriage return. The indexer ends a progress update with no newline and
    starts the next one with a carriage return, so reading by lines would hand
    each update over only when the next one arrives, one batch late (about 36 s
    on a 2011 laptop, 2026-11-26). An update that came whole is passed on at once."""
    pending = ""
    while True:
        chunk = stream.read1(4096) if hasattr(stream, "read1") else stream.read(4096)
        if not chunk:
            break
        pending += chunk.decode("utf-8", "replace") if isinstance(chunk, bytes) else chunk
        *done, pending = re.split(r"[\r\n]", pending)
        yield from done
        if _DOC_PARTS.match(pending.strip()) and pending.endswith("left   "):
            yield pending
            pending = ""
    if pending:
        yield pending


def run_cli(arguments, *, env=None, report=None, started=None):
    """Use the installed CLI and its normal engine. Keep progress out of GTK's thread."""
    command = [sys.executable, "-u", "-m", "ai2.cli", *map(str, arguments)]
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, env=env) as process:
        if started:
            started(process)
        output = []
        for line in _segments(process.stdout):
            line = line.strip()
            if line:
                # Keep diagnostics even if following documents print many progress updates.
                if not re.match(r"^\d+/\d+ parts,|^\d+ MB\s+\d+%", line):
                    if "no text found (a scanned PDF needs OCR" in line and "skipped " in line:
                        filename = line.split("skipped ", 1)[1].rsplit(": no text found", 1)[0]
                        line = tr("No readable text in {file}. For a scanned PDF, run text recognition (OCR) first.").format(file=filename)
                    output.append(line)
                if report:
                    report(line)
        if process.wait():
            raise ValueError("\n".join(output) or tr("The operation could not be completed."))
    return "\n".join(output)


_DOC_START = re.compile(r"^(.+): \d+ words in (\d+) parts, ")
_DOC_PARTS = re.compile(r"^(\d+)/(\d+) parts, \d+ s, about (\d+) min left")


def index_progress(line, state, count):
    """What a line of `ai-2 doc index` says about how far the import is, as
    {document, documents, name, done, total, minutes, fraction}, or None for a
    line that says nothing about it. `state` is a dict this keeps between
    lines; `count` is how many documents were handed to the indexer. The
    minutes are the indexer's own estimate for the document it is on."""
    start = _DOC_START.match(line)
    if start:
        state.update(document=state.get("document", 0) + 1, name=start.group(1),
                     done=0, total=int(start.group(2)), minutes=None)
    else:
        parts = _DOC_PARTS.match(line)
        if not parts or not state.get("document"):
            return None
        state.update(done=int(parts.group(1)), total=int(parts.group(2)), minutes=int(parts.group(3)))
    count = max(count, state["document"])
    within = state["done"] / state["total"] if state["total"] else 0
    return dict(state, documents=count, fraction=min(1.0, (state["document"] - 1 + within) / count))


def valid_language(language):
    return bool(re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", language))


def model_for(language):
    wanted = "nomic-embed-text-v1.5" if language.split("-")[0] == "en" else "nomic-embed-text-v2-moe"
    return next(m for m in embedding_models() if m["id"] == wanted)


def private_collections():
    result = {}
    for name in doc.list_collections():
        path = Path(doc.index_path(name)).with_name(DETAILS)
        try:
            details = json.loads(path.read_text(encoding="utf-8"))
            if (isinstance(details, dict) and isinstance(details.get("title"), str)
                    and isinstance(details.get("languages"), list) and not pack.manifest_of(name)):
                result[name] = details
        except (OSError, ValueError):
            continue
    return result


def create(title, language, paths, notes, report=None, started=None, progress=None):
    title = title.strip()
    paths = [Path(p).absolute() for p in paths]
    if not title or not (paths or notes.strip()):
        raise ValueError(tr("Enter a title and add a document or some notes."))
    if not valid_language(language):
        raise ValueError(tr("Choose a language for the documents."))
    names = {path.name for path in paths}
    if len(names) != len(paths):
        raise ValueError(tr("Two files have the same name. Rename one before adding both."))
    model = model_for(language)
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    base = re.sub("[^a-z0-9]+", "-", ascii_title.lower()).strip("-")[:56] or "my-pack"
    root = Path(doc.doc_root())
    root.mkdir(parents=True, exist_ok=True)
    reserved = {entry["id"] for entry in pack.load_catalog()} | {doc.DEFAULT_COLLECTION}
    with tempfile.TemporaryDirectory(dir=root, prefix=".create-") as tmp:
        # The collection is invisible to readers until every input has succeeded.
        staging = Path(tmp)
        note_path = None
        if notes.strip():
            note_name = tr("Notes.txt")
            while note_name in names:
                note_name = "_" + note_name
            note_path = staging / note_name
            note_path.write_text(notes, encoding="utf-8")
            paths.append(note_path)
        model_path = runtime.find_model_file(model["file"])
        env = dict(os.environ, XDG_DATA_HOME=tmp, AI2_SYSTEM_DOC_DIR=str(staging / "system"),
                   AI2_MODEL_DIR=os.path.dirname(model_path) if model_path else runtime.model_dir())
        state, count = {}, len(paths)

        def relay(line):
            info = index_progress(line, state, count) if progress else None
            if info:
                progress(info)
            if report:
                report(line)
        run_cli(["doc", "index", "--in", "draft", "--embedder", model["id"], "--", *paths],
                env=env, report=relay, started=started)
        collection = staging / "ai2/doc/draft"
        collection.chmod(0o700)
        details = {"title": title, "languages": [language]}
        (collection / DETAILS).write_text(json.dumps(details, ensure_ascii=False), encoding="utf-8")
        if note_path:
            note_path.rename(collection / "notes-source.txt")
        number = 1
        while True:
            name = base if number == 1 else f"{base}-{number}"
            number += 1
            if name in reserved or (root / name).exists() or doc.is_system(name):
                continue
            if note_path:
                with closing(sqlite3.connect(collection / "index.sqlite")) as conn:
                    conn.execute("UPDATE docs SET path=? WHERE name=?",
                                 (str(root / name / "notes-source.txt"), note_path.name))
                    conn.commit()
            try:
                collection.rename(root / name)
                return name, details
            except OSError as exc:
                if exc.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                    raise


def save_pack(name, details, destination):
    """The old file, if any, survives a failed export, including on removable media."""
    destination = Path(destination)
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        prepared = Path(tmp) / "export.ai2pack"
        manifest = pack.export_pack(name, str(prepared), details)
        os.replace(prepared, destination)
    return manifest


def try_question(name, question):
    return run_cli(["doc", "search", "--in", name, "--", question])


def prepare_community(name, details, parent, contact, license_id, credit, category, ages=()):
    contact, credit = contact.strip(), credit.strip()
    if not contact or not credit or license_id not in LICENSES or category not in pack.load_categories()["categories"]:
        raise ValueError(tr("Enter the author, source credits, license and category."))
    if pack.catalog_entry(name):
        raise ValueError(tr("This Knowledge Pack ID is already in the catalog. Follow the catalog guide to update it."))
    final = Path(parent) / (name + "-submission")
    if final.exists():
        raise ValueError(tr("A submission folder already exists here. Choose another location."))
    with tempfile.TemporaryDirectory(dir=parent) as tmp:
        bundle = Path(tmp) / "submission"
        relative = Path("packs") / name / f"{name}-r1.ai2pack"
        out = bundle / relative
        out.parent.mkdir(parents=True)
        manifest = pack.export_pack(name, str(out), dict(details, license=license_id, attribution=credit))
        if out.stat().st_size > 10 * 1024 * 1024:
            raise ValueError(tr("The Knowledge Pack exceeds the catalog’s 10 MiB limit. See the submission guide."))
        entry = {k: manifest[k] for k in ("id", "title", "version", "revision", "languages", "license", "attribution")}
        entry.update(embedder=manifest["embedder"]["id"], contact=contact, categories=[category],
                     url="https://raw.githubusercontent.com/ProWoos-Devs/ai2-knowledge/main/" + relative.as_posix(),
                     size_bytes=out.stat().st_size, sha256=pack.sha256_file(out),
                     documents=manifest["index"]["documents"], parts=manifest["index"]["parts"],
                     built_with="ai-2 " + __version__)
        if ages:
            entry.update(audience="children", ages=list(ages))
        (bundle / "catalog-entry.yml").write_text(yaml.safe_dump([entry], allow_unicode=True, sort_keys=False),
                                                 encoding="utf-8")
        with tempfile.TemporaryDirectory() as scratch:
            _check_submission(Path(scratch), bundle, entry)
        bundle.rename(final)
    return final


def _check_submission(check, bundle, entry):
    # Run the catalog's own offline checks against this candidate, including a real
    # install in a throwaway home. This pinned MIT tool is copied verbatim from
    # ProWoos-Devs/ai2-knowledge@0cf0c1375b245c4be40d6036fbe2d7a98c21c33d.
    data = importlib.resources.files("ai2").joinpath("data")
    (check / "tools").mkdir()
    (check / "catalog").mkdir()
    (check / "packs").symlink_to((bundle / "packs").resolve(), target_is_directory=True)
    validator = check / "tools/validate-catalog.py"
    validator.write_bytes(data.joinpath("validate-catalog.py").read_bytes())
    (check / "catalog/categories.yml").write_bytes(data.joinpath("pack-categories.yml").read_bytes())
    catalog_file = check / "catalog/community.yml"
    catalog_file.write_text(yaml.safe_dump({"version": 1, "packs": [entry]}), encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent.parent),
               AI2_SYSTEM_DOC_DIR=str(check / "system"))
    result = subprocess.run([sys.executable, validator, "--install", catalog_file],
                            capture_output=True, text=True, env=env)
    if result.returncode:
        raise ValueError(result.stdout.strip() or result.stderr.strip())
