"""`ai-2 doc`: chunking, the SQLite store, retrieval and the routing gate, with
no server (vectors come from a fake embedder)."""
import os
import sqlite3

import pytest

from ai2 import doc, serverstate, knowledgecli, runner, runtime
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
    assert knowledgecli._doc_embedder(doc, hw, None, None, "mypack")["id"] == "nomic-embed-text-v2-moe"
    assert knowledgecli._doc_embedder(doc, hw, "nomic-embed-text-v1.5", None, "mypack")["id"] == "nomic-embed-text-v1.5"

    # a collection keeps the model it was built with, and says where to go instead
    assert knowledgecli._doc_embedder(doc, hw, "nomic-embed-text-v1.5", "nomic-embed-text-v2-moe", "mypack") is None
    err = capsys.readouterr().err
    assert "cannot change" in err and "--in NEWNAME --embedder nomic-embed-text-v1.5" in err

    # an unknown name lists the real ones, and a model too big for the machine is refused
    assert knowledgecli._doc_embedder(doc, hw, "no-such-model", None, "mypack") is None
    assert "nomic-embed-text-v1.5" in capsys.readouterr().err
    assert knowledgecli._doc_embedder(doc, type("HW", (), {"ram_mib": 2000})(), "nomic-embed-text-v2-moe",
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
    assert doc.choose_answer_model([by_id["smollm3-3b"]], 2000, score) is None    # nothing starts above what the machine can hold
    assert doc.choose_answer_model([by_id["gemma3-270m"], by_id["qwen2.5-7b"]], 1800, score)["id"] == "gemma3-270m"   # the smallest, tight
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
    monkeypatch.setattr(runner, "_ensure_server", lambda hw, model, port, record, **kw: started.append((model["id"], record)) or "http://127.0.0.1:8081/")
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
    conn = doc.open_store(doc.index_path(name))   # the home copy: only writable place
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
    monkeypatch.setattr(runner, "_ensure_server", lambda hw, model, port, record, **kw: "http://127.0.0.1:8081/")
    monkeypatch.setattr(doc.EmbedClient, "embed_query", lambda self, q: fake_vec(q))
    monkeypatch.setattr(doc, "choose_embedder", lambda ram, catalog=None: {"id": "nomic-embed-text-v2-moe"})
    _store("documents", "nomic-embed-text-v2-moe", {"notas.txt": ["Madrid es la capital."]})
    _store("constitucion", "nomic-embed-text-v2-moe", {"c.pdf": ["La bandera de España.", "Madrid, la capital."]})
    _store("english", "nomic-embed-text-v1.5", {"e.txt": ["Madrid is the capital."]})
    assert cli.main(["doc", "list"]) == 0
    out = capsys.readouterr().out
    assert "  constitucion  (embedder nomic-embed-text-v2-moe" in out and "    notas.txt" in out and "  english  " in out
    # every collection is searched, even when the machine's default embedder is the other one
    assert cli.main(["doc", "search", "--top", "3", "Madrid capital"]) == 0
    out = capsys.readouterr().out
    assert "Not searched" not in out
    assert "constitucion/c.pdf, part" in out and "documents/notas.txt, part 1 of 1" in out
    assert "e.txt" in out
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
    monkeypatch.setattr(runner, "_ensure_server", lambda hw, model, port, record, **kw: "http://127.0.0.1:8081/")
    monkeypatch.setattr(runtime, "find_model_file", lambda f: "/m/" + f)
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
    monkeypatch.setattr(runner, "_ensure_server", lambda hw, model, port, record, **kw: "http://127.0.0.1:8081/")
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


def test_the_search_loop_lists_every_collection_when_embedders_differ(tmp_path, monkeypatch, capsys):
    from ai2 import cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(runner, "_ensure_server", lambda hw, model, port, record, **kw: "http://127.0.0.1:8081/")
    monkeypatch.setattr(doc.EmbedClient, "embed_query", lambda self, q: fake_vec(q))
    monkeypatch.setattr(doc, "choose_embedder", lambda ram, catalog=None: {"id": "nomic-embed-text-v2-moe"})
    _store("packs", "nomic-embed-text-v1.5", {"english.txt": ["Madrid is the capital."]})
    _store("mine", "nomic-embed-text-v2-moe", {"notas.txt": ["La capital es Madrid."]})
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    assert cli.main(["doc", "search"]) == 0
    out = capsys.readouterr().out
    assert "cannot search them together" not in out
    assert "Also searching your own documents:" in out and "packs" in out and "mine" in out
    assert out.rstrip().endswith("Nothing asked.")


def test_search_keeps_knowledge_packs_when_own_documents_use_another_embedder(tmp_path, monkeypatch, capsys):
    """The headline bug: after `ai-2 doc index FILE` on 4 GB, Search Knowledge
    used to drop the shipped v1.5 packs because choose_embedder picks v2-moe."""
    import yaml
    from ai2 import cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(runner, "_ensure_server", lambda hw, model, port, record, **kw: "http://127.0.0.1:8081/")
    monkeypatch.setattr(doc.EmbedClient, "embed_query", lambda self, q: fake_vec(q))
    monkeypatch.setattr(doc, "choose_embedder", lambda ram, catalog=None: {"id": "nomic-embed-text-v2-moe"})
    _store("ai2-help", "nomic-embed-text-v1.5",
           {"find-a-file.txt": ["Madrid, how to find a big file."]})
    with open(os.path.join(doc.doc_root(), "ai2-help", "manifest.yml"), "w", encoding="utf-8") as fh:
        yaml.safe_dump({"id": "ai2-help", "title": "AI-2 Help", "languages": ["en"],
                        "license": "MIT"}, fh)
    _store("documents", "nomic-embed-text-v2-moe", {"notas.txt": ["Madrid es la capital."]})
    assert cli.main(["doc", "search", "--top", "3", "Madrid"]) == 0
    out = capsys.readouterr().out
    assert "Not searched" not in out
    assert "find-a-file.txt" in out
    assert "ai2-help" in out or "AI-2 Help" in out or "find-a-file.txt" in out


def test_own_documents_are_not_crowded_out_by_the_packs(tmp_path, monkeypatch, capsys):
    """Two embedding models give scores that do not compare, so the groups
    take turns: three pack hits must not push the person's own file out."""
    import yaml
    from ai2 import cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(runner, "_ensure_server", lambda hw, model, port, record, **kw: "http://127.0.0.1:8081/")
    monkeypatch.setattr(doc.EmbedClient, "embed_query", lambda self, q: fake_vec(q))
    _store("ai2-help", "nomic-embed-text-v1.5",
           {"a.txt": ["Wifi setup."], "b.txt": ["Printer setup."], "c.txt": ["Sound setup."]})
    with open(os.path.join(doc.doc_root(), "ai2-help", "manifest.yml"), "w", encoding="utf-8") as fh:
        yaml.safe_dump({"id": "ai2-help", "title": "AI-2 Help", "languages": ["en"], "license": "MIT"}, fh)
    _store("documents", "nomic-embed-text-v2-moe", {"notas.txt": ["Madrid es la capital."]})
    assert cli.main(["doc", "search", "--top", "3", "Madrid es la capital."]) == 0
    out = capsys.readouterr().out
    assert out.index("[1] ") < out.index("a.txt") < out.index("notas.txt") < out.index("[3] ")


def test_a_busy_embedding_server_is_not_stopped_for_a_search(monkeypatch):
    """Searching while `ai-2 doc index` runs with the other model must not
    kill the indexing."""
    from ai2 import cli, serverstate
    monkeypatch.setattr(serverstate, "read_server", lambda name: {"pid": 1, "model": "nomic-embed-text-v2-moe"})
    monkeypatch.setattr(knowledgecli, "_server_busy", lambda url: True)
    stopped = []
    monkeypatch.setattr(serverstate, "stop_server", lambda **kw: stopped.append(kw))
    monkeypatch.setattr(runner, "_ensure_server", lambda *a, **kw: "http://127.0.0.1:8081/")
    assert knowledgecli._ensure_embed(None, {"id": "nomic-embed-text-v1.5"}, wait=1) is None
    assert stopped == []
    monkeypatch.setattr(knowledgecli, "_server_busy", lambda url: False)
    assert knowledgecli._ensure_embed(None, {"id": "nomic-embed-text-v1.5"}, wait=1) == "http://127.0.0.1:8081/"
    assert stopped == [{"name": serverstate.EMBED}]


def test_a_running_server_with_another_model_is_not_reused(monkeypatch, capsys):
    """An index embedded with the wrong model is wrong without any error, so a
    server that answers on the port must also run the model asked for."""
    from ai2 import cli, serverstate
    monkeypatch.setattr(runner, "_server_ready", lambda url, timeout=2.0: True)
    monkeypatch.setattr(serverstate, "read_server", lambda name: {"pid": 1, "model": "nomic-embed-text-v1.5"})
    model = {"id": "nomic-embed-text-v2-moe", "file": "x.gguf", "label": "x"}
    assert runner._ensure_server(None, model, 8081, serverstate.EMBED, wait=1) is None
    assert "already running with nomic-embed-text-v1.5" in capsys.readouterr().err
    monkeypatch.setattr(serverstate, "read_server", lambda name: {"pid": 1, "model": "nomic-embed-text-v2-moe"})
    monkeypatch.setattr(runner, "endpoint_problem", lambda url, port, expected_file=None: None)
    assert runner._ensure_server(None, model, 8081, serverstate.EMBED, wait=1) == "http://127.0.0.1:8081/"


def test_doc_search_with_a_question_on_a_terminal_keeps_asking(tmp_path, monkeypatch, capsys):
    """A question typed at a terminal is the first round of Search Knowledge,
    not a one-shot that cannot open the document."""
    import sys
    from ai2 import cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(runner, "_ensure_server", lambda hw, model, port, record, **kw: "http://127.0.0.1:8081/")
    monkeypatch.setattr(doc.EmbedClient, "embed_query", lambda self, q: fake_vec(q))
    _store("documents", "nomic-embed-text-v2-moe", {"notas.txt": ["La capital del Estado es Madrid."]})
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    assert cli.main(["doc", "search", "madrid"]) == 0
    out = capsys.readouterr().out
    assert "It is not AI-2 Chat" in out
    assert "[1] notas.txt, part 1 of 1" in out
    assert out.rstrip().endswith("Done.")


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
    monkeypatch.setattr(knowledgecli, "_offer_the_packs", lambda docmod, width: False)   # declined, or nothing to offer
    assert knowledgecli._doc_search(args, doc) == 1
    out = capsys.readouterr().out
    assert "nothing to search" in out and "ai-2 knowledge browse" in out
    assert waited == [True]

    # not in a terminal (a script, a pipe), nothing to hold open
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    assert knowledgecli._doc_search(args, doc) == 1
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
    monkeypatch.setattr(runtime, "find_model_file", lambda f: None)               # the model is not here yet
    installed = []
    monkeypatch.setattr(knowledgecli, "_install_cataloged_pack",
                        lambda entry, p, d: installed.append(entry["id"]) or 0)

    monkeypatch.setattr("builtins.input", lambda prompt="": "")               # Enter means yes
    assert knowledgecli._offer_the_packs(doc, 76) is True
    out = capsys.readouterr().out
    assert "ai2-help" in out and "337 KB" in out
    assert "85 MB" in out, "the model is the real cost of the first pack and must be said before the prompt"
    assert installed == ["ai2-help"]

    installed.clear()
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert knowledgecli._offer_the_packs(doc, 76) is False
    assert installed == [] and "Nothing installed" in capsys.readouterr().out

    # not a terminal: no prompt, and the caller falls back to naming the command
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("must not ask a script"))
    assert knowledgecli._offer_the_packs(doc, 76) is False


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
    knowledgecli._doc_search(args, doc)
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
    monkeypatch.setattr(knowledgecli, "_doc_hits", lambda args, docmod, hw, q, distinct=False: hits)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    answers = iter(["anything", "2", "1", "1", "7", ""])
    asked = []

    def fake_input(prompt=""):
        a = next(answers)
        asked.append(a)
        return a

    monkeypatch.setattr("builtins.input", fake_input)
    args = type("A", (), {"question": [], "collection": None, "top": 3, "doc": None, "wait": 1})()
    assert knowledgecli._doc_search(args, doc) == 0
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
    page = knowledgecli._doc_reader_page(hit, doc)
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
    assert knowledgecli._doc_open_reader(hit, doc, which=lambda name: None, run=run) is False and ran == []
    assert knowledgecli._doc_open_reader(hit, doc, which=lambda name: "/usr/bin/w3m", run=run) is True
    assert ran[0][0] == "w3m" and ran[0][-1].endswith("/document.html#hit")
    assert not os.path.exists(ran[0][-1].removeprefix("file://").removesuffix("#hit")), "and is gone afterwards"
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: False, raising=False)
    assert knowledgecli._doc_open_reader(hit, doc, which=lambda name: "/usr/bin/w3m", run=run) is False, "never for a pipe"


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
    monkeypatch.setattr(runner, "_ensure_server", lambda *a, **k: "http://x")
    monkeypatch.setattr(runner, "_catalog_entry", lambda model_id: {"id": model_id})
    monkeypatch.setattr(doc.EmbedClient, "embed_query", lambda self, q: fake_vec("madrid"))
    hw = type("HW", (), {"ram_mib": 8000})()
    args = type("A", (), {"collection": None, "top": 3, "doc": None, "wait": 1})()
    every = knowledgecli._doc_hits(args, doc, hw, "madrid?")
    assert [h["doc"] for h in every] == ["faq.txt"] * 3
    distinct = knowledgecli._doc_hits(args, doc, hw, "madrid?", distinct=True)
    assert [h["doc"] for h in distinct] == ["faq.txt", "other.txt"]


def _system_pack(tmp_path, monkeypatch, name="ai2-help", text="A system pack answer.", revision=1):
    """A pack in the read-only system location, as the ai2-help package
    installs it: index, manifest, and the record of where it came from."""
    import yaml
    import shutil
    root = tmp_path / "system-doc"
    (root / name).mkdir(parents=True, exist_ok=True)
    # built elsewhere and moved in, the way the package does it: the system
    # location is read-only even to us
    staging = tmp_path / "staging.sqlite"
    conn = doc.open_store(str(staging))
    doc.set_store_model(conn, "nomic-embed-text-v1.5", 8)
    doc.add_document(conn, "help.txt", "/help.txt", [text], [fake_vec(text)], len(text.split()))
    conn.close()
    shutil.move(str(staging), str(root / name / "index.sqlite"))
    monkeypatch.setenv("AI2_SYSTEM_DOC_DIR", str(root))
    # and made read-only, as pacman leaves a package's files for a user
    (root / name / "index.sqlite").chmod(0o444)
    (root / name / "manifest.yml").write_text(yaml.safe_dump(
        {"id": name, "title": "AI-2 Help", "version": "2026-09-18", "revision": revision,
         "license": "MIT", "languages": ["en"],
         "embedder": {"id": "nomic-embed-text-v1.5"}}), encoding="utf-8")
    (root / name / "origin.yml").write_text(yaml.safe_dump(
        {"from": "AI-2 itself", "id": name}), encoding="utf-8")
    return root


def test_a_pack_that_came_with_ai2_is_listed_and_searched(tmp_path, monkeypatch):
    """AI-2's own documentation has to be there when the machine has no
    network, so it comes with AI-2 instead of being installed into a home."""
    from ai2 import pack
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    _system_pack(tmp_path, monkeypatch)
    assert doc.list_collections() == ["ai2-help"]
    assert doc.system_collections() == ["ai2-help"]
    assert doc.is_system("ai2-help")
    assert pack.manifest_of("ai2-help")["title"] == "AI-2 Help"
    hits = doc.search(doc.open_store(doc.read_index_path("ai2-help")), fake_vec("A system pack answer."), top=1)
    assert hits and hits[0]["doc"] == "help.txt"


def test_your_own_copy_shadows_the_one_that_came_with_ai2(tmp_path, monkeypatch):
    """A newer revision installed from the catalog lands in the home and is
    what gets searched; removing it puts the system one back in use."""
    from ai2 import pack
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    _system_pack(tmp_path, monkeypatch)
    _store("ai2-help", "nomic-embed-text-v1.5", {"mine.txt": ["My own newer copy."]})
    assert doc.list_collections() == ["ai2-help"], "named once, not twice"
    assert not doc.is_system("ai2-help")
    assert [d["name"] for d in doc.list_documents(doc.open_store(doc.read_index_path("ai2-help")))] == ["mine.txt"]
    doc.remove_collection("ai2-help")
    assert doc.is_system("ai2-help") and doc.list_collections() == ["ai2-help"]
    assert [d["name"] for d in doc.list_documents(doc.open_store(doc.read_index_path("ai2-help")))] == ["help.txt"]
    assert pack.origin_of("ai2-help")["from"] == "AI-2 itself"


def test_a_read_only_system_pack_is_still_searchable(tmp_path, monkeypatch):
    """The real one is root-owned and 444. SQLite would try to write a
    journal on any open that is not explicitly read-only, so this is what
    breaks first if open_store ever stops noticing where the file is."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    root = _system_pack(tmp_path, monkeypatch)
    (root / "ai2-help").chmod(0o555)
    try:
        conn = doc.open_store(doc.read_index_path("ai2-help"))
        assert [d["name"] for d in doc.list_documents(conn)] == ["help.txt"]
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE nope (x)")      # read-only, and it stays that way
        conn.close()
    finally:
        (root / "ai2-help").chmod(0o755)


def test_nothing_writes_into_the_system_location(tmp_path, monkeypatch):
    """A package owns those files. Indexing and forgetting take the home
    path, so a write against a system pack makes a copy of the person's own
    rather than touching what the package installed."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    root = _system_pack(tmp_path, monkeypatch)
    before = (root / "ai2-help" / "index.sqlite").read_bytes()
    assert doc.index_path("ai2-help").startswith(doc.doc_root())
    assert doc.index_path("ai2-help") != doc.read_index_path("ai2-help")
    conn = doc.open_store(doc.index_path("ai2-help"))
    doc.set_store_model(conn, "nomic-embed-text-v1.5", 8)
    doc.add_document(conn, "mine.txt", "/mine.txt", ["mine"], [fake_vec("mine")], 1)
    conn.close()
    assert (root / "ai2-help" / "index.sqlite").read_bytes() == before, "the package's file was written to"


# ----------------------------------------------- `ai-2 doc ask`, the command
# Excerpts of a person's documents leave the computer only when asked: --remote
# or a remote they made the default. These run the command through cli.main, so
# a broken import or a routing change fails here and not on someone's machine.

REMOTE_URL = "http://10.0.0.5:8080/"


@pytest.fixture
def ask(tmp_path, monkeypatch):
    """Run `ai-2 doc ask` with one indexed document, recording every request."""
    from ai2 import chatterm, cli, models, sysinfo
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    by_id = {m["id"]: m for m in models.load_catalog()}
    world = {"remote": None, "model": by_id["qwen2.5-0.5b"], "prefill": 5.0, "sent": [], "chat_servers": [], "ram": 8000, "reply": ["An answer."]}

    def fake_ensure(hw, model, port, record, **kw):
        if record == serverstate.EMBED:
            return "http://127.0.0.1:8081/"
        world["chat_servers"].append(model["id"])
        return "http://127.0.0.1:8080/"

    def fake_stream(base, messages, **kw):
        world["sent"].append({"base": base, "text": " ".join(m["content"] for m in messages)})
        yield from world["reply"]

    monkeypatch.setattr(knowledgecli, "detect", lambda: type("HW", (), {"ram_mib": world["ram"], "cpu_variant": "avx2"})())
    monkeypatch.setattr(knowledgecli.remote, "load", lambda: world["remote"])
    monkeypatch.setattr(knowledgecli, "load_score", lambda: None)
    monkeypatch.setattr(knowledgecli, "installed_models",
                        lambda cat: [{"id": world["model"]["id"], "catalog": world["model"]}] if world["model"] else [])
    monkeypatch.setattr(runner, "_ensure_server", fake_ensure)
    monkeypatch.setattr(doc.EmbedClient, "embed_query", lambda self, q: fake_vec(q))
    monkeypatch.setattr(doc, "prefill_seconds", lambda n, score, model: world["prefill"])
    monkeypatch.setattr(chatterm, "stream_reply", fake_stream)
    monkeypatch.setattr(sysinfo, "mem_available_mib", lambda: 8000)
    conn = doc.open_store()
    doc.set_store_model(conn, "nomic-embed-text-v2-moe", 8)
    doc.add_document(conn, "c.txt", "/c.txt", ["La capital del Estado es la villa de Madrid."], [fake_vec("Madrid")], words=9)
    conn.close()
    world["run"] = lambda *flags: cli.main(["doc", "ask", *flags, "Madrid capital"])
    world["by_id"] = by_id
    return world


def _nondefault():
    return {"url": REMOTE_URL, "default": False}


def _went_remote(world):
    return any(s["base"] == REMOTE_URL for s in world["sent"])


def test_doc_ask_answers_locally_with_no_remote(ask, capsys):
    assert ask["run"]() == 0
    out = capsys.readouterr().out
    assert "An answer." in out and "Sources: [1] c.txt" in out
    assert ask["chat_servers"] == ["qwen2.5-0.5b"] and not _went_remote(ask)
    assert "villa de Madrid" in ask["sent"][0]["text"]          # the excerpt reached the local AI


def test_doc_ask_stays_local_when_slow_or_starter_and_remote_is_not_the_default(ask, capsys):
    ask["remote"] = _nondefault()
    for model, prefill in (("qwen2.5-0.5b", 999.0), ("gemma3-270m", 5.0)):
        ask["model"], ask["prefill"] = ask["by_id"][model], prefill
        assert ask["run"]() == 0
        out = capsys.readouterr().out
        assert not _went_remote(ask)
        assert "add --remote" in out and "leave this computer" in out      # named, not taken
    assert ask["chat_servers"] == ["qwen2.5-0.5b", "gemma3-270m"]


def test_doc_ask_with_no_local_model_refuses_instead_of_sending(ask, capsys):
    ask["remote"], ask["model"] = _nondefault(), None
    assert ask["run"]() == 1
    err = capsys.readouterr().err
    assert "no chat model" in err and "--remote" in err
    assert ask["sent"] == []


def test_doc_ask_sends_only_when_asked(ask, capsys):
    ask["remote"] = _nondefault()
    assert ask["run"]("--remote") == 0                          # asked this time
    assert _went_remote(ask) and "villa de Madrid" in ask["sent"][-1]["text"]
    assert "leave this computer" in capsys.readouterr().out     # and it says so first
    ask["sent"].clear()
    ask["remote"] = {"url": REMOTE_URL, "default": True}
    assert ask["run"]() == 0                                    # their saved default
    assert _went_remote(ask) and "leave this computer" in capsys.readouterr().out
    ask["sent"].clear()
    assert ask["run"]("--local") == 0                           # --local beats the default
    assert ask["sent"] and not _went_remote(ask)


def test_doc_ask_refuses_local_and_remote_together(ask, capsys):
    ask["remote"] = _nondefault()
    with pytest.raises(SystemExit):
        ask["run"]("--local", "--remote")
    assert ask["sent"] == []


def test_doc_ask_remote_with_none_configured_is_an_error(ask, capsys):
    assert ask["run"]("--remote") == 1
    assert "no remote AI configured" in capsys.readouterr().err and ask["sent"] == []


def test_doc_ask_no_model_and_no_remote_says_how_to_get_either(ask, capsys):
    ask["model"] = None
    assert ask["run"]() == 1
    assert "ai-2 remote set" in capsys.readouterr().err


def test_doc_ask_unknown_or_undownloaded_model_is_an_error(ask, capsys, monkeypatch):
    assert ask["run"]("--model", "no-such-model") == 1
    assert "not a chat model" in capsys.readouterr().err
    monkeypatch.setattr(runtime, "find_model_file", lambda f: None)
    assert ask["run"]("--model", "qwen2.5-0.5b") == 1
    assert "not downloaded" in capsys.readouterr().err
    assert ask["sent"] == []


def test_doc_ask_with_nothing_indexed_says_so(ask, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "empty"))
    assert ask["run"]() == 1
    assert "No documents indexed yet" in capsys.readouterr().err and ask["sent"] == []


def test_doc_ask_will_not_start_a_model_too_big_for_this_ram(ask, capsys):
    ask["model"], ask["ram"] = ask["by_id"]["qwen2.5-7b"], 2048
    assert ask["run"]() == 1
    err = capsys.readouterr().err
    assert "need more memory than its 2048 MiB" in err and "ai-2 model pull gemma3-270m" in err
    assert ask["chat_servers"] == [] and ask["sent"] == []


def test_doc_ask_too_big_with_a_remote_names_it_and_sends_nothing(ask, capsys):
    ask["model"], ask["ram"], ask["remote"] = ask["by_id"]["qwen2.5-7b"], 2048, _nondefault()
    assert ask["run"]() == 1
    assert "--remote" in capsys.readouterr().err and ask["sent"] == []


@pytest.mark.parametrize("flags", [(), ("--stream",)])
@pytest.mark.parametrize("reply", [[], ["", "  ", "\n"]])
def test_doc_ask_with_an_empty_reply_says_so_and_shows_the_passages(ask, capsys, flags, reply):
    """Gemma 270M ends its reply at once on this prompt. An empty answer with exit
    0 read as if the command had worked, on the machines that pick that model."""
    ask["reply"], ask["model"] = reply, ask["by_id"]["gemma3-270m"]
    assert ask["run"](*flags) == 0
    out = capsys.readouterr().out
    assert "Gemma 3 270M Instruct gave no answer" in out
    assert "villa de Madrid" in out and "c.txt" in out        # the document's own words, with where they come from


def test_doc_ask_empty_reply_from_a_remote_names_the_remote(ask, capsys):
    ask["remote"], ask["reply"] = _nondefault(), []
    assert ask["run"]("--remote") == 0
    out = capsys.readouterr().out
    assert "The remote AI gave no answer" in out and "villa de Madrid" in out


def test_doc_ask_with_an_answer_does_not_add_passages(ask, capsys):
    assert ask["run"]() == 0
    out = capsys.readouterr().out
    assert "gave no answer" not in out and "An answer." in out


def _parts(tmp_path, chunks):
    conn = doc.open_store(tmp_path / "s.sqlite")
    doc.add_document(conn, "d.txt", "/d.txt", chunks, [fake_vec(c) for c in chunks], words=50)
    return conn


def test_a_result_is_finished_from_the_next_part_without_repeating_the_overlap(tmp_path):
    conn = _parts(tmp_path, ["Call for help. Do not try", "help. Do not try to move them. Then wait."])
    hit = {"text": "Call for help. Do not try", "doc": "d.txt", "ord": 0}
    assert doc.finish_sentence(conn, hit) == "Call for help. Do not try to move them."
    assert hit["text"] == "Call for help. Do not try", "the model's excerpt stays as stored"


def test_a_finished_or_last_part_stays_as_stored(tmp_path):
    conn = _parts(tmp_path, ["One. Two.", "Three then four"])
    assert doc.finish_sentence(conn, {"text": "One. Two.", "doc": "d.txt", "ord": 0}) == "One. Two."
    assert doc.finish_sentence(conn, {"text": "Three then four", "doc": "d.txt", "ord": 1}) == "Three then four"


def test_a_heading_or_list_line_with_no_full_stop_ends_at_its_paragraph(tmp_path):
    conn = _parts(tmp_path, ["Text. Keep calm", "Keep calm and warm\n\nNext heading here."])
    assert doc.finish_sentence(conn, {"text": "Text. Keep calm", "doc": "d.txt", "ord": 0}) == "Text. Keep calm and warm"
    conn = _parts(tmp_path, ["Text. A heading", "A heading\n\nNext paragraph here."])
    assert doc.finish_sentence(conn, {"text": "Text. A heading", "doc": "d.txt", "ord": 0}) == "Text. A heading"


def test_a_sentence_that_runs_on_is_left_alone(tmp_path):
    long_part = "word " * (doc.FINISH_WORDS + 5) + "end."
    conn = _parts(tmp_path, ["Start of it", long_part])
    assert doc.finish_sentence(conn, {"text": "Start of it", "doc": "d.txt", "ord": 0}) == "Start of it"


# ------------------------------------------------- a topic's short answer

TOPIC = "Title?\n\nSearch terms: a, b.\n\nSHORT ANSWER\n\nYes, it was. [S1]\n\nTHE FACTS\n\n1. One."


def test_a_short_answer_is_found_whole_when_parts_cut_through_it(tmp_path):
    """Parts are cut by word count, so the heading can end one part and its
    text begin the next. The section is read from the topic joined together."""
    whole = doc.short_answer(_parts(tmp_path / "a", [TOPIC]), "d.txt")
    assert whole == {"heading": "SHORT ANSWER", "text": "Yes, it was. [S1]", "first": 0, "last": 0}
    cut = _parts(tmp_path / "b", ["Title?\n\nSearch terms: a, b.\n\nSHORT", "terms: a, b.\n\nSHORT ANSWER\n\nYes, it",
                                  "ANSWER\n\nYes, it was. [S1]\n\nTHE FACTS", "[S1]\n\nTHE FACTS\n\n1. One."])
    assert doc.short_answer(cut, "d.txt") == {"heading": "SHORT ANSWER", "text": "Yes, it was. [S1]",
                                              "first": 0, "last": 3}
    # the parts before the heading and after the next one are not part of it
    later = _parts(tmp_path / "c", ["Title?\n\nSearch terms: a, b.", "terms: a, b.\n\nSHORT ANSWER\n\nYes, it was. [S1]"
                                    "\n\nTHE FACTS", "THE FACTS\n\n1. One.\n\n2. Two.", "2. Two.\n\n3. Three."])
    found = doc.short_answer(later, "d.txt")
    assert (found["first"], found["last"]) == (1, 1)


def test_a_part_without_overlap_inside_the_short_answer_leaves_it_unknown(tmp_path):
    """A long window is cut in halves that share no words (fit_ranges), and a
    part does not say whether its first word began a paragraph. The next
    heading is then joined to the answer, and the rest of the topic with it."""
    hidden = _parts(tmp_path / "a", ["Title?\n\nSearch terms: a, b.\n\nSHORT ANSWER\n\nYes, it was.",
                                     "THE FACTS\n\n1. One.\n\n2. Two."])
    assert doc.join_paragraphs(["SHORT ANSWER\n\nYes, it was.", "THE FACTS\n\n1. One."])[1] == "Yes, it was. THE FACTS"
    assert doc.short_answer(hidden, "d.txt") is None
    midway = _parts(tmp_path / "b", ["Title?\n\nSHORT ANSWER\n\nYes, it", "was. [S1]\n\nTHE FACTS\n\n1. One."])
    assert doc.short_answer(midway, "d.txt") is None
    # such a seam before the heading or below the next one hides nothing of the answer
    outside = _parts(tmp_path / "c", ["Title?\n\nSearch terms: a,", "b.\n\nSHORT ANSWER\n\nYes, it was. [S1]\n\nTHE FACTS"
                                      "\n\n1. One.", "2. Two.\n\n3. Three."])
    assert doc.short_answer(outside, "d.txt") == {"heading": "SHORT ANSWER", "text": "Yes, it was. [S1]",
                                                  "first": 1, "last": 1}


def test_a_topic_without_the_heading_has_no_short_answer(tmp_path):
    assert doc.short_answer(_parts(tmp_path / "a", ["Title\n\nText here.\n\nMORE\n\nText."]), "d.txt") is None
    assert doc.short_answer(_parts(tmp_path / "b", ["Title\n\nShort answer\n\nYes.\n\nMORE"]), "d.txt") is None
    # text under the sentence, or None would come back for having nothing under it
    inside = _parts(tmp_path / "c", ["Title\n\nThe SHORT ANSWER is no.\n\nIt was never one.\n\nMORE\n\nText."])
    assert doc.short_answer(inside, "d.txt") is None
    assert doc.short_answer(inside, "no-such-topic.txt") is None


def test_a_heading_twice_or_with_nothing_under_it_is_no_short_answer(tmp_path):
    twice = _parts(tmp_path / "a", ["SHORT ANSWER\n\nYes.\n\nSHORT ANSWER\n\nNo."])
    assert doc.short_answer(twice, "d.txt") is None
    empty = _parts(tmp_path / "b", ["Title\n\nSHORT ANSWER\n\nTHE FACTS\n\n1. One."])
    assert doc.short_answer(empty, "d.txt") is None
    assert doc.short_answer(_parts(tmp_path / "c", ["Title\n\nSHORT ANSWER"]), "d.txt") is None


def test_a_short_answer_longer_than_the_guard_is_left_alone(tmp_path):
    def topic(words):
        return "SHORT ANSWER\n\n" + "word " * words + "\n\nTHE FACTS"
    kept = doc.short_answer(_parts(tmp_path / "a", [topic(doc.SHORT_ANSWER_WORDS)]), "d.txt")
    assert len(kept["text"].split()) == doc.SHORT_ANSWER_WORDS == 150
    assert doc.short_answer(_parts(tmp_path / "b", [topic(doc.SHORT_ANSWER_WORDS + 1)]), "d.txt") is None


def test_the_short_answer_ends_at_the_next_heading_or_the_end_of_the_topic(tmp_path):
    to_the_end = _parts(tmp_path / "a", ["Title\n\nSHORT ANSWER\n\nYes.\n\nBut see below."])
    assert doc.short_answer(to_the_end, "d.txt")["text"] == "Yes.\n\nBut see below."
    # a sentence that opens in capitals, or an answer of one word, is not the next heading
    capitals = _parts(tmp_path / "b", ["SHORT ANSWER\n\nUSB is a plug. It is common.\n\nWHAT TO DO\n\nPlug it in."])
    assert doc.short_answer(capitals, "d.txt")["text"] == "USB is a plug. It is common."
    assert doc.short_answer(_parts(tmp_path / "c", ["SHORT ANSWER\n\nNO.\n\nTHE FACTS\n\n1."]), "d.txt")["text"] == "NO."
    assert doc.is_heading("THE FACTS") and doc.is_heading("1. LOS HECHOS")
    assert not doc.is_heading("NO.") and not doc.is_heading("The facts") and not doc.is_heading("1.")
    assert not doc.is_heading(" ".join(["WORD"] * (doc.HEADING_WORDS + 1)))
    # a paragraph without letters is in no capitals
    assert not doc.is_heading("1898") and not doc.is_heading("* * *")
    year = _parts(tmp_path / "d", ["SHORT ANSWER\n\nIt ended in\n\n1898\n\nTHE FACTS\n\n1. One."])
    assert doc.short_answer(year, "d.txt")["text"] == "It ended in\n\n1898"
    # German capitals may keep the ß, which has no capital of one letter in upper()
    assert doc.is_heading("DIE GRÖßE") and doc.is_heading("DIE GRÖSSE") and not doc.is_heading("Die Größe")
    eszett = _parts(tmp_path / "e", ["KURZE ANTWORT\n\nJa.\n\nDIE GRÖßE\n\nEins zwei drei."])
    assert doc.short_answer(eszett, "d.txt")["text"] == "Ja."


def test_the_heading_is_known_in_english_spanish_and_german(tmp_path):
    assert doc.SHORT_ANSWER_HEADINGS == {"en": "SHORT ANSWER", "es": "RESPUESTA CORTA", "de": "KURZE ANTWORT"}
    spanish = doc.short_answer(_parts(tmp_path / "es", ["Título\n\nRESPUESTA CORTA\n\nSí.\n\nLOS HECHOS\n\n1. Uno."]), "d.txt")
    assert (spanish["heading"], spanish["text"]) == ("RESPUESTA CORTA", "Sí.")
    german = doc.short_answer(_parts(tmp_path / "de", ["Titel\n\nKURZE ANTWORT\n\nJa.\n\nDIE FAKTEN"]), "d.txt")
    assert (german["heading"], german["text"]) == ("KURZE ANTWORT", "Ja.")


def test_join_paragraphs_is_unchanged():
    """short_answer() needs to know where each part lies in the joined text,
    so the joining moved into _joined(). What join_paragraphs returns is what
    it returned in 0.29.5 for the same parts."""
    parts = ["Title here\n\nFirst paragraph runs on and", "runs on and ends here.\n\nA HEADING\n\nSecond one",
             "A HEADING\n\nSecond one is short.", "Nothing shared.\n\nLast."]
    assert doc.join_paragraphs(parts) == ["Title here", "First paragraph runs on and ends here.", "A HEADING",
                                          "Second one is short. Nothing shared.", "Last."]
    assert doc.join_paragraphs(parts, max_overlap=2) == [
        "Title here", "First paragraph runs on and runs on and ends here.", "A HEADING", "Second one A HEADING",
        "Second one is short. Nothing shared.", "Last."]
    assert doc.join_paragraphs([]) == [] and doc.join_paragraphs(["", "one"]) == ["one"]


def test_cite_names_the_section_shown():
    hit = {"doc": "x.txt", "ord": 0, "of": 3, "section": "SHORT ANSWER"}
    assert doc.cite(hit) == "x.txt, SHORT ANSWER"
    assert doc.cite(dict(hit, collection="pack"), with_collection=True) == "pack/x.txt, SHORT ANSWER"
    assert doc.cite(dict(hit, section=None)) == "x.txt, part 1 of 3"


def _store_with_long_document(tmp_path):
    conn = doc.open_store(str(tmp_path / "index.sqlite"))
    doc.set_store_model(conn, "m", 2)
    doc.add_document(conn, "long.txt", "long.txt", [f"long {i}" for i in range(70)], [[1.0, 0.0]] * 70, words=70)
    doc.add_document(conn, "b.txt", "b.txt", ["b one", "b two"], [[0.6, 0.8], [0.8, 0.6]], words=2)
    doc.add_document(conn, "c.txt", "c.txt", ["c one"], [[0.5, 0.86]], words=1)
    return conn


def test_a_long_document_leaves_room_for_the_others(tmp_path):
    conn = _store_with_long_document(tmp_path)
    hits = doc.best_per_document(conn, [1.0, 0.0], top=3)
    assert [(h["doc"], h["text"]) for h in hits] == [("long.txt", "long 0"), ("b.txt", "b two"), ("c.txt", "c one")]
    assert hits[1]["ord"] == 1 and hits[1]["of"] == 2


def test_closest_documents_merges_stores_and_names_them(tmp_path):
    conn = _store_with_long_document(tmp_path)
    hits = doc.closest_documents({"one": conn}, [1.0, 0.0], top=2)
    assert [(h["collection"], h["doc"]) for h in hits] == [("one", "long.txt"), ("one", "b.txt")]


def test_closest_documents_hands_back_what_every_part_scored(tmp_path):
    """The caller's tally holds the sum of the scores and the number of parts
    read, over every store, and the hits are the ones it gets without one."""
    conn = _store_with_long_document(tmp_path)
    plain = doc.closest_documents({"one": conn}, [1.0, 0.0], top=2)
    tally = [0.0, 0]
    assert doc.closest_documents({"one": conn}, [1.0, 0.0], top=2, tally=tally) == plain
    scores = [row[0] for row in doc._scored(conn, [1.0, 0.0])]
    assert tally[1] == len(scores) > 2 and tally[0] == pytest.approx(sum(scores))
    doc.closest_documents({"one": conn, "again": conn}, [1.0, 0.0], top=2, tally=tally)
    assert tally[1] == 3 * len(scores) and tally[0] == pytest.approx(3 * sum(scores))


def test_search_returns_the_closest_parts_in_store_order_on_ties(tmp_path):
    conn = _store_with_long_document(tmp_path)
    assert [h["text"] for h in doc.search(conn, [1.0, 0.0], top=3)] == ["long 0", "long 1", "long 2"]
    assert [h["text"] for h in doc.search(conn, [1.0, 0.0], top=2, doc="b.txt")] == ["b two", "b one"]



def _hits(collection, *standings):
    return [{"collection": collection, "doc": f"{collection}-{i}", "score": 0.5,
             **({} if s is None else {"standing": s})} for i, s in enumerate(standings)]


def test_a_group_that_found_nothing_waits_for_the_one_that_found_the_answer():
    """Rafael, 2026-11-22: «¿Era la encomienda esclavitud?» showed the secret
    key of a wallet first, from the packs of the English model, and the
    encomienda fourth, out of the three results on screen."""
    english = _hits("english", 0.37, 0.36, 0.35)
    history = _hits("history", 0.54, 0.50, 0.49)
    merged = doc.interleave([english, history])
    assert [h["collection"] for h in merged] == ["history"] * 3 + ["english"] * 3


def test_groups_that_both_found_something_still_take_turns_the_best_first():
    one = _hits("one", 0.57, 0.55)
    two = _hits("two", 0.65, 0.56)
    assert [h["doc"] for h in doc.interleave([one, two])] == ["two-0", "one-0", "two-1", "one-1"]


def test_a_group_with_no_standing_keeps_its_turn_and_its_place():
    """A person's own short document has too few parts to say what an
    ordinary part scores, so it is never sent to the back."""
    packs = _hits("packs", 0.6, 0.5, 0.5)
    mine = _hits("mine", None)
    assert [h["collection"] for h in doc.interleave([packs, mine])] == ["packs", "mine", "packs", "packs"]
    assert [h["collection"] for h in doc.interleave([mine, packs])] == ["mine", "packs", "packs", "packs"]
    assert doc.interleave([[], mine]) == mine and doc.interleave([]) == []


def test_standing_needs_enough_parts_and_measures_the_rise_above_the_ordinary():
    few = doc.stand([{"score": 0.9}], [10.0, 20])
    assert "standing" not in few[0]
    many = doc.stand([{"score": 0.75}, {"score": 0.5}], [50.0, 100])       # an ordinary part scores 0.5
    assert [round(h["standing"], 3) for h in many] == [0.5, 0.0]


def test_a_search_over_many_parts_gives_its_hits_a_standing(tmp_path):
    conn = doc.open_store(str(tmp_path / "big.sqlite"))
    doc.set_store_model(conn, "m", 8)
    texts = ["La capital es Madrid."] + [f"otra cosa {i}" for i in range(doc.STANDING_MIN_PARTS)]
    doc.add_document(conn, "big.txt", "/big.txt", texts, [fake_vec(t) for t in texts], words=len(texts))
    for found in (doc.closest_documents({"big": conn}, fake_vec("Madrid"), top=1),
                  doc.search_collections({"big": conn}, fake_vec("Madrid"), top=1)):
        assert found[0]["text"] == "La capital es Madrid." and 0.5 < found[0]["standing"] <= 1.0
    small = doc.open_store(str(tmp_path / "small.sqlite"))
    doc.set_store_model(small, "m", 8)
    doc.add_document(small, "s.txt", "/s.txt", ["Madrid."], [fake_vec("Madrid")], words=1)
    assert "standing" not in doc.closest_documents({"small": small}, fake_vec("Madrid"), top=1)[0]


def test_doc_search_asks_the_loaded_model_first_and_shows_the_same(tmp_path, monkeypatch, capsys):
    """Two models share one port. Asking them in a fixed order stopped the one
    loaded, started the other, then started the first again."""
    from ai2 import cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    asked = []
    monkeypatch.setattr(knowledgecli, "_ensure_embed",
                        lambda hw, model, wait=None, **kw: asked.append(model["id"]) or "http://127.0.0.1:8081/")
    monkeypatch.setattr(doc.EmbedClient, "embed_query", lambda self, q: fake_vec(q))
    _store("spanish", "nomic-embed-text-v2-moe", {"c.pdf": ["Madrid, la capital."]})
    _store("english", "nomic-embed-text-v1.5", {"e.txt": ["Madrid is the capital."]})
    shown = []
    for loaded in (None, "nomic-embed-text-v1.5", "nomic-embed-text-v2-moe"):
        monkeypatch.setattr(serverstate, "read_server",
                            lambda name=serverstate.CHAT, loaded=loaded: {"model": loaded} if loaded else None)
        del asked[:]
        assert cli.main(["doc", "search", "--top", "3", "Madrid capital"]) == 0
        shown.append(capsys.readouterr().out)
        assert sorted(asked) == ["nomic-embed-text-v1.5", "nomic-embed-text-v2-moe"]
        if loaded:
            assert asked[0] == loaded
    assert shown[0] == shown[1] == shown[2]


def _embed_slots(monkeypatch, loaded: dict, avail: int, busy: bool = False):
    """_ensure_embed with these models in the slots and this much free memory.
    Returns what it stopped and what it started."""
    from ai2 import sysinfo
    stopped, started = [], []
    monkeypatch.setattr(serverstate, "read_server",
                        lambda name=serverstate.CHAT: {"model": loaded[name], "pid": 1} if loaded.get(name) else None)
    monkeypatch.setattr(serverstate, "stop_server",
                        lambda name=serverstate.CHAT, **kw: stopped.append(name) or loaded.pop(name, None))
    monkeypatch.setattr(sysinfo, "mem_available_mib", lambda *a: avail)
    monkeypatch.setattr(knowledgecli, "_server_busy", lambda url, timeout=2.0: busy)
    monkeypatch.setattr(runner, "_ensure_server",
                        lambda hw, model, port, record, **kw: started.append((model["id"], port, record)) or f"http://127.0.0.1:{port}/")
    return stopped, started


def test_a_second_search_model_gets_its_own_port_when_memory_allows(monkeypatch):
    """Two models taking turns on one port cost the 2011 laptop 1.8 to 5.6 s of
    every question in stopping one and starting the other."""
    english = {"id": "nomic-embed-text-v1.5", "ram_peak_mb": 300}
    spanish = {"id": "nomic-embed-text-v2-moe", "ram_peak_mb": 1100}
    # room: the other model stays, this one starts beside it
    stopped, started = _embed_slots(monkeypatch, {serverstate.EMBED: spanish["id"]}, avail=2600)
    assert knowledgecli._ensure_embed(None, english, wait=5) == "http://127.0.0.1:8082/"
    assert stopped == [] and started == [(english["id"], 8082, serverstate.EMBED2)]
    # both loaded: each is found on its own port, whatever slot it is in
    stopped, started = _embed_slots(monkeypatch, {serverstate.EMBED: spanish["id"], serverstate.EMBED2: english["id"]}, avail=50)
    assert knowledgecli._ensure_embed(None, english, wait=5) == "http://127.0.0.1:8082/"
    assert knowledgecli._ensure_embed(None, spanish, wait=5) == "http://127.0.0.1:8081/"
    assert stopped == []
    assert knowledgecli._loaded_embedders() == [spanish["id"], english["id"]]
    # a 2 GB computer: no room, so they take turns on the first port as before
    stopped, started = _embed_slots(monkeypatch, {serverstate.EMBED: english["id"]}, avail=1200)
    assert knowledgecli._ensure_embed(None, spanish, wait=5) == "http://127.0.0.1:8081/"
    assert stopped == [serverstate.EMBED] and started == [(spanish["id"], 8081, serverstate.EMBED)]
    # no room and the other model is indexing: left alone, nothing started
    stopped, started = _embed_slots(monkeypatch, {serverstate.EMBED: english["id"]}, avail=1200, busy=True)
    assert knowledgecli._ensure_embed(None, spanish, wait=5) is None and stopped == [] and started == []
    # the only one loaded sits in the second slot and there is no room: it goes, the first port is used
    stopped, started = _embed_slots(monkeypatch, {serverstate.EMBED2: english["id"]}, avail=1200)
    assert knowledgecli._ensure_embed(None, spanish, wait=5) == "http://127.0.0.1:8081/"
    assert stopped == [serverstate.EMBED2] and started == [(spanish["id"], 8081, serverstate.EMBED)]
    # nothing loaded: the first port
    stopped, started = _embed_slots(monkeypatch, {}, avail=100)
    assert knowledgecli._ensure_embed(None, english, wait=5) == "http://127.0.0.1:8081/" and stopped == []


def test_doc_index_uses_its_model_on_whichever_port_it_is_loaded(tmp_path, monkeypatch, capsys):
    """After a search, either model can be on either port. Indexing looked at
    the first port only and gave up when its model was loaded on the second."""
    from ai2 import cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(doc, "choose_embedder", lambda ram, catalog=None: next(
        m for m in embedding_models() if m["id"] == "nomic-embed-text-v2-moe"))
    monkeypatch.setattr(runtime, "find_model_file", lambda f: "/x/" + f)
    monkeypatch.setattr(doc.EmbedClient, "embed_documents", lambda self, chunks, progress=None: [fake_vec(c) for c in chunks])
    monkeypatch.setattr(doc.EmbedClient, "ntokens", lambda self, text: len(text.split()))
    note = tmp_path / "nota.txt"
    note.write_text("Madrid es la capital de España.")
    stopped, started = _embed_slots(monkeypatch, {serverstate.EMBED: "nomic-embed-text-v1.5",
                                                  serverstate.EMBED2: "nomic-embed-text-v2-moe"}, avail=50)
    assert cli.main(["doc", "index", str(note)]) == 0
    assert started == [("nomic-embed-text-v2-moe", 8082, serverstate.EMBED2)] and stopped == []
    assert "1 parts indexed" in capsys.readouterr().out
    note.write_text("A changed document needs the embedding server again.")
    # the other model is busy and there is no room: said plainly, nothing stopped
    stopped, started = _embed_slots(monkeypatch, {serverstate.EMBED: "nomic-embed-text-v1.5"}, avail=50, busy=True)
    assert cli.main(["doc", "index", str(note)]) == 1
    assert "another one is loaded and busy" in capsys.readouterr().err and stopped == [] and started == []


def test_repeated_import_skips_all_model_work_and_failed_replacement_retries(tmp_path, monkeypatch, capsys):
    from ai2 import cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    model = next(m for m in embedding_models() if m["id"] == "nomic-embed-text-v1.5")
    monkeypatch.setattr(doc, "choose_embedder", lambda ram: model)
    starts = []
    client = doc.EmbedClient("http://unused", model)

    def start(*args):
        starts.append(True)
        return client

    monkeypatch.setattr(knowledgecli, "_index_client", start)
    monkeypatch.setattr(client, "ntokens", lambda text: len(text.split()))
    monkeypatch.setattr(client, "embed_documents", lambda texts, **kw: [fake_vec(t) for t in texts])
    path = tmp_path / "lesson.txt"
    path.write_text("Madrid is the capital.")
    args = ["doc", "index", str(path)]
    assert cli.main(args) == 0
    with monkeypatch.context() as m:
        m.setattr(doc, "extract_pages", lambda *a, **kw: pytest.fail("unchanged file extracted again"))
        assert cli.main(args) == 0
    assert len(starts) == 1 and "unchanged" in capsys.readouterr().out
    assert cli.main([*args, "--force"]) == 0 and len(starts) == 2
    path.write_text("A changed lesson.")

    def fail(*a, **kw):
        raise OSError("engine stopped")

    with monkeypatch.context() as m:
        m.setattr(client, "embed_documents", fail)
        assert cli.main(args) == 1
    conn = doc.open_store()
    assert conn.execute("SELECT text FROM chunks").fetchone()[0] == "Madrid is the capital."
    assert cli.main(args) == 0 and len(starts) == 4
    assert conn.execute("SELECT text FROM chunks").fetchone()[0] == "A changed lesson."
    # Pre-fingerprint indexes acquire the metadata the next time they are imported.
    conn.execute("DROP TABLE index_fingerprints")
    conn.commit()
    conn.close()
    assert cli.main(args) == 0 and len(starts) == 5
    assert cli.main(args) == 0 and len(starts) == 5
    model = dict(model, ctx=model["ctx"] // 2)
    monkeypatch.setattr(runner, "_catalog_entry", lambda model_id: model)
    assert cli.main(args) == 0 and len(starts) == 6


# --------------------------------------------- an import that was stopped
# Each batch of four vectors is committed as it comes back, and the same
# command carries on from the first part without one.

class _Killed(BaseException):
    """What a power cut or kill -9 looks like from inside: nothing after it
    runs, no handler, no cleanup."""


def _long_text(n_words=2000):
    keys = ("Madrid", "castellano", "bandera", "monarquía", "dieciocho", "tortura", "religión")
    return " ".join(f"{keys[i % len(keys)]}{i // 7}" if i % 13 else f"palabra{i}." for i in range(n_words))


@pytest.fixture
def resume(tmp_path, monkeypatch):
    """`ai-2 doc index` with a fake embedding server that records every batch
    and can be made to stop at a given batch."""
    from ai2 import cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    world = {"model": next(m for m in embedding_models() if m["id"] == "nomic-embed-text-v1.5"),
             "batches": [], "stop_at": None, "stop_with": KeyboardInterrupt, "starts": 0}
    monkeypatch.setattr(doc, "choose_embedder", lambda ram, catalog=None: world["model"])
    monkeypatch.setattr(runner, "_catalog_entry", lambda model_id: world["model"])
    client = doc.EmbedClient("http://unused", world["model"])

    def start(*a):
        world["starts"] += 1
        client.model = world["model"]
        return client

    def embed(texts, progress=None):
        if world["stop_at"] is not None and len(world["batches"]) == world["stop_at"]:
            raise world["stop_with"]("stopped here")
        world["batches"].append(list(texts))
        return [fake_vec(t) + [float(len(t))] for t in texts]

    monkeypatch.setattr(knowledgecli, "_index_client", start)
    monkeypatch.setattr(knowledgecli, "detect", lambda: type("HW", (), {"ram_mib": 8000})())
    monkeypatch.setattr(client, "ntokens", lambda text: len(text.split()))
    monkeypatch.setattr(client, "embed_documents", embed)
    f = tmp_path / "ley.txt"
    f.write_text(_long_text(), encoding="utf-8")
    world.update(cli=cli, file=f, client=client)
    return world


def _rows(collection=None):
    conn = doc.open_store(None if collection is None else doc.index_path(collection))
    rows = conn.execute("SELECT chunks.ord, chunks.text, chunks.vec, chunks.page, chunks.page_end FROM chunks "
                        "JOIN docs ON docs.id = chunks.doc_id ORDER BY chunks.ord").fetchall()
    left = conn.execute("SELECT COUNT(*) FROM index_checkpoints").fetchone()[0] + \
        conn.execute("SELECT COUNT(*) FROM checkpoint_parts").fetchone()[0]
    conn.close()
    return rows, left


def test_a_stopped_import_carries_on_and_ends_as_an_uninterrupted_one(resume, capsys):
    cli, f = resume["cli"], resume["file"]
    assert cli.main(["doc", "index", "--in", "whole", str(f)]) == 0
    whole, _ = _rows("whole")
    total = len(whole)
    assert total >= 20
    resume["batches"].clear()
    resume["stop_at"] = 2                                   # Ctrl+C during the third batch
    assert cli.main(["doc", "index", str(f)]) == 130
    assert "8 of %d parts are saved" % total in capsys.readouterr().err
    assert doc.unfinished_imports(doc.open_store()) == [{"name": "ley.txt", "done": 8, "total": total,
                                                         "path": str(f)}]
    done_before = [t for b in resume["batches"] for t in b]
    resume["batches"].clear()
    resume["stop_at"] = None
    with pytest.MonkeyPatch.context() as m:
        m.setattr(doc, "extract_pages", lambda *a, **kw: pytest.fail("a resumed import read the file again"))
        m.setattr(resume["client"], "ntokens", lambda text: pytest.fail("a resumed import cut the parts again"))
        assert cli.main(["doc", "index", str(f)]) == 0
    out = capsys.readouterr().out
    assert f"resuming, 8 of {total} parts already done" in out
    again = [t for b in resume["batches"] for t in b]
    assert len(again) == total - 8 and not set(again) & set(done_before)
    rows, left = _rows()
    assert rows == whole and left == 0                      # byte for byte, and the checkpoint is gone
    assert cli.main(["doc", "index", str(f)]) == 0 and "unchanged" in capsys.readouterr().out


def test_a_kill_between_batches_keeps_the_batches_already_done(resume, capsys):
    cli, f = resume["cli"], resume["file"]
    resume["stop_at"], resume["stop_with"] = 3, _Killed
    with pytest.raises(_Killed):
        cli.main(["doc", "index", str(f)])
    raw = sqlite3.connect(doc.index_path())                 # what the next process finds on disk
    assert raw.execute("SELECT COUNT(vec), COUNT(*) FROM checkpoint_parts").fetchone()[0] == 12
    assert raw.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
    raw.close()
    # the embedding server dying is said plainly, and nothing is lost either
    resume["stop_at"], resume["stop_with"] = 5, OSError
    assert cli.main(["doc", "index", str(f)]) == 1
    err = capsys.readouterr().err
    assert "20 of" in err and "carries on from there" in err
    resume["stop_at"] = None
    assert cli.main(["doc", "index", str(f)]) == 0
    assert "resuming, 20 of" in capsys.readouterr().out
    rows, left = _rows()
    assert len({r[1] for b in [rows] for r in b}) == len(rows) and left == 0
    assert len([t for b in resume["batches"] for t in b]) == len(rows)    # every part embedded exactly once


def test_a_changed_file_or_model_or_force_starts_again(resume, capsys):
    cli, f = resume["cli"], resume["file"]
    resume["stop_at"] = 1
    assert cli.main(["doc", "index", str(f)]) == 130
    resume["stop_at"] = None
    f.write_text(_long_text(2100), encoding="utf-8")
    resume["batches"].clear()
    resume["stop_at"] = 1
    assert cli.main(["doc", "index", str(f)]) == 130
    assert "changed since its import was stopped" in capsys.readouterr().out
    conn = doc.open_store()
    assert conn.execute("SELECT COUNT(*) FROM index_checkpoints").fetchone()[0] == 1
    assert doc.unfinished_imports(conn)[0]["done"] == 4
    # another search model file (a new revision of the model) is another recipe
    resume["model"] = dict(resume["model"], sha256="0" * 64)
    resume["batches"].clear()
    assert cli.main(["doc", "index", str(f)]) == 130
    assert "changed since its import was stopped" in capsys.readouterr().out
    # --force throws a checkpoint away even when it would fit
    resume["stop_at"] = None
    resume["batches"].clear()
    assert cli.main(["doc", "index", "--force", str(f)]) == 0
    out = capsys.readouterr().out
    rows, left = _rows()
    assert "resuming" not in out and len([t for b in resume["batches"] for t in b]) == len(rows) and left == 0


def test_forget_and_removing_the_collection_leave_nothing_behind(resume, capsys):
    cli, f = resume["cli"], resume["file"]
    resume["stop_at"] = 2
    assert cli.main(["doc", "index", "--in", "leyes", str(f)]) == 130
    assert cli.main(["doc", "list"]) == 0
    assert "import stopped at 8 of" in capsys.readouterr().out
    assert cli.main(["doc", "forget", "ley.txt"]) == 0
    assert "Dropped the stopped import of ley.txt. (collection leyes)" in capsys.readouterr().out
    assert _rows("leyes") == ([], 0)
    # a document that is indexed and whose newer version was stopped goes whole
    resume["stop_at"] = None
    assert cli.main(["doc", "index", "--in", "leyes", str(f)]) == 0
    f.write_text(_long_text(2100), encoding="utf-8")
    resume["stop_at"] = len(resume["batches"]) + 1
    assert cli.main(["doc", "index", "--in", "leyes", str(f)]) == 130
    assert cli.main(["doc", "forget", "ley.txt"]) == 0
    assert "Forgot 1 document." in capsys.readouterr().out and _rows("leyes") == ([], 0)
    assert cli.main(["doc", "index", "--in", "leyes", str(f)]) == 130
    assert cli.main(["doc", "forget", "--all", "--in", "leyes"]) == 0
    assert not os.path.exists(os.path.dirname(doc.index_path("leyes")))
    # forget --all on a store keeps nothing of a stopped import either
    conn = doc.open_store(doc.index_path("otra"))
    doc.start_checkpoint(conn, "a.txt", "/a.txt", "fp", ["one", "two"], None, 2)
    doc.forget(conn, everything=True)
    assert conn.execute("SELECT COUNT(*) FROM checkpoint_parts").fetchone()[0] == 0


def test_a_store_from_an_older_version_gains_checkpoints_and_resumes(resume, capsys):
    cli, f = resume["cli"], resume["file"]
    os.makedirs(os.path.dirname(doc.index_path()))
    old = sqlite3.connect(doc.index_path())
    old.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE docs (id INTEGER PRIMARY KEY, name TEXT UNIQUE, path TEXT, added TEXT, words INTEGER, chunks INTEGER);
        CREATE TABLE chunks (id INTEGER PRIMARY KEY, doc_id INTEGER REFERENCES docs(id) ON DELETE CASCADE,
                             ord INTEGER, text TEXT, vec BLOB);
        INSERT INTO meta VALUES ('model', 'nomic-embed-text-v1.5'), ('dims', '9');
        INSERT INTO docs VALUES (1, 'old.txt', '/old.txt', '2026-09-14 10:00', 3, 1);
    """)
    old.execute("INSERT INTO chunks VALUES (1, 1, 0, 'Madrid es la capital.', ?)", (doc.to_blob(fake_vec("madrid")),))
    old.commit()
    old.close()
    resume["stop_at"] = 1
    assert cli.main(["doc", "index", str(f)]) == 130
    resume["stop_at"] = None
    assert cli.main(["doc", "index", str(f)]) == 0
    assert "resuming, 4 of" in capsys.readouterr().out
    assert [d["name"] for d in doc.list_documents(doc.open_store())] == ["old.txt", "ley.txt"]


def test_a_read_only_store_without_checkpoint_tables_still_lists(tmp_path, monkeypatch, capsys):
    """A Knowledge Pack that came with AI-2 is opened read-only and its schema
    is never touched, and one made by `ai-2 knowledge export` has no
    checkpoint tables at all."""
    from ai2 import cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    _system_pack(tmp_path, monkeypatch)
    path = doc.read_index_path("ai2-help")
    os.chmod(path, 0o644)                   # drop the tables as export_pack does
    raw = sqlite3.connect(path)
    raw.execute("DROP TABLE checkpoint_parts")
    raw.execute("DROP TABLE index_checkpoints")
    raw.commit()
    assert not {"checkpoint_parts", "index_checkpoints"} & {
        r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    raw.close()
    os.chmod(path, 0o444)
    conn = doc.open_store(path)
    assert doc.unfinished_imports(conn) == [] and doc.checkpoint_for(conn, "help.txt", "x") == (None, False)
    assert doc.discard_checkpoint(conn, "help.txt") == 0
    conn.close()
    assert cli.main(["doc", "list"]) == 0 and "help.txt" in capsys.readouterr().out


def test_parts_are_cut_the_same_way_every_time():
    """The checkpoint stores the parts, so a resume never depends on this, but
    the parts of an uninterrupted import and of a resumed one come from the
    same function with the same counter."""
    pages = [_long_text(700), _long_text(500)]
    count = lambda c: len(c.split())                                  # noqa: E731
    assert doc.make_chunks(pages, True, count, 60) == doc.make_chunks(list(pages), True, count, 60)


# ------------------------------------- a stopped import that goes wrong

def _docs(collection=None):
    conn = doc.open_store(None if collection is None else doc.index_path(collection))
    rows = conn.execute("SELECT name, words, chunks FROM docs ORDER BY name").fetchall()
    conn.close()
    return rows


def test_a_stopped_import_forgotten_while_it_runs_writes_no_empty_document(resume, capsys):
    """`ai-2 doc forget` in another terminal while the import is going: the
    import stops saying so, and no document of 0 parts is left to be called
    unchanged afterwards."""
    cli, f = resume["cli"], resume["file"]
    embed = resume["client"].embed_documents

    def forget_in_third_batch(texts, progress=None):
        if len(resume["batches"]) == 2:
            assert cli.main(["doc", "forget", "ley.txt"]) == 0
        return embed(texts, progress)

    resume["client"].embed_documents = forget_in_third_batch
    assert cli.main(["doc", "index", str(f)]) == 1
    captured = capsys.readouterr()
    assert "Dropped the stopped import of ley.txt." in captured.out
    assert "dropped or finished by another run" in captured.err and "parts indexed" not in captured.out
    assert _docs() == [] and _rows() == ([], 0)
    resume["client"].embed_documents = embed
    assert cli.main(["doc", "index", str(f)]) == 0
    assert "unchanged" not in capsys.readouterr().out and len(_rows()[0]) == _docs()[0][2] > 0


def test_a_stopped_import_finished_by_another_run_is_left_as_that_run_wrote_it(resume, capsys):
    cli, f = resume["cli"], resume["file"]
    assert cli.main(["doc", "index", "--in", "whole", str(f)]) == 0
    whole, _ = _rows("whole")
    resume["batches"].clear()
    resume["stop_at"] = 2
    assert cli.main(["doc", "index", str(f)]) == 130
    resume["stop_at"] = None
    embed = resume["client"].embed_documents
    other = {"ran": False}

    def second_run_inside(texts, progress=None):
        if not other["ran"]:                # a second doc index of the same file finishes first
            other["ran"] = True
            assert cli.main(["doc", "index", str(f)]) == 0
        return embed(texts, progress)

    resume["client"].embed_documents = second_run_inside
    assert cli.main(["doc", "index", str(f)]) == 1
    err = capsys.readouterr().err
    assert "dropped or finished by another run" in err
    rows, left = _rows()
    assert rows == whole and left == 0 and _docs() == [("ley.txt", 2000, len(whole))]
    resume["client"].embed_documents = embed
    assert cli.main(["doc", "index", str(f)]) == 0 and "unchanged" in capsys.readouterr().out


def test_a_file_saved_while_it_is_read_leaves_no_stopped_import(resume, capsys, monkeypatch):
    """The parts saved for a resume must be the text the fingerprint was taken
    from; an editor saving the file between the two would otherwise store the
    edited text under the old fingerprint."""
    cli, f = resume["cli"], resume["file"]
    original = f.read_text(encoding="utf-8")
    assert cli.main(["doc", "index", "--in", "whole", str(f)]) == 0
    whole, _ = _rows("whole")
    extract = doc.extract_pages

    def saved_meanwhile(path, lang="eng"):
        f.write_text("EDITED " + original, encoding="utf-8")
        return extract(path, lang=lang)

    with pytest.MonkeyPatch.context() as m:
        m.setattr(doc, "extract_pages", saved_meanwhile)
        assert cli.main(["doc", "index", str(f)]) == 1
    assert "file changed while reading" in capsys.readouterr().err
    assert doc.unfinished_imports(doc.open_store()) == []
    f.write_text(original, encoding="utf-8")
    assert cli.main(["doc", "index", str(f)]) == 0
    assert "resuming" not in capsys.readouterr().out and _rows() == (whole, 0)


def test_a_file_put_back_to_its_indexed_version_drops_its_stopped_import(resume, capsys):
    cli, f = resume["cli"], resume["file"]
    original = f.read_text(encoding="utf-8")
    assert cli.main(["doc", "index", str(f)]) == 0
    f.write_text(_long_text(2100), encoding="utf-8")
    resume["stop_at"] = len(resume["batches"]) + 1
    assert cli.main(["doc", "index", str(f)]) == 130
    f.write_text(original, encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["doc", "index", str(f)]) == 0 and "unchanged" in capsys.readouterr().out
    assert doc.unfinished_imports(doc.open_store()) == []
    assert cli.main(["doc", "list"]) == 0
    out = capsys.readouterr().out
    assert out.count("ley.txt") == 1 and "import stopped" not in out


def test_a_full_disk_says_what_is_saved_and_goes_on_with_the_next_file(resume, capsys, tmp_path):
    cli, f = resume["cli"], resume["file"]
    other = tmp_path / "otra.txt"
    other.write_text(_long_text(300), encoding="utf-8")
    embed = resume["client"].embed_documents

    def full_once(texts, progress=None):
        if len(resume["batches"]) == 2 and not resume.get("full"):
            resume["full"] = True               # the vectors of batch 3 do not fit
            raise sqlite3.OperationalError("database or disk is full")
        return embed(texts, progress)

    resume["client"].embed_documents = full_once
    assert cli.main(["doc", "index", str(f), str(other)]) == 1
    captured = capsys.readouterr()
    assert "8 of" in captured.err and "parts are saved" in captured.err and "Traceback" not in captured.err
    assert "otra.txt: " in captured.out and "parts indexed" in captured.out
    resume["client"].embed_documents = embed
    assert cli.main(["doc", "index", str(f)]) == 0
    assert "resuming, 8 of" in capsys.readouterr().out and _rows()[1] == 0


def test_a_full_disk_before_the_first_part_is_saved_is_said_plainly(resume, capsys, monkeypatch):
    cli, f = resume["cli"], resume["file"]
    open_store = doc.open_store

    def full(path=None):
        conn = open_store(path)
        conn.execute("PRAGMA max_page_count = %d" % conn.execute("PRAGMA page_count").fetchone()[0])
        return conn

    with pytest.MonkeyPatch.context() as m:
        m.setattr(doc, "open_store", full)
        assert cli.main(["doc", "index", str(f)]) == 1
    assert "could not be saved" in capsys.readouterr().err
    assert doc.unfinished_imports(doc.open_store()) == []
    assert cli.main(["doc", "index", str(f)]) == 0 and _rows()[1] == 0


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes to a read-only file")
def test_a_read_only_store_from_before_checkpoints_still_opens(tmp_path, monkeypatch, capsys):
    from ai2 import cli
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    path = doc.index_path("viejo")
    os.makedirs(os.path.dirname(path))
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE docs (id INTEGER PRIMARY KEY, name TEXT UNIQUE, path TEXT, added TEXT, words INTEGER, chunks INTEGER);
        CREATE TABLE index_fingerprints (doc_id INTEGER PRIMARY KEY REFERENCES docs(id) ON DELETE CASCADE,
                                         fingerprint TEXT NOT NULL);
        CREATE TABLE chunks (id INTEGER PRIMARY KEY, doc_id INTEGER REFERENCES docs(id) ON DELETE CASCADE,
                             ord INTEGER, text TEXT, vec BLOB, page INTEGER, page_end INTEGER);
        INSERT INTO meta VALUES ('model', 'nomic-embed-text-v1.5'), ('dims', '9');
        INSERT INTO docs VALUES (1, 'old.txt', '/old.txt', '2026-09-14 10:00', 3, 1);
    """)
    old.execute("INSERT INTO chunks VALUES (1, 1, 0, 'Madrid es la capital.', ?, NULL, NULL)",
                (doc.to_blob(fake_vec("madrid")),))
    old.commit()
    old.close()
    os.chmod(path, 0o444)
    conn = doc.open_store(path)
    assert [d["name"] for d in doc.list_documents(conn)] == ["old.txt"] and doc.unfinished_imports(conn) == []
    conn.close()
    assert cli.main(["doc", "list"]) == 0 and "old.txt" in capsys.readouterr().out


def test_doc_list_says_when_the_file_of_a_stopped_import_is_gone(resume, capsys):
    cli, f = resume["cli"], resume["file"]
    resume["stop_at"] = 2
    assert cli.main(["doc", "index", "--in", "nueva", str(f)]) == 130
    capsys.readouterr()
    assert cli.main(["doc", "list"]) == 0
    out = capsys.readouterr().out
    assert "the same ai-2 doc index carries on" in out and "embedder None" not in out
    f.rename(f.with_name("otro.txt"))
    assert cli.main(["doc", "list"]) == 0
    out = capsys.readouterr().out
    assert f"the file is no longer at {f}, ai-2 doc forget ley.txt drops it" in out


def test_a_stopped_pdf_resumes_with_its_pages_and_word_count(resume, capsys, monkeypatch):
    cli, f = resume["cli"], resume["file"]
    pages = [_long_text(), _long_text(1500), _long_text(1000)]
    monkeypatch.setattr(doc, "extract_pages", lambda *a, **kw: (list(pages), True))
    words = sum(len(p.split()) for p in pages)
    assert cli.main(["doc", "index", "--in", "whole", str(f)]) == 0
    whole, _ = _rows("whole")
    resume["batches"].clear()
    resume["stop_at"] = 2
    assert cli.main(["doc", "index", str(f)]) == 130
    resume["stop_at"] = None
    assert cli.main(["doc", "index", str(f)]) == 0
    rows, left = _rows()
    assert rows == whole and left == 0
    assert all(r[3] is not None and r[4] is not None for r in rows) and rows[-1][4] == 3
    assert _docs() == _docs("whole") == [("ley.txt", words, len(rows))]


def test_a_stored_vector_is_the_servers_vector_made_unit_length(resume, capsys):
    """Not only the same bytes as an uninterrupted run, which goes through the
    same code: the bytes the server's vector gives."""
    cli, f = resume["cli"], resume["file"]
    resume["stop_at"] = 2
    assert cli.main(["doc", "index", str(f)]) == 130
    resume["stop_at"] = None
    assert cli.main(["doc", "index", str(f)]) == 0
    rows, _ = _rows()
    assert rows and all(vec == doc.to_blob(fake_vec(text) + [float(len(text))]) for _, text, vec, _, _ in rows)


def test_an_incomplete_batch_keeps_what_was_saved(resume, capsys):
    cli, f = resume["cli"], resume["file"]
    embed = resume["client"].embed_documents

    def one_short(texts, progress=None):
        vectors = embed(texts, progress)
        return vectors[:-1] if len(resume["batches"]) == 3 else vectors

    resume["client"].embed_documents = one_short
    assert cli.main(["doc", "index", str(f)]) == 1
    err = capsys.readouterr().err
    assert "skipped ley.txt" in err and "incomplete batch" in err
    conn = doc.open_store()
    assert doc.unfinished_imports(conn)[0]["done"] == 8
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
    resume["client"].embed_documents = embed
    assert cli.main(["doc", "index", str(f)]) == 0 and "resuming, 8 of" in capsys.readouterr().out


def test_minutes_left_after_a_resume_count_only_this_run(resume, capsys, monkeypatch):
    import time
    cli, f = resume["cli"], resume["file"]
    resume["stop_at"] = 2
    assert cli.main(["doc", "index", str(f)]) == 130
    total = doc.unfinished_imports(doc.open_store())[0]["total"]
    resume["stop_at"] = None
    clock = iter(range(0, 60 * 1000, 60))
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))
    capsys.readouterr()
    assert cli.main(["doc", "index", str(f)]) == 0
    left = int(60 / 4 * (total - 12) / 60) + 1
    assert f"12/{total} parts, 60 s, about {left} min left" in capsys.readouterr().out
