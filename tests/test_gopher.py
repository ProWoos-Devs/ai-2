"""`ai-2 gopher`: the protocol itself, spoken over a real socket."""
import socket
import time

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


def test_one_question_at_a_time_by_default(library):
    """A search embeds the question and then scans every vector in plain
    Python, seconds of a core on the machines AI-2 is built for. Threads would
    let one eager client start several at once, so the default server is
    sequential and `--workers N` bounds the rest."""
    import threading
    import time
    started, done = [], []
    gate = threading.Event()

    def slow_embed(model_id, text):
        started.append(time.monotonic())
        gate.wait(5)
        done.append(time.monotonic())
        return vec(text)

    server = serve(embed=slow_embed)
    assert isinstance(server, gopher.Sequential) and server.gate is None
    try:
        first = threading.Thread(target=talk, args=(server, "/search/everyday\tcapital"))
        first.start()
        while not started:
            time.sleep(0.02)
        # the second request cannot even begin while the first is being answered
        second = threading.Thread(target=talk, args=(server, "/search/everyday\tcapital"))
        second.start()
        time.sleep(0.3)
        assert len(started) == 1, "a second question was answered while the first was still running"
        gate.set()
        first.join(10)
        second.join(10)
        assert len(started) == 2 and len(done) == 2
    finally:
        gate.set()
        server.shutdown()


def test_workers_bounds_how_many_run_at_once(library):
    import threading
    import time
    inside = []
    peak = [0]
    gate = threading.Event()

    def slow_embed(model_id, text):
        inside.append(1)
        peak[0] = max(peak[0], len(inside))
        gate.wait(5)
        inside.pop()
        return vec(text)

    server = serve(embed=slow_embed)
    server.shutdown()
    server = gopher.serve(slow_embed, host="127.0.0.1", port=0, workers=2)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert isinstance(server, gopher.Threaded)
        threads = [threading.Thread(target=talk, args=(server, "/search/everyday\tcapital")) for _ in range(4)]
        for t in threads:
            t.start()
        time.sleep(0.5)
        assert peak[0] <= 2, f"{peak[0]} questions ran at once with --workers 2"
        gate.set()
        for t in threads:
            t.join(10)
    finally:
        gate.set()
        server.shutdown()


def test_search_and_document_name_the_source_url_and_licence(library, tmp_path):
    """Gopher says where the text came from the way the command line does:
    the document's own source URL, the pack and its licence, the attribution."""
    import yaml
    manifest = yaml.safe_load((tmp_path / "data/ai2/doc/everyday/manifest.yml").read_text())
    manifest["sources"] = [{"file": "spain.txt", "title": "Spain", "url": "https://example.org/spain"}]
    (tmp_path / "data/ai2/doc/everyday/manifest.yml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    server = serve()
    try:
        out = talk(server, "/search/everyday\twhat is the capital of Spain?")
        assert "i    source: https://example.org/spain\t" in out
        assert "From the pack Everyday Reference (CC0-1.0), version 2026-09-16." in out
        assert "Facts from Wikidata." in out
        page = talk(server, "/doc/everyday/spain.txt")
        assert "Source: https://example.org/spain" in page
        assert "From the pack Everyday Reference (CC0-1.0), version 2026-09-16." in page
        assert "Facts from Wikidata." in page
    finally:
        server.shutdown()


# ---------------------------------------------------- chat, this computer only

def chat_server(reply, tmp_path=None):
    server = gopher.serve(lambda model_id, text: vec(text), host="127.0.0.1", port=0, chat_reply=reply)
    server.menus.port = server.server_address[1]
    import threading
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def items(reply, kind="7"):
    return [l.split("\t") for l in reply.splitlines() if l.startswith(kind)]


def test_chat_item_is_offered_only_to_this_computer(library):
    server = chat_server(lambda h: iter(["hi"]))
    try:
        assert any("/chat" == i[1] for i in items(talk(server, "")))
        assert "/chat" not in server.menus.root(local=False)
        assert items(server.menus.root(local=True))[0][1:3] == ["/chat", "127.0.0.1"]
    finally:
        server.shutdown()


def test_a_server_with_no_chat_keeps_the_old_menu(library):
    server = serve()
    try:
        assert "/chat" not in talk(server, "")
        assert talk(server, "/chat\thello").startswith("3")
    finally:
        server.shutdown()


def test_chat_refuses_a_peer_on_the_network(library):
    server = chat_server(lambda h: pytest.fail("the model must not be asked"))
    sent = []

    class Fake(gopher.Handler):
        def __init__(self):
            self.server = server
            self.wfile = type("W", (), {"write": lambda _s, b: sent.append(b)})()
    try:
        Fake()._chat("/chat", "hello", local=False)
        assert sent[0].startswith(b"3Chat answers only on the computer")
        assert "192.168.1.5" not in gopher.LOOPBACK and "127.0.0.1" in gopher.LOOPBACK
    finally:
        server.shutdown()


def test_chat_answer_ends_with_the_next_question_and_keeps_the_conversation(library):
    seen = []

    def reply(history):
        seen.append(list(history))
        return iter(["Hola, ", "soy la IA.\n", "Segunda linea."])
    server = chat_server(reply)
    try:
        first = talk(server, "/chat\tquien eres")
        assert "i> quien eres" in first and "Reading your question" in first
        assert "iHola, soy la IA." in first and "iSegunda linea." in first and first.endswith(".\r\n")
        next_item, new_item = items(first)
        assert next_item[1].startswith("/chat/") and new_item[1] == "/chat"
        talk(server, f"{next_item[1]}\ty ahora")
        assert [m["content"] for m in seen[1]] == ["quien eres", "Hola, soy la IA.\nSegunda linea.", "y ahora"]
        talk(server, "/chat\totra cosa")
        assert [m["content"] for m in seen[2]] == ["otra cosa"]      # a new conversation
    finally:
        server.shutdown()


def test_chat_lines_arrive_before_the_answer_is_finished(library):
    """The whole point of chat over Gopher: nothing is held back to the end."""
    import threading
    release = threading.Event()

    def reply(history):
        yield "x" * 80 + " "
        release.wait(5)
        yield "the end."
    server = chat_server(reply)
    try:
        host, port = server.server_address
        with socket.create_connection((host, port), timeout=5) as s:
            s.sendall(b"/chat\thello\r\n")
            got = b""
            while b"Reading your question" not in got or b"xxxx" not in got:
                got += s.recv(4096)
            assert b"the end." not in got
            release.set()
            while not got.endswith(b".\r\n"):
                got += s.recv(4096)
            assert b"the end." in got
    finally:
        release.set()
        server.shutdown()


def test_a_chat_answer_does_not_hold_up_knowledge_packs(library):
    import threading
    release = threading.Event()

    def reply(history):
        release.wait(10)
        yield "done"
    server = chat_server(reply)
    host, port = server.server_address
    try:
        s = socket.create_connection((host, port), timeout=5)
        s.sendall(b"/chat\thello\r\n")
        while b"Reading" not in s.recv(4096):
            pass
        assert talk(server, "/list/everyday").startswith("iEveryday Reference")
    finally:
        release.set()
        s.close()
        server.shutdown()


def test_a_second_chat_says_busy_instead_of_hanging(library, monkeypatch):
    import threading
    monkeypatch.setattr(gopher, "BUSY_WAIT", 0.2)
    release = threading.Event()

    def reply(history):
        release.wait(10)
        yield "done"
    server = chat_server(reply)
    host, port = server.server_address
    try:
        s = socket.create_connection((host, port), timeout=5)
        s.sendall(b"/chat\tfirst\r\n")
        while b"Reading" not in s.recv(4096):
            pass
        assert "still answering" in talk(server, "/chat\tsecond")
    finally:
        release.set()
        s.close()
        server.shutdown()


def test_a_client_that_leaves_takes_its_question_with_it():
    seen = []

    def reply(history):
        seen.append([m["content"] for m in history])
        yield "An answer.\n"

    chat = gopher.Chat(reply)
    sent = []

    def leaves_at_the_answer(text):
        if "An answer" in text:
            raise BrokenPipeError
        sent.append(text)

    with pytest.raises(OSError):
        chat.answer("", "first", leaves_at_the_answer, 7070)
    key = next(iter(chat.sessions))
    assert chat.sessions[key] == []
    chat.answer(key, "second", sent.append, 7070)
    assert seen[-1] == ["second"]
    assert chat.lane.acquire(blocking=False)


def test_chat_with_no_model_says_why_and_stays_usable(library):
    def reply(history):
        raise RuntimeError("The chat models on this computer need more memory than its 2048 MiB.")
    server = chat_server(reply)
    try:
        out = talk(server, "/chat\thello")
        assert "need more memory" in out and out.endswith(".\r\n")
        assert "gave no answer" not in out
    finally:
        server.shutdown()


def test_chat_with_an_empty_reply_says_so_and_forgets_the_question(library):
    seen = []

    def reply(history):
        seen.append(list(history))
        return iter([])
    server = chat_server(reply)
    try:
        first = talk(server, "/chat\thello")
        assert "gave no answer" in first
        talk(server, items(first)[0][1] + "\tagain")
        assert [m["content"] for m in seen[1]] == ["again"]
    finally:
        server.shutdown()


def test_a_client_that_leaves_stops_the_model(library):
    import threading
    closed = threading.Event()

    def reply(history):
        try:
            while True:
                yield "word " * 30
                time.sleep(0.01)
        finally:
            closed.set()
    server = chat_server(reply)
    host, port = server.server_address
    try:
        s = socket.create_connection((host, port), timeout=5)
        s.sendall(b"/chat\thello\r\n")
        while b"word" not in s.recv(4096):
            pass
        s.close()
        assert closed.wait(10), "the model kept generating for nobody"
    finally:
        server.shutdown()


def test_line_wrap_keeps_lines_short_and_loses_nothing():
    wrap = gopher.LineWrap(10)
    lines = wrap.feed("uno dos tres cuatro\ncinco ") + wrap.feed("seis") + wrap.tail()
    assert all(len(l) <= 10 for l in lines)
    assert " ".join(lines).split() == "uno dos tres cuatro cinco seis".split()
    assert gopher.LineWrap(5).feed("a" * 12) == ["aaaaa", "aaaaa"]


def _silent_model(cancelled):
    """A reply that says nothing until it is cancelled, as a model reading a prompt."""
    class Silent:
        def __iter__(self):
            if not cancelled.wait(20):
                raise AssertionError("nobody cancelled the silent model")
            raise ConnectionAbortedError("cancelled")
            yield ""

        def cancel(self):
            cancelled.set()
    return Silent()


def test_a_client_that_leaves_during_the_silence_cancels_the_model(library):
    """Nothing is being written while the model reads, so no write can fail."""
    import threading
    cancelled = threading.Event()
    server = chat_server(lambda history: _silent_model(cancelled))
    chat = server.menus.chat
    host, port = server.server_address
    try:
        s = socket.create_connection((host, port), timeout=5)
        s.sendall(b"/chat\thello\r\n")
        got = b""
        while b"Reading your question" not in got:
            got += s.recv(4096)
        s.close()
        assert cancelled.wait(5), "the model kept reading for nobody"
        assert chat.lane.acquire(timeout=5), "the next question would have to wait"
        chat.lane.release()
        assert next(iter(chat.sessions.values())) == []
    finally:
        cancelled.set()
        server.shutdown()


def test_a_client_that_stays_is_not_cancelled_and_a_model_failure_is_told(library):
    """An OSError from the model is not the client leaving: it hears why, can ask
    again, and the half answer stays out of the conversation."""
    seen = []

    def reply(history):
        seen.append([m["content"] for m in history])
        yield "Half an "
        if len(seen) == 1:
            raise OSError("the model went away")
        yield "answer.\n"
    server = chat_server(reply)
    try:
        first = talk(server, "/chat\tfirst")
        assert "Half an" in first and "stopped before it finished" in first and first.endswith(".\r\n")
        key = items(first)[0][1]
        second = talk(server, f"{key}\tsecond")
        assert "Half an answer." in second
        assert seen[-1] == ["second"]
    finally:
        server.shutdown()
