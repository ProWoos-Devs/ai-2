"""Build personal collections using the ordinary AI-2 indexer and pack format."""
from __future__ import annotations

from contextlib import closing
import errno
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata

from . import doc, pack, runtime
from .i18n import tr
from .models import embedding_models

DETAILS = "creator.json"


def run_cli(arguments, *, env=None, report=None, started=None):
    """Use the installed CLI and its normal engine. Keep progress out of GTK's thread."""
    command = [sys.executable, "-u", "-m", "ai2.cli", *map(str, arguments)]
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, errors="replace", env=env) as process:
        if started:
            started(process)
        output = []
        for line in process.stdout:
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


def create(title, language, paths, notes, report=None, started=None):
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
        run_cli(["doc", "index", "--in", "draft", "--embedder", model["id"], "--", *paths],
                env=env, report=report, started=started)
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
