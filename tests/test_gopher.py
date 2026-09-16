"""`ai-2 gopher`: the protocol itself, spoken over a real socket."""
import socket

import pytest
import yaml

from ai2 import doc, gopher


def vec(text):
    keys = ("madrid", "capital", "frozen", "program", "disk", "x", "y", "z")
    return [1.0 if k in text.lower() else 0.05 for k in keys]


def talk(server, request: str) -> str:
    """One Gopher exchange: send a selector (and query), read to the end."""
    host, port = server.server_address
    with socket.create_connection((host, port), timeout=10) as s:
        s.sendall(request.encode() + b"\r\n")
        out = b""
        while True:
            block = s.recv(4096)
            if not block:
                break
            out += block
    return out.decode()


@pytest.fixture
def library(tmp_path, monkeypatch):
    """One installed pack and one collection of the user's own."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    conn = doc.open_store(doc.index_path("everyday"))
    doc.set_store_model(conn, "nomic-embed-text-v1.5", 8)
    doc.add_document(conn, "spain.txt", "spain.txt",
                     ["Spain The capital of Spain is Madrid.", "The currency used in Spain is the euro."],
                     [vec("madrid capital"), vec("euro")], words=14, pages=[(1, 1), (1, 1)])
    conn.close()
    manifest = {"id": "everyday", "title": "Everyday Reference", "version": "2026-09-16",
                "license": "CC0-1.0", "attribution": "Facts from Wikidata.", "format": 1}
    (tmp_path / "data/ai2/doc/everyday/manifest.yml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    mine = doc.open_store(doc.index_path("my-notes"))
    doc.set_store_model(mine, "nomic-embed-text-v1.5", 8)
    doc.add_document(mine, "private.txt", "/home/me/private.txt", ["My private disk notes."],
                     [vec("disk")], words=4)
    mine.close()
    return tmp_path


def serve(everything=False, embed=None):
    server = gopher.serve(embed or (lambda model_id, text: vec(text)), host="127.0.0.1", port=0,
                          everything=everything)
    import threading
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_root_menu_offers_only_packs_until_all_is_given(library):
    server = serve()
    try:
        root = talk(server, "")
        assert "7Ask Everyday Reference\t/search/everyday\t127.0.0.1\t" in root
        assert "1What is in Everyday Reference\t/list/everyday\t" in root
        assert "my-notes" not in root                      # the user's own documents stay private
        assert root.endswith(".\r\n") and root.count("\r\n") > 3
    finally:
        server.shutdown()
    server = serve(everything=True)
    try:
        assert "/search/my-notes" in talk(server, "")
    finally:
        server.shutdown()


def test_search_returns_the_passage_and_the_pack_terms(library):
    server = serve()
    try:
        out = talk(server, "/search/everyday\twhat is the capital of Spain?")
        assert "i[1] spain.txt, page 1\t" in out
        assert "The capital of Spain is Madrid." in out
        assert "0    the whole of spain.txt\t/doc/everyday/spain.txt\t" in out
        assert "Facts from Wikidata." in out
        assert talk(server, "/search/everyday\t   ").startswith("3Type a question")
        assert talk(server, "/search/my-notes\tdisk").startswith("3No knowledge called")
    finally:
        server.shutdown()


def test_document_is_text_with_the_overlap_trimmed(library):
    server = serve()
    try:
        out = talk(server, "/doc/everyday/spain.txt")
        assert out.startswith("spain.txt\r\n=========\r\n")
        assert "The capital of Spain is Madrid. The currency used in Spain is the euro." in out.replace("\r\n", " ")
        assert out.endswith(".\r\n")
        assert talk(server, "/doc/everyday/ghost.txt").startswith("3No document called")
    finally:
        server.shutdown()


def test_bad_selectors_are_refused(library):
    server = serve()
    try:
        for selector in ("/doc/../../etc/passwd", "/list/../secrets", "/search/Bad Name\tq",
                         "/nonsense", "/doc/everyday"):
            assert talk(server, selector).startswith("3"), selector
        assert talk(server, "/list/everyday").startswith("iEveryday Reference")
    finally:
        server.shutdown()


def test_an_embedding_failure_is_reported_not_crashed(library):
    def broken(model_id, text):
        raise RuntimeError("the embedding server did not start")
    server = serve(embed=broken)
    try:
        out = talk(server, "/search/everyday\tanything")
        assert out.startswith("3Cannot answer right now (the embedding server did not start)")
        assert talk(server, "").startswith("i")          # the server is still up
    finally:
        server.shutdown()


def test_join_parts_trims_the_overlap_and_text_pages_escape_a_lone_dot():
    parts = ["one two three four five", "four five six seven", "seven eight"]
    assert gopher.join_parts(parts, max_overlap=5).split() == \
        "one two three four five six seven eight".split()
    assert gopher.join_parts([]) == ""
    page = gopher.text_page("a\n.\nb")
    assert page == "a\r\n..\r\nb\r\n.\r\n"


def test_menu_lines_cannot_be_broken_by_a_tab_in_a_name():
    out = gopher.line("0", "a\tname\nwith control", "/doc/x\ty", "host", 70)
    assert out == "0a name with control\t/doc/x y\thost\t70\r\n"
