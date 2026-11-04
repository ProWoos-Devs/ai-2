"""`ai-2 gopher`: the protocol itself, spoken over a real socket."""
import socket
import socketserver
import threading
import time

import pytest
import yaml

from ai2 import chatstore, doc, gopher


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
        assert "From the Knowledge Pack Everyday Reference (CC0-1.0), version" in out
        assert "Facts from Wikidata." in out
        page = talk(server, "/doc/everyday/spain.txt")
        assert "Source: https://example.org/spain" in page
        assert "From the Knowledge Pack Everyday Reference (CC0-1.0), version" in page
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
        assert "i> quien eres" in first and "Processing" in first
        assert "iHola, soy la IA." in first and "iSegunda linea." in first and first.endswith(".\r\n")
        next_item, new_item = items(first)
        assert next_item[1].startswith("/chat/") and new_item[1] == "/chat"
        talk(server, f"{next_item[1]}\ty ahora")
        assert [m["content"] for m in seen[1]] == ["quien eres", "Hola, soy la IA.\nSegunda linea.", "y ahora"]
        talk(server, "/chat\totra cosa")
        assert [m["content"] for m in seen[2]] == ["otra cosa"]      # a new conversation
    finally:
        server.shutdown()


def test_the_page_holds_the_whole_conversation(library):
    answers = iter(["First answer.", "Second answer."])
    server = chat_server(lambda h: iter([next(answers)]))
    try:
        first = talk(server, "/chat\tone")
        key = items(first)[0][1]
        second = talk(server, f"{key}\ttwo")
        order = [second.index(t) for t in ("i> one", "iFirst answer.", "i> two", "iSecond answer.")]
        assert order == sorted(order)
        # how the last answer started is not part of the conversation, so a client can drop it
        assert second.count("Processing") == 1
        assert f"Processing ...\t{gopher.CHAT_STATUS}\t" in second
        page = talk(server, key)
        assert "i> two" in page and "iSecond answer." in page and "Processing" not in page
    finally:
        server.shutdown()


def test_the_chat_page_opens_empty_without_asking_the_model(library):
    server = chat_server(lambda h: pytest.fail("the model must not be asked"))
    try:
        page = talk(server, "/chat")
        assert "Type your question" in page and page.endswith(".\r\n")
        assert [i[1] for i in items(page)] == ["/chat"]
        assert talk(server, "/chat/nobody") == page       # a conversation the server no longer has
        assert not server.menus.chat.sessions
    finally:
        server.shutdown()


def test_a_cancelled_question_stays_off_the_page():
    def reply(history):
        yield "An answer.\n"
    chat = gopher.Chat(reply)

    def leaves(text):
        if "An answer" in text:
            raise BrokenPipeError
    with pytest.raises(OSError):
        chat.answer("", "first", leaves, 7070)
    key = next(iter(chat.sessions))
    sent = []
    chat.answer(key, "second", sent.append, 7070)
    assert "first" not in "".join(sent)


def test_a_conversation_page_has_a_limit():
    chat = gopher.Chat(lambda h: iter(["Yes."]))
    sent = []
    chat.answer("", "0", sent.append, 7070)
    key = next(iter(chat.sessions))
    for n in range(1, gopher.CHAT_SHOWN + 3):
        chat.answer(key, str(n), sent.append, 7070)
    page = chat.page(key, 7070)
    assert page.count("iYes.") == gopher.CHAT_SHOWN and "i> 0\t" not in page


def test_the_model_gets_the_recent_part_only_when_it_outgrows_the_budget():
    seen = []

    def reply(history):
        seen.append([m["content"] for m in history])
        return iter(["b" * 40])
    chat = gopher.Chat(reply, budget=200)
    sent = []
    chat.answer("", "a" * 40, sent.append, 7070)
    key = next(iter(chat.sessions))
    for n in range(4):
        chat.answer(key, "a" * 40, sent.append, 7070)
    assert [len(s) for s in seen] == [1, 3, 5, 1, 3]       # a large cut, then it stays put again
    assert all(s[0].startswith("a") for s in seen)         # it opens with a question
    assert len(chat.sessions[key]) == 10                   # the page keeps everything


def test_a_conversation_too_long_for_the_model_is_retried_with_the_question_alone():
    seen = []

    def reply(history):
        seen.append(len(history))
        if len(history) > 1:
            raise gopher.ContextFull("more than the model can hold")
        return iter(["Fine."])
    chat = gopher.Chat(reply)
    sent = []
    chat.answer("", "one", sent.append, 7070)
    key = next(iter(chat.sessions))
    chat.answer(key, "two", sent.append, 7070)
    assert seen == [1, 3, 1] and "iFine." in "".join(sent)


def test_a_question_too_long_by_itself_says_so_and_stays_usable():
    def reply(history):
        raise gopher.ContextFull("more than the model can hold")
    chat = gopher.Chat(reply)
    sent = []
    chat.answer("", "far too long", sent.append, 7070)
    page = "".join(sent)
    assert "too long for this model" in page and "gave no answer" not in page and page.endswith(".\r\n")
    assert chat.lane.acquire(blocking=False)


def saved_chat(tmp_path, answer="An answer."):
    store = chatstore.Store(str(tmp_path / "chats"))
    return gopher.Chat(lambda h: iter([answer]), store), store


def test_a_conversation_survives_the_server(tmp_path):
    chat, store = saved_chat(tmp_path)
    sent = []
    chat.answer("", "Me llamo Ana", sent.append, 7070)
    key = next(iter(chat.sessions))
    again = gopher.Chat(lambda h: iter(["Otra."]), store)
    page = again.page(key, 7070)
    assert "i> Me llamo Ana" in page and "iAn answer." in page and f"/chat/{key}" in page
    sent = []
    again.answer(key, "Y ahora", sent.append, 7070)
    assert [m["content"] for m in store.load(key)] == ["Me llamo Ana", "An answer.", "Y ahora", "Otra."]


def test_a_reopened_conversation_gives_the_model_the_recent_part(tmp_path):
    chat, store = saved_chat(tmp_path, "b" * 100)
    sent = []
    chat.answer("", "a" * 100, sent.append, 7070)
    key = next(iter(chat.sessions))
    for _ in range(9):
        chat.answer(key, "a" * 100, sent.append, 7070)
    seen = []
    again = gopher.Chat(lambda h: seen.append(len(h)) or iter(["c"]), store, budget=1000)
    again.answer(key, "next", sent.append, 7070)
    assert 1 < seen[0] < 10


def test_a_question_that_was_not_answered_is_not_saved(tmp_path):
    store = chatstore.Store(str(tmp_path / "chats"))
    chat = gopher.Chat(lambda h: iter([]), store)
    chat.answer("", "hello", [].append, 7070)
    assert store.keys() == []


def test_earlier_conversations_is_a_menu_that_reopens_them(tmp_path):
    chat, store = saved_chat(tmp_path)
    sent = []
    chat.answer("", "Primera pregunta", sent.append, 7070)
    key = next(iter(chat.sessions))
    assert f"1Earlier conversations\t{gopher.CHATS_SELECTOR}\t" in "".join(sent)
    menu = chat.conversations(7070)
    assert f"Primera pregunta\t/chat/{key}\t127.0.0.1\t7070" in menu
    assert menu.endswith(".\r\n")


def test_nothing_is_deleted_without_saying_yes(tmp_path):
    chat, store = saved_chat(tmp_path)
    sent = []
    chat.answer("", "one", sent.append, 7070)
    key = next(iter(chat.sessions))
    page = chat.forget(key, False, 7070)
    assert store.keys() == [key] and f"/chats/forget/{key}/yes" in page
    page = chat.forget(key, True, 7070)
    assert store.keys() == [] and key not in chat.sessions and "No saved conversations" in page
    chat.answer("", "two", sent.append, 7070)
    chat.answer("", "three", sent.append, 7070)
    assert "/chats/forget/all/yes" in chat.forget("all", False, 7070) and len(store.keys()) == 2
    chat.forget("all", True, 7070)
    assert store.keys() == [] and not chat.sessions


def test_a_conversation_name_cannot_reach_outside_its_folder(tmp_path):
    chat, store = saved_chat(tmp_path)
    secret = tmp_path / "secret.json"
    secret.write_text('{"messages": []}')
    assert store.load("../secret") is None and store.delete("../secret") is False and secret.exists()
    assert "Type your question" in chat.page("../secret", 7070)


def test_conversations_answer_only_this_computer(library):
    server = chat_server(lambda h: iter(["hi"]))
    try:
        sent = []

        class Fake:
            wfile = type("W", (), {"write": staticmethod(sent.append)})()
            connection = None
            server = None
        Fake.server = server
        gopher.Handler._chat(Fake(), "/chats", "", local=False)
        assert sent[0].startswith(b"3Chat answers only on the computer")
        assert gopher.is_chat("/chats") and gopher.is_chat("/chats/forget/all/yes")
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
            while b"Processing" not in got or b"xxxx" not in got:
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
        while b"Processing" not in s.recv(4096):
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
        while b"Processing" not in s.recv(4096):
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
        while b"Processing" not in got:
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


def test_offers_chat_reads_the_menu_not_the_open_port():
    """A port that merely answers must not pass for the chat server."""
    class Other(socketserver.StreamRequestHandler):
        def handle(self):
            self.rfile.readline()
            self.wfile.write(b"iSomething else\t\t\t0\r\n.\r\n")
    other = socketserver.TCPServer(("127.0.0.1", 0), Other)
    threading.Thread(target=other.serve_forever, daemon=True).start()
    try:
        assert gopher.offers_chat(other.server_address[1]) is False
    finally:
        other.shutdown()
        other.server_close()
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    port = closed.getsockname()[1]
    closed.close()
    assert gopher.offers_chat(port, timeout=1) is False
