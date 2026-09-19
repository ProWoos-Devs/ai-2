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


def test_a_pack_builder_can_choose_the_small_english_embedder(capsys):
    """Without --embedder a roomy machine picks the multilingual model, which
    is right for a person's own documents and wrong for a pack meant to be
    shared: everyone who installs it would have to fetch 345 MB."""
    from ai2 import cli
    hw = type("HW", (), {"ram_mib": 8000})()
    assert cli._doc_embedder(doc, hw, None, None, "mypack")["id"] == "nomic-embed-text-v2-moe"
    assert cli._doc_embedder(doc, hw, "nomic-embed-text-v1.5", None, "mypack")["id"] == "nomic-embed-text-v1.5"

    # a collection keeps the model it was built with, and says where to go instead
    assert cli._doc_embedder(doc, hw, "nomic-embed-text-v1.5", "nomic-embed-text-v2-moe", "mypack") is None
    err = capsys.readouterr().err
    assert "cannot change" in err and "--in NEWNAME --embedder nomic-embed-text-v1.5" in err

    # an unknown name lists the real ones, and a model too big for the machine is refused
    assert cli._doc_embedder(doc, hw, "no-such-model", None, "mypack") is None
    assert "nomic-embed-text-v1.5" in capsys.readouterr().err
    assert cli._doc_embedder(doc, type("HW", (), {"ram_mib": 2000})(), "nomic-embed-text-v2-moe",
                             None, "mypack") is None
    assert "can spare" in capsys.readouterr().err


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


def test_doc_search_prints_passages_without_a_chat_model(tmp_path, monkeypatch, capsys):
    from ai2 import cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    started = []
    monkeypatch.setattr(cli, "_ensure_server", lambda hw, model, port, record, **kw: started.append((model["id"], record)) or "http://127.0.0.1:8081/")
    monkeypatch.setattr(doc.EmbedClient, "embed_query", lambda self, q: fake_vec(q))
    assert cli.main(["doc", "search", "capital"]) == 1
    assert "No documents indexed yet" in capsys.readouterr().err and started == []
    conn = doc.open_store()
    doc.set_store_model(conn, "nomic-embed-text-v2-moe", 8)
    doc.add_document(conn, "c.pdf", "/c.pdf", ["La capital del Estado es la villa de Madrid.", "El castellano es la lengua oficial."],
                     [fake_vec("Madrid"), fake_vec("castellano")], words=14, pages=[(3, 3), (3, 4)])
    doc.add_document(conn, "n.txt", "/n.txt", ["Notas sin páginas sobre la bandera."], [fake_vec("bandera")], words=5)
    conn.close()
    assert cli.main(["doc", "search", "--top", "2", "¿Dónde", "está", "Madrid?"]) == 0
    out = capsys.readouterr().out
    assert "[1] c.pdf, page 3\n    La capital del Estado es la villa de Madrid." in out
    assert "[2] " in out and "[3] " not in out
    assert started == [("nomic-embed-text-v2-moe", serverstate.EMBED)]      # the embedding server only, no chat model
    assert cli.main(["doc", "search", "--doc", "n.txt", "bandera"]) == 0
    assert "[1] n.txt, part 1 of 1" in capsys.readouterr().out
    assert cli.main(["doc", "search", "--doc", "ghost.pdf", "x"]) == 1
    assert "No document named 'ghost.pdf'" in capsys.readouterr().err


def _store(name, model, docs):
    conn = doc.open_store(doc.index_path(name))
    doc.set_store_model(conn, model, 8)
    for doc_name, texts in docs.items():
        doc.add_document(conn, doc_name, "/" + doc_name, texts, [fake_vec(t) for t in texts], words=len(texts))
    conn.close()


def test_collection_names_and_the_legacy_index_moves_in_place(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert doc.valid_collection("constitucion-es") and doc.valid_collection("python3.14_docs")
    for bad in ("", "Docs", "../x", "a/b", ".hidden", "-x", "x" * 65):
        assert not doc.valid_collection(bad)
    assert doc.list_collections() == []
    legacy = tmp_path / "data" / "ai2" / "doc" / "index.sqlite"      # where 0.14 and 0.15 kept it
    conn = doc.open_store(str(legacy))
    doc.set_store_model(conn, "nomic-embed-text-v1.5", 8)
    doc.add_document(conn, "old.txt", "/old.txt", ["Madrid"], [fake_vec("Madrid")], words=1)
    conn.close()
    assert doc.list_collections() == ["documents"]
    assert not legacy.exists() and os.path.isfile(doc.index_path("documents"))
    assert doc.list_documents(doc.open_store())[0]["name"] == "old.txt"
    os.makedirs(doc.doc_root() + "/Not-A-Name")
    assert doc.list_collections() == ["documents"]


def test_search_across_collections_merges_and_names_them(tmp_path):
    a = doc.open_store(str(tmp_path / "a.sqlite"))
    b = doc.open_store(str(tmp_path / "b.sqlite"))
    for conn, name, text in ((a, "a.txt", "La capital es Madrid."), (b, "b.txt", "Madrid, capital y bandera.")):
        doc.set_store_model(conn, "m", 8)
        doc.add_document(conn, name, "/" + name, [text, "otra cosa"], [fake_vec(text), fake_vec("x")], words=4)
    hits = doc.search_collections({"documents": a, "packs": b}, fake_vec("Madrid bandera"), top=3)
    assert [h["collection"] for h in hits[:1]] == ["packs"] and len(hits) == 3
    assert doc.cite(hits[0], with_collection=True) == "packs/b.txt, part 1 of 2"
    assert doc.cite(hits[0]) == "b.txt, part 1 of 2"
    chunks = {"documents": 10, "big": 500, "small": 5}
    assert doc.pick_embedder_group({"v2": ["documents"], "v1": ["big"]}, "v2", chunks) == "v2"   # what this machine indexes with
    assert doc.pick_embedder_group({"v2": ["small"], "v1": ["big"]}, "none", chunks) == "v1"     # else the most parts


def test_doc_cli_with_collections(tmp_path, monkeypatch, capsys):
    from ai2 import cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(cli, "_ensure_server", lambda hw, model, port, record, **kw: "http://127.0.0.1:8081/")
    monkeypatch.setattr(doc.EmbedClient, "embed_query", lambda self, q: fake_vec(q))
    monkeypatch.setattr(doc, "choose_embedder", lambda ram, catalog=None: {"id": "nomic-embed-text-v2-moe"})
    _store("documents", "nomic-embed-text-v2-moe", {"notas.txt": ["Madrid es la capital."]})
    _store("constitucion", "nomic-embed-text-v2-moe", {"c.pdf": ["La bandera de España.", "Madrid, la capital."]})
    _store("english", "nomic-embed-text-v1.5", {"e.txt": ["Madrid is the capital."]})
    assert cli.main(["doc", "list"]) == 0
    out = capsys.readouterr().out
    assert "  constitucion  (embedder nomic-embed-text-v2-moe" in out and "    notas.txt" in out and "  english  " in out
    # every collection built with this machine's embedder, named in the citations; the other one is said
    assert cli.main(["doc", "search", "--top", "3", "Madrid capital"]) == 0
    out = capsys.readouterr().out
    assert "Not searched, built with another embedding model: english" in out
    assert "constitucion/c.pdf, part" in out and "documents/notas.txt, part 1 of 1" in out and "e.txt" not in out
    # --in picks one collection, whatever its model; citations stay short
    assert cli.main(["doc", "search", "--in", "english", "Madrid"]) == 0
    out = capsys.readouterr().out
    assert "[1] e.txt, part 1 of 1" in out and "Not searched" not in out
    assert cli.main(["doc", "search", "--in", "ghost", "x"]) == 1
    assert "No collection named 'ghost'" in capsys.readouterr().err
    assert cli.main(["doc", "search", "--in", "Bad/Name", "x"]) == 1
    assert "not a collection name" in capsys.readouterr().err
    # forget finds the document's collection, refuses when ambiguous, --all --in removes a collection
    _store("otra", "nomic-embed-text-v2-moe", {"notas.txt": ["Otra copia."]})
    assert cli.main(["doc", "forget", "notas.txt"]) == 1
    assert "more than one collection (documents, otra)" in capsys.readouterr().err
    assert cli.main(["doc", "forget", "notas.txt", "--in", "otra"]) == 0
    assert "Forgot 1 document. (collection otra)" in capsys.readouterr().out
    assert cli.main(["doc", "forget", "c.pdf"]) == 0
    assert cli.main(["doc", "forget", "--all", "--in", "english"]) == 0
    assert "Forgot 1 document and the collection english." in capsys.readouterr().out
    assert "english" not in doc.list_collections() and "otra" in doc.list_collections()
    assert cli.main(["doc", "forget", "--all", "--in", "english"]) == 1


def test_doc_index_into_a_named_collection(tmp_path, monkeypatch, capsys):
    from ai2 import cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(cli, "_ensure_server", lambda hw, model, port, record, **kw: "http://127.0.0.1:8081/")
    monkeypatch.setattr(cli, "find_model_file", lambda f: "/m/" + f)
    monkeypatch.setattr(doc.EmbedClient, "ntokens", lambda self, text: len(text.split()))
    monkeypatch.setattr(doc.EmbedClient, "embed_documents", lambda self, chunks, progress=None: [fake_vec(c) for c in chunks])
    monkeypatch.setattr(doc, "choose_embedder", lambda ram, catalog=None: next(
        m for m in embedding_models() if m["id"] == "nomic-embed-text-v1.5"))
    f = tmp_path / "ley.txt"
    f.write_text("La capital del Estado es la villa de Madrid. " * 30, encoding="utf-8")
    assert cli.main(["doc", "index", "--in", "leyes", str(f)]) == 0
    assert "--in leyes" in capsys.readouterr().out
    assert doc.list_collections() == ["leyes"]
    conn = doc.open_store(doc.index_path("leyes"))
    assert doc.store_model(conn) == "nomic-embed-text-v1.5" and doc.list_documents(conn)[0]["name"] == "ley.txt"


def test_doc_search_with_no_question_asks_and_keeps_asking(tmp_path, monkeypatch, capsys):
    """What the Search Knowledge menu entry runs. The first screen has to say
    that this is not AI-2 Chat, because that difference is the point."""
    from ai2 import cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(cli, "_ensure_server", lambda hw, model, port, record, **kw: "http://127.0.0.1:8081/")
    monkeypatch.setattr(doc.EmbedClient, "embed_query", lambda self, q: fake_vec(q))
    monkeypatch.setattr(doc, "choose_embedder", lambda ram, catalog=None: {"id": "nomic-embed-text-v2-moe"})
    _store("documents", "nomic-embed-text-v2-moe", {"notas.txt": ["La capital del Estado es Madrid."]})
    asked = iter(["madrid", "", "never reached"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(asked))
    assert cli.main(["doc", "search"]) == 0
    out = capsys.readouterr().out
    assert "It is not AI-2 Chat" in out and "nothing can be made up" in out
    # a collection of one's own is named as that, not as a knowledge pack
    assert "Also searching your own documents:  documents" in out
    assert "[1] notas.txt, part 1 of 1" in out
    assert "La capital del Estado es Madrid." in out
    assert out.rstrip().endswith("Done.")


def test_the_search_loop_says_when_there_is_nothing_to_search(tmp_path, monkeypatch, capsys):
    """The case of an older AI-2 brought up to date: the packs are not added
    by an update, so the menu entry must not look broken."""
    from ai2 import cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert cli.main(["doc", "search"]) == 1
    out = capsys.readouterr().out
    assert "nothing to search on this computer yet" in out
    assert "ai-2 knowledge browse" in out and "ai-2 doc index FILE" in out


def test_the_search_loop_warns_when_collections_use_different_embedders(tmp_path, monkeypatch, capsys):
    from ai2 import cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(cli, "_ensure_server", lambda hw, model, port, record, **kw: "http://127.0.0.1:8081/")
    monkeypatch.setattr(doc.EmbedClient, "embed_query", lambda self, q: fake_vec(q))
    monkeypatch.setattr(doc, "choose_embedder", lambda ram, catalog=None: {"id": "nomic-embed-text-v2-moe"})
    _store("packs", "nomic-embed-text-v1.5", {"english.txt": ["Madrid is the capital."]})
    _store("mine", "nomic-embed-text-v2-moe", {"notas.txt": ["La capital es Madrid."]})
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    assert cli.main(["doc", "search"]) == 0
    out = capsys.readouterr().out
    assert "cannot search them together" in out and "--in NAME" in out
    assert out.rstrip().endswith("Nothing asked.")


def test_the_search_loop_survives_ctrl_c(tmp_path, monkeypatch, capsys):
    from ai2 import cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    _store("documents", "nomic-embed-text-v2-moe", {"notas.txt": ["Madrid"]})
    def interrupt(prompt=""):
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", interrupt)
    assert cli.main(["doc", "search"]) == 0
    assert "Nothing asked." in capsys.readouterr().out


def test_search_knowledge_holds_the_window_when_there_is_nothing_to_search(tmp_path, monkeypatch, capsys):
    """The menu entry runs this in a terminal that closes when the command
    returns. Every round of the loop waits for input, so the window stays by
    itself; the round that never happens has to hold it, or the message saying
    why flashes past unread (rafaminu-pc, upgraded and packless, 2026-09-17)."""
    from ai2 import about, cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    args = type("A", (), {"question": [], "collection": None, "top": 5, "doc": None, "wait": 1})()

    waited = []
    monkeypatch.setattr(about, "wait_for_enter", lambda: waited.append(True))
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(cli, "_offer_the_packs", lambda docmod, width: False)   # declined, or nothing to offer
    assert cli._doc_search(args, doc) == 1
    out = capsys.readouterr().out
    assert "nothing to search" in out and "ai-2 knowledge browse" in out
    assert waited == [True]

    # not in a terminal (a script, a pipe), nothing to hold open
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    assert cli._doc_search(args, doc) == 1
    assert waited == [True]


def test_the_empty_window_offers_the_packs_instead_of_naming_a_command(tmp_path, monkeypatch, capsys):
    """Rafael, 2026-09-18, on a machine with no packs: "it does not offer a way
    to install a pack. What a terrible UX". Printing a command into a window
    that closes on the next keypress is homework, not an offer."""
    from ai2 import cli, pack
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    entries = [{"id": "ai2-help", "title": "AI-2 Help", "parts": 107, "size_bytes": 345691,
                "license": "MIT", "embedder": "nomic-embed-text-v1.5", "url": "https://x/a.ai2pack",
                "sha256": "0" * 64, "version": "2026-09-16"}]
    monkeypatch.setattr(pack, "load_catalog", lambda: entries)
    monkeypatch.setattr(cli, "find_model_file", lambda f: None)               # the model is not here yet
    installed = []
    monkeypatch.setattr(cli, "_install_cataloged_pack",
                        lambda entry, p, d: installed.append(entry["id"]) or 0)

    monkeypatch.setattr("builtins.input", lambda prompt="": "")               # Enter means yes
    assert cli._offer_the_packs(doc, 76) is True
    out = capsys.readouterr().out
    assert "ai2-help" in out and "337 KB" in out
    assert "85 MB" in out, "the model is the real cost of the first pack and must be said before the prompt"
    assert installed == ["ai2-help"]

    installed.clear()
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert cli._offer_the_packs(doc, 76) is False
    assert installed == [] and "Nothing installed" in capsys.readouterr().out

    # not a terminal: no prompt, and the caller falls back to naming the command
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("must not ask a script"))
    assert cli._offer_the_packs(doc, 76) is False


def test_the_first_screen_names_the_packs_and_says_what_else_is_available(tmp_path, monkeypatch, capsys):
    """Rafael, 2026-09-18: the bare "Searching: a, b, c" became "Searching the
    following Knowledge Packs:" with the same two hints the empty state gives.
    Not every collection is a pack, so a person's own documents are named as
    theirs rather than swept in under the heading."""
    from ai2 import cli, pack
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    conn = doc.open_store(doc.index_path("recipes"))
    doc.set_store_model(conn, "nomic-embed-text-v2-moe", 8)
    doc.add_document(conn, "cake.txt", "/home/me/cake.txt", ["Beat the eggs."], [fake_vec("x")], words=3)
    conn.close()
    monkeypatch.setattr(pack, "manifest_of",
                        lambda name: {"title": "AI-2 Help"} if name == "ai2-help" else None)
    monkeypatch.setattr(doc, "list_collections", lambda: ["ai2-help", "recipes"])
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "")               # finish at once

    args = type("A", (), {"question": [], "collection": None, "top": 3, "doc": None, "wait": 1})()
    cli._doc_search(args, doc)
    out = capsys.readouterr().out
    assert "Searching the following Knowledge Packs:" in out
    assert "ai2-help           AI-2 Help" in out
    assert "Also searching your own documents:  recipes" in out, "a collection of one's own is not a pack"
    assert "ai-2 knowledge browse" in out and "ai-2 doc index FILE" in out, \
        "the same two hints the empty state gives"
    assert "https://github.com/ProWoos-Devs/ai2-knowledge" in out, "and where packs are got and shared"


def test_a_number_reads_more_of_that_result(tmp_path, monkeypatch, capsys):
    """Rafael, 2026-09-18, looking at three results of which only the second
    was the one he wanted: "What if I want to expand just #2". A number opens
    that result's document; the same number again opens it wider."""
    from ai2 import cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    conn = doc.open_store(doc.index_path("manual"))
    doc.set_store_model(conn, "nomic-embed-text-v2-moe", 8)
    long_parts = [f"Part {i} of the long manual says thing number {i}." for i in range(30)]
    doc.add_document(conn, "long.txt", "/x/long.txt", long_parts, [fake_vec("x")] * 30, words=300)
    doc.add_document(conn, "short.txt", "/x/short.txt", ["Only one thing here.", "And a second."],
                     [fake_vec("x")] * 2, words=8)
    conn.close()
    hits = [{"collection": "manual", "doc": "long.txt", "ord": 15, "of": 30, "text": long_parts[15],
             "cite": "long.txt, part 16 of 30", "url": None, "manifest": None},
            {"collection": "manual", "doc": "short.txt", "ord": 0, "of": 2, "text": "Only one thing here.",
             "cite": "short.txt, part 1 of 2", "url": None, "manifest": None}]
    monkeypatch.setattr(cli, "_doc_hits", lambda args, docmod, hw, q, distinct=False: hits)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    answers = iter(["anything", "2", "1", "1", "7", ""])
    asked = []

    def fake_input(prompt=""):
        a = next(answers)
        asked.append(a)
        return a

    monkeypatch.setattr("builtins.input", fake_input)
    args = type("A", (), {"question": [], "collection": None, "top": 3, "doc": None, "wait": 1})()
    assert cli._doc_search(args, doc) == 0
    out = capsys.readouterr().out
    assert "Type a number to read more of that one" in out
    # 2: a short document comes back whole, and nothing more is offered for it
    assert "Only one thing here. And a second." in out
    # 1: a window onto the long one, centred on the part that matched ...
    assert "long.txt, parts 14 to 18 of 30" in out and "Type 1 again for more of it" in out
    # ... and the same number again opens it wider
    assert "long.txt, parts 12 to 20 of 30" in out
    # 7 is not one of the results, so it is a question like any other
    assert asked == ["anything", "2", "1", "1", "7", ""]


def test_paragraphs_survive_indexing_and_the_embedder_sees_what_it_always_saw():
    """Until 0.18.6 a part was its words joined by spaces, so a document read
    back as one unbroken block (Rafael, 2026-09-18: "it looks like everything
    is 1 line"). The breaks now live in the stored text, and ONLY there: what
    is embedded is flat(text), which is exactly the old text, so a rebuilt pack
    has the same vectors and every measured score still stands."""
    title = "Finding a file"
    para1 = " ".join(f"alpha{i}" for i in range(60)) + "."
    para2 = " ".join(f"beta{i}" for i in range(80)) + "."
    text = f"{title}\n\n{para1}\n\n{para2}\n"
    new, _, n_words = doc.make_chunks([text], False, lambda c: 0, limit=512)
    old = doc.chunk_words(text)                       # the pre-0.18.6 chunker, still there
    assert [doc.flat(t) for t in new] == old, "the embedder must see byte-for-byte what it saw before"
    assert n_words == len(text.split())
    assert doc.paragraphs(new[0])[0] == title and "\n\n" in new[0]

    # parts overlap by twenty words; stitched back, the paragraphs come out whole and once
    assert doc.join_paragraphs(new) == [title, para1, para2]
    wrapped = doc.join_parts(new, width=50)
    assert wrapped.count("\n\n") == 2 and max(len(l) for l in wrapped.split("\n")) <= 50

    # an index made before this has no breaks in it, and reads as it always did
    assert doc.join_paragraphs(old) == [" ".join(text.split())]


def test_a_page_break_is_not_a_paragraph_break():
    """A sentence runs across pages; a new page starts a paragraph only when
    the text before it had closed its sentence."""
    running = ["The sentence starts here and", "continues on the next page. Then more."]
    texts, _, _ = doc.make_chunks(running, True, lambda c: 0, limit=512)
    assert doc.paragraphs(texts[0]) == ["The sentence starts here and continues on the next page. Then more."]
    closed = ["A chapter ends here.", "A new one begins."]
    texts, _, _ = doc.make_chunks(closed, True, lambda c: 0, limit=512)
    assert doc.paragraphs(texts[0]) == ["A chapter ends here.", "A new one begins."]


def _reader_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    text = "How to find <a> file\n\nFirst paragraph here.\n\nThe big files answer is in this one & nowhere else.\n"
    parts, _, _ = doc.make_chunks([text], False, lambda c: 0, limit=512)
    conn = doc.open_store(doc.index_path("manual"))
    doc.set_store_model(conn, "nomic-embed-text-v2-moe", 8)
    doc.add_document(conn, "find.txt", "/x/find.txt", parts, [fake_vec("x")] * len(parts), words=20)
    conn.close()
    return {"collection": "manual", "doc": "find.txt", "ord": 0, "text": "The big files answer is in this one",
            "url": "https://example.org/find?a=1&b=2", "manifest": None}


def test_the_reader_page_has_paragraphs_an_anchor_and_a_source_link(tmp_path, monkeypatch):
    from ai2 import cli
    hit = _reader_fixture(tmp_path, monkeypatch)
    page = cli._doc_reader_page(hit, doc)
    assert page.count("<p>") >= 3, "paragraphs, not one block"
    assert "&lt;a&gt; file" in page and "&amp; nowhere else" in page, "document text is escaped, not interpreted"
    assert '<a name="hit"></a><p>The big files answer' in page, "the anchor sits where the result begins"
    assert 'href="https://example.org/find?a=1&amp;b=2"' in page, "the source can be followed from the reader"


def test_the_reader_is_w3m_when_there_is_one_and_the_terminal_otherwise(tmp_path, monkeypatch):
    """A terminal prints text once, at one width; w3m owns its window and
    re-lays the text out when it is resized (measured, 60 columns to 120). It
    is on the AI-2 image but not on a machine brought up to date, so its
    absence must change nothing."""
    from ai2 import cli
    hit = _reader_fixture(tmp_path, monkeypatch)
    ran = []

    def run(cmd):
        assert os.path.exists(cmd[-1].removeprefix("file://").removesuffix("#hit")), "the page exists while w3m runs"
        ran.append(cmd)

    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: True, raising=False)
    assert cli._doc_open_reader(hit, doc, which=lambda name: None, run=run) is False and ran == []
    assert cli._doc_open_reader(hit, doc, which=lambda name: "/usr/bin/w3m", run=run) is True
    assert ran[0][0] == "w3m" and ran[0][-1].endswith("/document.html#hit")
    assert not os.path.exists(ran[0][-1].removeprefix("file://").removesuffix("#hit")), "and is gone afterwards"
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: False, raising=False)
    assert cli._doc_open_reader(hit, doc, which=lambda name: "/usr/bin/w3m", run=run) is False, "never for a pipe"


def test_search_shows_one_result_per_document_and_ask_keeps_every_part(tmp_path, monkeypatch):
    """"Is Linux safe", Rafael, 2026-09-18: two parts of the same FAQ took two
    of the three slots. For a person reading, three slots should be three
    documents; the rest of any of them is one keypress away. The chat model is
    different: it may need two parts of one document to answer."""
    from ai2 import cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    conn = doc.open_store(doc.index_path("documents"))
    doc.set_store_model(conn, "nomic-embed-text-v2-moe", 8)
    doc.add_document(conn, "faq.txt", "/x/faq.txt", ["madrid one", "madrid two", "madrid three"],
                     [fake_vec("madrid")] * 3, words=6)
    doc.add_document(conn, "other.txt", "/x/other.txt", ["castellano here"], [fake_vec("castellano madrid")], words=2)
    conn.close()
    monkeypatch.setattr(cli, "_ensure_server", lambda *a, **k: "http://x")
    monkeypatch.setattr(cli, "_catalog_entry", lambda model_id: {"id": model_id})
    monkeypatch.setattr(doc.EmbedClient, "embed_query", lambda self, q: fake_vec("madrid"))
    hw = type("HW", (), {"ram_mib": 8000})()
    args = type("A", (), {"collection": None, "top": 3, "doc": None, "wait": 1})()
    every = cli._doc_hits(args, doc, hw, "madrid?")
    assert [h["doc"] for h in every] == ["faq.txt"] * 3
    distinct = cli._doc_hits(args, doc, hw, "madrid?", distinct=True)
    assert [h["doc"] for h in distinct] == ["faq.txt", "other.txt"]
