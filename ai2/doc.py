"""Ask the AI about your own documents (`ai-2 doc`), the rag block the tier
files have declared since the first release, finally with something behind it.

How it works, on the runtime AI-2 already ships. `ai-2 doc index FILE` turns
the file into text (pdftotext, tesseract for scans, plain text as is), cuts it
into chunks of about a hundred words, embeds every chunk with an embedding
model through llama-server's /v1/embeddings (a second, small on-demand server,
see serverstate.EMBED) and keeps text and vector in a SQLite file. `ai-2 doc
ask QUESTION` embeds the question the same way, takes the closest chunks by
cosine, and hands them to the chat model together with the question, locally
or through the remote AI. Nothing but Python's standard library is involved.

The embedders are nomic's: they need the `search_document: ` / `search_query: `
prefixes (prefix_document / prefix_query in the catalog) or retrieval degrades
silently, and their context is the chunk ceiling (512 tokens for the MoE), so
every chunk is tokenized by the server and split when it is too long.

Honesty rule for these machines: on the validated laptops prompt processing
runs at generation speed (about 2 tok/s on the 2011 one), so the excerpts we
prepend to the question cost minutes before the first word. prefill_seconds()
estimates that from the stored AI Score; `ai-2 doc ask` sends the question to
the remote AI when it is configured and the local answer would be a starter
model or a long wait, and says so, because the excerpts leave the computer.
"""

from __future__ import annotations

import array
import json
import math
import os
import shutil
import sqlite3
import subprocess
import time
import urllib.request
import zipfile

from .models import RAM_HEADROOM_MIB, embedding_models

EMBED_PORT = 8081          # the chat server has 8080
EMBED_IDLE_S = 600         # the embedding server never stays resident, even on persistent tiers
CHUNK_WORDS = 110
OVERLAP_WORDS = 20
TOP_K = 3
SLOW_PREFILL_S = 60        # above this the local answer is "minutes", route to the remote if there is one
ANSWER_MIN_TG = 1.0        # the answering model may be slower than the chat floor (1.5); the user accepted a wait
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".log", ".rst", ".text"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


# ---------------------------------------------------------------- the store

def data_dir() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "ai2")


def index_path() -> str:
    return os.path.join(data_dir(), "doc", "index.sqlite")


def open_store(path: str | None = None) -> sqlite3.Connection:
    path = path or index_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS docs (
            id INTEGER PRIMARY KEY, name TEXT UNIQUE, path TEXT, added TEXT,
            words INTEGER, chunks INTEGER);
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY, doc_id INTEGER REFERENCES docs(id) ON DELETE CASCADE,
            ord INTEGER, text TEXT, vec BLOB);
        CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
    """)
    return conn


def store_model(conn: sqlite3.Connection) -> str | None:
    """The embedding model every vector in this store came from (one store,
    one model: vectors of different models do not compare)."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'model'").fetchone()
    return row[0] if row else None


def set_store_model(conn: sqlite3.Connection, model_id: str, dims: int) -> None:
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('model', ?)", (model_id,))
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('dims', ?)", (str(dims),))
    conn.commit()


def to_blob(vec) -> bytes:
    """Unit-length float32 bytes, so cosine is a plain dot product later."""
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return array.array("f", (x / norm for x in vec)).tobytes()


def from_blob(blob: bytes) -> array.array:
    a = array.array("f")
    a.frombytes(blob)
    return a


def add_document(conn: sqlite3.Connection, name: str, path: str, chunks: list[str],
                 vectors: list, words: int) -> int:
    """Replace any document of the same name; returns its id."""
    conn.execute("DELETE FROM docs WHERE name = ?", (name,))
    cur = conn.execute("INSERT INTO docs (name, path, added, words, chunks) VALUES (?, ?, ?, ?, ?)",
                       (name, path, time.strftime("%Y-%m-%d %H:%M"), words, len(chunks)))
    doc_id = cur.lastrowid
    conn.executemany("INSERT INTO chunks (doc_id, ord, text, vec) VALUES (?, ?, ?, ?)",
                     [(doc_id, i, text, to_blob(vec)) for i, (text, vec) in enumerate(zip(chunks, vectors))])
    conn.commit()
    return doc_id


def list_documents(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT name, path, added, words, chunks FROM docs ORDER BY added, name").fetchall()
    return [dict(zip(("name", "path", "added", "words", "chunks"), r)) for r in rows]


def forget(conn: sqlite3.Connection, name: str | None = None, everything: bool = False) -> int:
    """Remove one document (by name) or all of them; returns how many."""
    if everything:
        n = conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        conn.execute("DELETE FROM docs")
        conn.execute("DELETE FROM meta")
    else:
        n = conn.execute("DELETE FROM docs WHERE name = ?", (name,)).rowcount
    conn.commit()
    return n


def search(conn: sqlite3.Connection, qvec, top: int = TOP_K, doc: str | None = None) -> list[dict]:
    """The `top` chunks closest to qvec (cosine), each with its document name,
    position and score. A few thousand chunks is a fraction of a second in
    plain Python; that is the whole vector store."""
    q = array.array("f", qvec)
    qn = math.sqrt(sum(x * x for x in q)) or 1.0
    sql = ("SELECT chunks.text, chunks.ord, docs.name, docs.chunks, chunks.vec FROM chunks "
           "JOIN docs ON docs.id = chunks.doc_id")
    params: tuple = ()
    if doc:
        sql += " WHERE docs.name = ?"
        params = (doc,)
    hits = []
    for text, ord_, name, total, blob in conn.execute(sql, params):
        v = from_blob(blob)
        if len(v) != len(q):
            continue
        score = sum(a * b for a, b in zip(q, v)) / qn
        hits.append({"text": text, "ord": ord_, "doc": name, "of": total, "score": score})
    hits.sort(key=lambda h: -h["score"])
    return hits[:top]


# ------------------------------------------------------- text and chunking

def extract_text(path: str, lang: str = "eng") -> str:
    """Plain text of a file: text files as they are, PDFs through pdftotext,
    .docx through its XML, images through tesseract (the documents workflow
    installs both tools). Raises RuntimeError naming the missing tool."""
    suffix = os.path.splitext(path)[1].lower()
    if suffix in TEXT_SUFFIXES or suffix == "":
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    if suffix == ".pdf":
        if not shutil.which("pdftotext"):
            raise RuntimeError("pdftotext is not installed (package poppler); ai-2 workflow install documents")
        return subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True,
                              check=True).stdout
    if suffix == ".docx":
        import re
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml)
    if suffix in IMAGE_SUFFIXES:
        if not shutil.which("tesseract"):
            raise RuntimeError("tesseract is not installed; ai-2 workflow install documents")
        return subprocess.run(["tesseract", path, "-", "-l", lang], capture_output=True, text=True,
                              check=True).stdout
    raise RuntimeError(f"unsupported file type {suffix or '(none)'}: text, PDF, DOCX or an image (scan)")


def chunk_words(text: str, size: int = CHUNK_WORDS, overlap: int = OVERLAP_WORDS) -> list[str]:
    """Windows of `size` words that overlap by `overlap`, so a sentence cut at
    a boundary still appears whole in one of them."""
    words = text.split()
    if not words:
        return []
    step = max(1, size - overlap)
    out = []
    for start in range(0, len(words), step):
        out.append(" ".join(words[start:start + size]))
        if start + size >= len(words):
            break
    return out


def fit_chunks(chunks: list[str], count_tokens, limit: int) -> list[str]:
    """Every chunk at or under `limit` tokens as the server counts them (with
    the document prefix included by the caller's counter); a long one is split
    in halves until it fits. Non-causal models refuse inputs above n_ubatch."""
    out = []
    stack = list(reversed(chunks))
    while stack:
        c = stack.pop()
        if count_tokens(c) <= limit:
            out.append(c)
            continue
        words = c.split()
        if len(words) < 2:
            out.append(c)   # one huge word, nothing to split; the server will say no
            continue
        mid = len(words) // 2
        stack.append(" ".join(words[mid:]))
        stack.append(" ".join(words[:mid]))
    return out


# ------------------------------------------------------- the servers' side

class EmbedClient:
    """Talks to a llama-server started with --embeddings."""

    def __init__(self, url: str, model: dict):
        self.url = url.rstrip("/")
        self.model = model

    def _post(self, path: str, payload: dict, timeout: float = 3600):
        req = urllib.request.Request(self.url + path, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def ntokens(self, text: str) -> int:
        return len(self._post("/tokenize", {"content": text}, timeout=120)["tokens"])

    def embed(self, texts: list[str], batch: int = 8, progress=None) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), batch):
            r = self._post("/v1/embeddings", {"input": texts[i:i + batch]})
            out += [d["embedding"] for d in sorted(r["data"], key=lambda d: d["index"])]
            if progress:
                progress(len(out), len(texts))
        return out

    def embed_documents(self, chunks: list[str], progress=None) -> list[list[float]]:
        # batches of 4: on the reference laptops a part takes 10-20 s, and the
        # progress line should move more often than every two minutes
        p = self.model.get("prefix_document", "")
        return self.embed([p + c for c in chunks], batch=4, progress=progress)

    def embed_query(self, question: str) -> list[float]:
        return self.embed([self.model.get("prefix_query", "") + question])[0]

    def token_limit(self) -> int:
        return int(self.model.get("ctx", 512)) - 8


def choose_embedder(ram_mib: int, catalog: list[dict] | None = None) -> dict | None:
    """The embedder for a new index on this machine: the multilingual one when
    its measured peak fits next to the OS headroom, else the largest that
    fits, else None."""
    budget = max(0, ram_mib - RAM_HEADROOM_MIB)
    fits = [m for m in (catalog or embedding_models()) if m["ram_peak_mb"] <= budget]
    if not fits:
        return None
    multi = [m for m in fits if m.get("multilingual")]
    return max(multi or fits, key=lambda m: m["params_b"])


def choose_answer_model(present: list[dict], ram_mib: int, score: dict | None) -> dict | None:
    """The chat model `ai-2 doc ask` answers with. Not the speed recommendation:
    on rafaminu-pc that is the 270M starter, which cannot read excerpts at all
    (it answered a question about the Constitution with "I am programmed to be
    a safe and helpful AI assistant", 2026-09-14) while Qwen2.5 0.5B on the
    same disk can. So, the largest model on disk that fits RAM and is estimated
    from the AI Score to generate at least ANSWER_MIN_TG tok/s; failing that the
    largest that fits; without a score the same. `present` is the chat catalog
    filtered to files on disk."""
    from .models import estimate_tps
    budget = max(0, ram_mib - RAM_HEADROOM_MIB)
    fits = [m for m in present if m["ram_peak_mb"] <= budget] or list(present)
    if not fits:
        return None
    if score and score.get("tg_tps"):
        fast = [m for m in fits
                if estimate_tps(float(score["tg_tps"]), float(score.get("bench_params_b") or 0.5),
                                float(m["params_b"])) >= ANSWER_MIN_TG]
        if fast:
            return max(fast, key=lambda m: m["params_b"])
    return max(fits, key=lambda m: m["params_b"])


def estimate_tokens(text: str) -> int:
    """Rough token count for the prefill gate (about 3 characters per token in
    Spanish and German, more in English); only the order of magnitude matters."""
    return len(text) // 3 + 1


def prefill_seconds(n_tokens: int, score: dict | None, model: dict | None) -> float | None:
    """How long the local chat model needs to read a prompt of n_tokens, from
    the stored AI Score's measured prompt speed scaled by the linear rule the
    recommender uses (speed falls with parameter count). None when unknown."""
    if not score or not model:
        return None
    pp = float(score.get("pp_tps") or 0)
    if pp <= 0:
        return None
    est = pp * float(score.get("bench_params_b") or 0.5) / float(model["params_b"])
    return n_tokens / est if est > 0 else None


def build_messages(question: str, hits: list[dict], system: str) -> list[dict]:
    excerpts = "\n\n".join(f"[{i}] ({h['doc']}, part {h['ord'] + 1} of {h['of']})\n{h['text']}"
                           for i, h in enumerate(hits, 1))
    user = (f"Excerpts from my documents:\n\n{excerpts}\n\n"
            f"Question: {question}\n"
            "Answer from the excerpts and cite them as [1], [2]. If they do not contain the answer, say so.")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def doc_system_prompt(base: str) -> str:
    return (base + " The user's question comes with numbered excerpts from their own documents; "
            "answer from those excerpts, cite them as [1], [2], and say plainly when they do not "
            "contain the answer.")
