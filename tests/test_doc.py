"""`ai-2 doc`: chunking, the SQLite store, retrieval and the routing gate, with
no server (vectors come from a fake embedder)."""
import os

import pytest

from ai2 import doc, serverstate
from ai2.models import embedding_models


def fake_vec(text: str) -> list[float]:
    """A deterministic 8-dim 'embedding': bag of a few keywords, so texts that
    share words are close and the search has something to rank."""
    keys = ("madrid", "castellano", "bandera", "monarquía", "dieciocho", "tortura", "religión", "x")
    low = text.lower()
    return [1.0 if k in low else 0.05 for k in keys]


def test_chunk_words_overlaps_and_covers_everything():
    words = [f"w{i}" for i in range(300)]
    chunks = doc.chunk_words(" ".join(words), size=110, overlap=20)
    assert chunks[0].split()[0] == "w0" and chunks[-1].split()[-1] == "w299"
    assert chunks[1].split()[0] == "w90"           # step = size - overlap
    assert all(len(c.split()) <= 110 for c in chunks)
    assert doc.chunk_words("   ") == []


def test_fit_chunks_splits_until_under_the_limit():
    count = lambda c: len(c.split()) * 2          # 2 tokens per word
    chunks = ["a b c d e f g h", "one two"]
    out = doc.fit_chunks(chunks, count, limit=8)
    assert out == ["a b c d", "e f g h", "one two"]  # order kept, halves fit
    assert doc.fit_chunks(["singleword"], lambda c: 99, limit=8) == ["singleword"]


def test_fit_ranges_keeps_positions():
    words = "a b c d e f g h".split()
    count = lambda c: len(c.split()) * 2
    assert doc.fit_ranges(words, [(0, 8)], count, limit=8) == [(0, 4), (4, 8)]
    assert doc.fit_ranges(words, [(0, 1)], lambda c: 99, limit=8) == [(0, 1)]


def test_pdf_pages_come_from_the_form_feeds(tmp_path, monkeypatch):
    """pdftotext ends every page with a form feed (39 in the 39-page
    Constitution PDF, checked 2026-09-15); the one after the last page is not a
    page of its own."""
    pdf = tmp_path / "c.pdf"
    pdf.write_bytes(b"%PDF")
    monkeypatch.setattr(doc.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(doc.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": "uno dos\ftres\f\fcuatro\f"})())
    pages, paged = doc.extract_pages(str(pdf))
    assert paged and pages == ["uno dos", "tres", "", "cuatro"]      # an empty page keeps its number
    assert doc.extract_text(str(pdf)).split() == ["uno", "dos", "tres", "cuatro"]
    (tmp_path / "n.txt").write_text("hola\fmundo", encoding="utf-8")
    assert doc.extract_pages(str(tmp_path / "n.txt")) == (["hola\fmundo"], False)


def test_make_chunks_names_the_pages_each_chunk_spans():
    pages = [" ".join(f"p1w{i}" for i in range(100)), " ".join(f"p2w{i}" for i in range(100)), "", "fin"]
    texts, spans, words = doc.make_chunks(pages, True, lambda c: 0, limit=512, size=110, overlap=20)
    assert words == 201
    assert texts[0].split()[0] == "p1w0" and texts[0].split()[-1] == "p2w9"
    assert spans[0] == (1, 2)                       # runs across the page break
    assert spans[1] == (1, 2) and texts[1].split()[0] == "p1w90"
    assert spans[-1] == (2, 4) and texts[-1].split()[-1] == "fin"   # page 3 is empty, "fin" is on page 4
    # split to fit: the halves keep their own pages
    t2, s2, _ = doc.make_chunks(pages[:2], True, lambda c: len(c.split()), limit=60, size=110, overlap=20)
    assert all(len(t.split()) <= 60 for t in t2) and s2[0] == (1, 1) and (2, 2) in s2
    t3, s3, w3 = doc.make_chunks(["sin páginas aquí"], False, lambda c: 0, limit=512)
    assert t3 == ["sin páginas aquí"] and s3 is None and w3 == 3
    assert doc.make_chunks(["", "  "], True, lambda c: 0, limit=512) == ([], [], 0)


def test_cite_prefers_pages_over_parts():
    assert doc.cite({"doc": "c.pdf", "ord": 4, "of": 49, "page": 12, "page_end": 12}) == "c.pdf, page 12"
    assert doc.cite({"doc": "c.pdf", "ord": 4, "of": 49, "page": 12, "page_end": 13}) == "c.pdf, pages 12-13"
    assert doc.cite({"doc": "n.txt", "ord": 4, "of": 49, "page": None, "page_end": None}) == "n.txt, part 5 of 49"
    assert doc.cite({"doc": "n.txt", "ord": 0, "of": 1}) == "n.txt, part 1 of 1"


def test_pages_are_stored_and_old_stores_gain_the_columns(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.sqlite")
    old = sqlite3.connect(path)          # the 0.14.0 schema, with a document in it
    old.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE docs (id INTEGER PRIMARY KEY, name TEXT UNIQUE, path TEXT, added TEXT, words INTEGER, chunks INTEGER);
        CREATE TABLE chunks (id INTEGER PRIMARY KEY, doc_id INTEGER REFERENCES docs(id) ON DELETE CASCADE,
                             ord INTEGER, text TEXT, vec BLOB);
    """)
    old.execute("INSERT INTO docs VALUES (1, 'old.txt', '/old.txt', 'x', 1, 1)")
    old.execute("INSERT INTO chunks VALUES (1, 1, 0, 'Madrid', ?)", (doc.to_blob(fake_vec("Madrid")),))
    old.commit()
    old.close()
    conn = doc.open_store(path)
    hit = doc.search(conn, fake_vec("Madrid"), top=1)[0]
    assert hit["doc"] == "old.txt" and hit["page"] is None and doc.cite(hit) == "old.txt, part 1 of 1"
    doc.add_document(conn, "c.pdf", "/c.pdf", ["La capital es Madrid.", "El castellano."],
                     [fake_vec("Madrid"), fake_vec("castellano")], words=5, pages=[(3, 3), (3, 4)])
    hits = doc.search(conn, fake_vec("castellano"), top=1, doc="c.pdf")
    assert hits[0]["page"] == 3 and hits[0]["page_end"] == 4
    conn.close()
    doc.open_store(path).close()          # opening twice does not add the columns twice


def test_store_roundtrip_search_and_forget(tmp_path):
    conn = doc.open_store(str(tmp_path / "index.sqlite"))
    assert doc.store_model(conn) is None
    doc.set_store_model(conn, "nomic-embed-text-v2-moe", 8)
    chunks = ["La capital del Estado es la villa de Madrid.",
              "El castellano es la lengua española oficial del Estado.",
              "La bandera de España está formada por tres franjas."]
    doc.add_document(conn, "constitucion.txt", "/x/constitucion.txt", chunks,
                     [fake_vec(c) for c in chunks], words=30)
    assert doc.store_model(conn) == "nomic-embed-text-v2-moe"
    hits = doc.search(conn, fake_vec("¿cuál es la capital?"), top=2)
    assert hits[0]["text"].startswith("La capital") and hits[0]["doc"] == "constitucion.txt"
    assert hits[0]["ord"] == 0 and hits[0]["of"] == 3 and len(hits) == 2
    # same name replaces, not duplicates
    doc.add_document(conn, "constitucion.txt", "/x/constitucion.txt", chunks[:1], [fake_vec(chunks[0])], words=8)
    assert doc.list_documents(conn)[0]["chunks"] == 1
    # a vector of another size is skipped rather than crashing the search
    assert doc.search(conn, [1.0, 0.0], top=3) == []
    assert doc.forget(conn, name="nothing") == 0
    assert doc.forget(conn, name="constitucion.txt") == 1
    assert doc.list_documents(conn) == []
    doc.add_document(conn, "a.txt", "/a", ["x"], [fake_vec("x")], words=1)
    assert doc.forget(conn, everything=True) == 1
    assert doc.store_model(conn) is None      # a fresh store may pick another embedder


def test_blob_is_unit_length_float32():
    v = doc.from_blob(doc.to_blob([3.0, 4.0]))
    assert v.typecode == "f" and [round(x, 3) for x in v] == [0.6, 0.8]


def test_extract_text_plain_and_docx_and_unknown(tmp_path):
    p = tmp_path / "notes.md"
    p.write_text("hola mundo", encoding="utf-8")
    assert doc.extract_text(str(p)) == "hola mundo"
    import zipfile
    d = tmp_path / "x.docx"
    with zipfile.ZipFile(d, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:p><w:r><w:t>Primer párrafo</w:t></w:r></w:p>"
                                         "<w:p><w:r><w:t>Segundo</w:t></w:r></w:p></w:document>")
    assert doc.extract_text(str(d)).split() == ["Primer", "párrafo", "Segundo"]
    with pytest.raises(RuntimeError):
        doc.extract_text(str(tmp_path / "x.xyz"))


def test_extract_text_names_the_missing_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(doc.shutil, "which", lambda name: None)
    (tmp_path / "a.pdf").write_bytes(b"%PDF")
    with pytest.raises(RuntimeError, match="pdftotext"):
        doc.extract_text(str(tmp_path / "a.pdf"))
    (tmp_path / "a.png").write_bytes(b"\x89PNG")
    with pytest.raises(RuntimeError, match="tesseract"):
        doc.extract_text(str(tmp_path / "a.png"))


def test_choose_embedder_prefers_multilingual_when_it_fits():
    cat = embedding_models()
    assert doc.choose_embedder(8000, cat)["id"] == "nomic-embed-text-v2-moe"   # Standard, 8 GB
    assert doc.choose_embedder(3800, cat)["id"] == "nomic-embed-text-v2-moe"   # Light 4 GB: 1100 <= 2600
    assert doc.choose_embedder(2000, cat)["id"] == "nomic-embed-text-v1.5"     # Tiny 2 GB: only 300 fits
    assert doc.choose_embedder(1200, cat) is None


def test_prefill_gate_uses_measured_prompt_speed():
    score = {"pp_tps": 2.38, "bench_params_b": 0.5}
    m05 = {"params_b": 0.5}
    # 900 prompt tokens at 2.38 tok/s on the benchmark model: about 6 minutes
    assert round(doc.prefill_seconds(900, score, m05)) == 378
    # a 3B model reads 6x slower by the linear rule
    assert round(doc.prefill_seconds(900, score, {"params_b": 3.0})) == 2269
    assert doc.prefill_seconds(900, None, m05) is None
    assert doc.prefill_seconds(900, {"tg_tps": 2.0}, m05) is None
    assert doc.estimate_tokens("a" * 300) == 101


def test_answer_model_prefers_the_biggest_usable_over_the_starter():
    """rafaminu-pc 2026-09-14: the score recommends Gemma 3 270M (nothing clears
    1.5 tok/s), which produced nonsense over the excerpts; Qwen2.5 0.5B on the
    same disk answers. doc ask picks the largest present model estimated to
    still run at 1 tok/s, not the speed recommendation."""
    from ai2.models import load_catalog
    by_id = {m["id"]: m for m in load_catalog()}
    present = [by_id["gemma3-270m"], by_id["qwen2.5-0.5b"], by_id["smollm3-3b"]]
    score = {"tg_tps": 1.34, "bench_params_b": 0.5}          # rafaminu-pc
    assert doc.choose_answer_model(present, 7800, score)["id"] == "qwen2.5-0.5b"
    fast = {"tg_tps": 40.0, "bench_params_b": 0.5}           # a strong CPU: the 3B clears 1 tok/s
    assert doc.choose_answer_model(present, 7800, fast)["id"] == "smollm3-3b"
    assert doc.choose_answer_model(present, 3800, fast)["id"] == "qwen2.5-0.5b"   # the 3B does not fit 4 GB
    assert doc.choose_answer_model(present, 7800, None)["id"] == "smollm3-3b"     # no score: largest that fits
    assert doc.choose_answer_model([by_id["smollm3-3b"]], 2000, score)["id"] == "smollm3-3b"  # only one, even if it does not fit
    assert doc.choose_answer_model([], 7800, score) is None


def test_build_messages_numbers_the_excerpts():
    hits = [{"text": "El castellano es la lengua oficial.", "doc": "c.pdf", "ord": 2, "of": 37, "score": 0.9},
            {"text": "Madrid es la capital.", "doc": "c.pdf", "ord": 4, "of": 37, "score": 0.8, "page": 7, "page_end": 7}]
    msgs = doc.build_messages("¿Cuál es la capital?", hits)
    assert msgs[0] == {"role": "system", "content": doc.SYSTEM_PROMPT}
    user = msgs[1]["content"]
    assert user.startswith("Question: ¿Cuál es la capital?\n")          # question first
    assert "[1] (c.pdf, part 3 of 37)" in user and "[2] (c.pdf, page 7)" in user
    assert user.rstrip().endswith("If the excerpts do not contain the answer, say so.")
    assert 'Answer the question "¿Cuál es la capital?" in one or two complete sentences' in user


def test_stream_reply_sends_temperature_only_when_asked(monkeypatch):
    import io
    import json
    from ai2 import chatterm
    sent = []

    class FakeResp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        sent.append(json.loads(req.data))
        return FakeResp(b'data: {"choices":[{"delta":{"content":"hola"}}]}\n\ndata: [DONE]\n')
    monkeypatch.setattr(chatterm.urllib.request, "urlopen", fake_urlopen)
    assert "".join(chatterm.stream_reply("http://x", [{"role": "user", "content": "q"}])) == "hola"
    assert "temperature" not in sent[0]
    list(chatterm.stream_reply("http://x", [], temperature=0.2))
    assert sent[1]["temperature"] == 0.2


def test_embedding_server_has_its_own_record(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    serverstate.write_server(os.getpid(), "qwen2.5-0.5b", "/m/q.gguf", 8080, "127.0.0.1")
    serverstate.write_server(os.getpid(), "nomic-embed-text-v2-moe", "/m/n.gguf", doc.EMBED_PORT, "127.0.0.1",
                             name=serverstate.EMBED)
    assert serverstate.read_server()["model"] == "qwen2.5-0.5b"
    assert serverstate.read_server(serverstate.EMBED)["port"] == 8081
    assert serverstate.log_file(serverstate.EMBED).endswith("embed.log")
    serverstate.clear_server(serverstate.EMBED)
    assert serverstate.read_server(serverstate.EMBED) is None
    assert serverstate.read_server() is not None
    serverstate.clear_server()


def test_stop_reports_both_servers(tmp_path, monkeypatch, capsys):
    from ai2 import cli
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    stopped = []
    monkeypatch.setattr(serverstate, "stop_server", lambda name=serverstate.CHAT, **kw: stopped.append(name) or True)
    serverstate.write_server(os.getpid(), "qwen2.5-0.5b", "/m/q.gguf", 8080, "127.0.0.1")
    serverstate.write_server(os.getpid(), "nomic-embed-text-v1.5", "/m/n.gguf", 8081, "127.0.0.1",
                             name=serverstate.EMBED)
    assert cli.main(["stop"]) == 0
    out = capsys.readouterr().out
    assert "Stopping the AI (qwen2.5-0.5b" in out and "document index server (nomic-embed-text-v1.5" in out
    assert stopped == [serverstate.CHAT, serverstate.EMBED]
    serverstate.clear_server(); serverstate.clear_server(serverstate.EMBED)
    assert cli.main(["stop"]) == 0
    assert "No AI-2 server is running" in capsys.readouterr().out


def test_doc_list_and_forget_cli(tmp_path, monkeypatch, capsys):
    from ai2 import cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert cli.main(["doc", "list"]) == 0
    assert "No documents indexed yet" in capsys.readouterr().out
    conn = doc.open_store()
    doc.set_store_model(conn, "nomic-embed-text-v1.5", 8)
    doc.add_document(conn, "c.txt", "/c.txt", ["Madrid"], [fake_vec("Madrid")], words=1)
    conn.close()
    assert cli.main(["doc", "list"]) == 0
    out = capsys.readouterr().out
    assert "c.txt" in out and "nomic-embed-text-v1.5" in out
    assert cli.main(["doc", "forget"]) == 1
    assert cli.main(["doc", "forget", "c.txt"]) == 0
    assert "Forgot 1 document." in capsys.readouterr().out
    assert cli.main(["doc", "forget", "--all"]) == 0
    assert "already empty" in capsys.readouterr().out
    assert cli.main(["doc", "forget", "ghost.txt"]) == 1
    assert "No document named 'ghost.txt'" in capsys.readouterr().out
