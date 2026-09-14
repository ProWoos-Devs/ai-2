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


def test_build_messages_numbers_the_excerpts():
    hits = [{"text": "El castellano es la lengua oficial.", "doc": "c.pdf", "ord": 2, "of": 37, "score": 0.9},
            {"text": "Madrid es la capital.", "doc": "c.pdf", "ord": 4, "of": 37, "score": 0.8}]
    msgs = doc.build_messages("¿Cuál es la capital?", hits, doc.doc_system_prompt("You are the assistant."))
    assert msgs[0]["role"] == "system" and "cite them as [1], [2]" in msgs[0]["content"]
    user = msgs[1]["content"]
    assert "[1] (c.pdf, part 3 of 37)" in user and "[2] (c.pdf, part 5 of 37)" in user
    assert user.rstrip().endswith("If they do not contain the answer, say so.")
    assert "Question: ¿Cuál es la capital?" in user


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
