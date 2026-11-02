"""`ai-2 gopher`: serve this computer's Knowledge Packs over Gopher (RFC 1436).

Why Gopher. The protocol's search item (type 7) is exactly the shape of
`ai-2 doc search`: the client sends a selector and a query, the server sends
back a menu. So an old machine holding the Knowledge Packs can answer questions for
every other machine in the house, over a protocol that costs nothing in
bandwidth and that clients exist for on anything with a network stack. No AI-2
code is needed on the asking side.

What is served. By default only Knowledge Packs, because a pack is published
material; a person's own indexed documents are exposed only with --all. The
menu offers, per collection, a search item and a list of its documents; a
document comes back as plain text with its parts joined.

Chat. The Gopher app is how AI-2's chat is meant to be used (Rafael, 2026-11-02):
no browser and no separate chat screen. A chat item is a search item whose reply
is written line by line as the model produces it, so words appear as they come,
and the conversation is kept here and named in the selector of the next item.
It answers only this computer. Gopher has no passwords or encryption, so a peer
on the network is refused even with --host 0.0.0.0, where it can still read the
Knowledge Packs.
"""

from __future__ import annotations

import collections
import secrets
import select
import socket
import socketserver
import textwrap
import threading

from . import doc
from .i18n import tr

PORT = 7071                 # 70 needs root; this is the one AI-2 uses by default
MAX_SELECTOR = 4096         # a client that sends more is not asking a question (a chat line can be a paragraph)
MAX_HITS = 5
WRAP = 70                   # Gopher menus are read in 80-column clients
TIMEOUT = 10.0              # a client that opens a socket and says nothing
WORKERS = 1                 # see Server: one question at a time by default
BUSY_WAIT = 20.0            # how long a waiting request holds on before saying busy
CHAT_SELECTOR = "/chat"
CHAT_SESSIONS = 8           # conversations kept; the oldest is forgotten first
CHAT_HISTORY = 8            # messages sent to the model, out of a small context
LOOPBACK = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
CRLF = "\r\n"


def line(kind: str, display: str, selector: str = "", host: str = "(NULL)", port: int = 0) -> str:
    """One menu line. Tabs are the field separator, so they cannot appear in
    the parts; a display name that contains one would split the line."""
    clean = lambda s: str(s).replace("\t", " ").replace("\r", " ").replace("\n", " ")   # noqa: E731
    return f"{kind}{clean(display)}\t{clean(selector)}\t{clean(host)}\t{port}{CRLF}"


def info(display: str = "") -> str:
    return line("i", display)


def error(message: str) -> str:
    return line("3", message) + "." + CRLF


def text_page(body: str) -> str:
    """A text response: the text, then a lone dot. A line that is just a dot
    has to be doubled or it would end the response early."""
    out = []
    for raw in body.splitlines():
        out.append(".." + CRLF if raw.strip() == "." else raw + CRLF)
    return "".join(out) + "." + CRLF


def join_parts(parts: list[str], max_overlap: int = 40) -> str:
    """The document's text from its parts, at the width a Gopher client reads.
    The joining itself lives in `doc.join_parts`, shared with the search
    window's "read more of this one"."""
    return doc.join_parts(parts, max_overlap=max_overlap, width=WRAP)


class LineWrap:
    """Turns a stream of model pieces into whole lines of at most `width`."""

    def __init__(self, width: int = WRAP):
        self.width = width
        self.buf = ""

    def feed(self, piece: str) -> list[str]:
        self.buf += piece
        out = []
        while True:
            newline = self.buf.find("\n")
            if 0 <= newline <= self.width:
                out.append(self.buf[:newline].rstrip())
                self.buf = self.buf[newline + 1:]
            elif len(self.buf) > self.width:
                cut = self.buf.rfind(" ", 0, self.width + 1)
                cut = cut if cut > 0 else self.width
                out.append(self.buf[:cut].rstrip())
                self.buf = self.buf[cut:].lstrip(" ")
            else:
                return out

    def tail(self) -> list[str]:
        rest, self.buf = self.buf.strip(), ""
        return [rest] if rest else []


class ClientWatch:
    """Notices a client that leaves while the model is still silent, when there
    is nothing to write that would fail, and cancels the reply it was waiting
    for. A client that closes its sending side but keeps reading looks the same
    from here; the Gopher clients in use do not do that."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.left = threading.Event()
        self.done = threading.Event()
        self.lock = threading.Lock()
        self.reply = None
        threading.Thread(target=self._watch, daemon=True).start()

    def attach(self, reply) -> None:
        with self.lock:
            self.reply = reply
            if self.left.is_set():
                self._cancel()

    def stop(self) -> None:
        self.done.set()

    def _cancel(self) -> None:
        if hasattr(self.reply, "cancel"):
            self.reply.cancel()

    def _watch(self) -> None:
        while not self.done.is_set():
            try:
                ready, _, _ = select.select([self.sock], [], [], 0.25)
                if not ready or self.sock.recv(1024, socket.MSG_DONTWAIT):
                    continue
            except BlockingIOError:
                continue
            except (OSError, ValueError):
                pass
            with self.lock:
                self.left.set()
                self._cancel()
            return


class Chat:
    """The conversations, and one answer at a time. `reply(history)` returns an
    iterator of text pieces and raises RuntimeError with a sentence for the
    person when no model can start. The model and its system prompt are the
    caller's, the same ones `ai-2 chat` uses."""

    def __init__(self, reply):
        self.reply = reply
        self.sessions: collections.OrderedDict[str, list[dict]] = collections.OrderedDict()
        self.lane = threading.Lock()

    def _session(self, wanted: str | None) -> tuple[str, list[dict]]:
        key = wanted if wanted in self.sessions else secrets.token_hex(8)
        history = self.sessions.setdefault(key, [])
        self.sessions.move_to_end(key)
        while len(self.sessions) > CHAT_SESSIONS:
            self.sessions.popitem(last=False)
        return key, history

    def answer(self, wanted: str | None, question: str, write, port: int,
               watch: ClientWatch | None = None) -> None:
        """Write the whole Gopher reply through `write`, a line at a time. An
        OSError from it means the client left, and ends the answer, and so does
        `watch` noticing the same while the model says nothing. An OSError from
        the model is not the client's doing: the client is told."""
        wrote_to_nobody = []

        def out(text: str) -> None:
            try:
                write(text)
            except OSError:
                wrote_to_nobody.append(True)
                raise

        question = question.strip()
        if not question:
            out(error(tr("Type a question")))
            return
        if not self.lane.acquire(timeout=BUSY_WAIT):
            out(error(tr("The AI is still answering another question, try again in a moment")))
            return
        try:
            key, history = self._session(wanted)
            for text in textwrap.wrap(question, width=WRAP):
                out(info(f"> {text}"))
            out(info())
            # before the model is asked: it says nothing until it has read everything
            out(info(tr("Reading your question. On a slow computer this can take a minute or more.")))
            out(info())
            history.append({"role": "user", "content": question})
            del history[:-CHAT_HISTORY]
            parts: list[str] = []
            wrap = LineWrap()
            pieces = None
            broke = False
            try:
                pieces = self.reply(list(history))
                if watch is not None:
                    watch.attach(pieces)
                for piece in pieces:
                    parts.append(piece)
                    for text in wrap.feed(piece):
                        out(info(text))
                for text in wrap.tail():
                    out(info(text))
            except RuntimeError as exc:
                for text in textwrap.wrap(str(exc), width=WRAP):
                    out(info(text))
            except OSError:
                if wrote_to_nobody or (watch is not None and watch.left.is_set()):
                    history.pop()          # the client left: nobody is waiting for this one
                    raise
                broke = True
            finally:
                if hasattr(pieces, "close"):
                    pieces.close()         # a client that left stops the model too
            if broke:
                history.pop()              # half an answer must not poison the conversation
                for text in wrap.tail():
                    out(info(text))
                out(info())
                out(info(tr("The AI stopped before it finished. Try asking again.")))
            elif "".join(parts).strip():
                history.append({"role": "assistant", "content": "".join(parts)})
            else:
                history.pop()              # no answer must not poison the conversation
                if pieces is not None:
                    out(info(tr("The AI gave no answer to this. Try asking in other words.")))
            out(info())
            out(line("7", tr("Ask the next question"), f"{CHAT_SELECTOR}/{key}", "127.0.0.1", port))
            out(line("7", tr("Start a new conversation"), CHAT_SELECTOR, "127.0.0.1", port))
            out("." + CRLF)
        finally:
            self.lane.release()


class Library:
    """The collections this server offers, read fresh for every request so a
    pack installed while it runs shows up without a restart."""

    def __init__(self, everything: bool = False):
        self.everything = everything

    def collections(self) -> list[tuple[str, dict | None]]:
        from . import pack
        out = []
        for name in doc.list_collections():
            manifest = pack.manifest_of(name)
            if manifest is not None or self.everything:
                out.append((name, manifest))
        return out

    def title(self, name: str, manifest: dict | None) -> str:
        return str((manifest or {}).get("title") or name)

    def store(self, name: str):
        if not doc.valid_collection(name) or name not in {n for n, _ in self.collections()}:
            return None
        return doc.open_store(doc.read_index_path(name))


class Menus:
    """Builds every response. Kept apart from the socket handling so the
    tests can ask for a menu without opening a port."""

    def __init__(self, library: Library, embed_query, host: str, port: int, chat: Chat | None = None):
        self.lib = library
        self.embed_query = embed_query
        self.host = host
        self.port = port
        self.chat = chat

    def root(self, local: bool = False) -> str:
        from . import __version__
        out = [info(f"AI-2 {__version__} knowledge, over Gopher"), info()]
        if self.chat is not None and local:
            out.append(line("7", tr("Chat with the AI"), CHAT_SELECTOR, "127.0.0.1", self.port))
            out.append(info())
        collections = self.lib.collections()
        if not collections:
            out.append(info("Nothing is installed here yet."))
            out.append(info("On the AI-2 machine:  ai-2 knowledge install ai2-help"))
            return "".join(out) + "." + CRLF
        for name, manifest in collections:
            title = self.lib.title(name, manifest)
            out.append(line("7", f"Ask {title}", f"/search/{name}", self.host, self.port))
            out.append(line("1", f"What is in {title}", f"/list/{name}", self.host, self.port))
            if manifest:
                out.append(info(f"   {manifest.get('version', '')}, {manifest.get('license', '')}"))
            out.append(info())
        out.append(info("Type a question into a search item. The answer is the text itself,"))
        out.append(info("from the document that holds it, with its source named."))
        return "".join(out) + "." + CRLF

    def listing(self, name: str) -> str:
        conn = self.lib.store(name)
        if conn is None:
            return error(f"No knowledge called {name!r} here")
        manifest = dict(self.lib.collections()).get(name)
        out = [info(self.lib.title(name, manifest)), info()]
        for d in doc.list_documents(conn):
            out.append(line("0", f"{d['name']}  ({d['words']} words)", f"/doc/{name}/{d['name']}",
                            self.host, self.port))
        out.append(info())
        out.append(line("7", "Ask this one a question", f"/search/{name}", self.host, self.port))
        return "".join(out) + "." + CRLF

    def document(self, name: str, doc_name: str) -> str:
        conn = self.lib.store(name)
        if conn is None:
            return error(f"No knowledge called {name!r} here")
        rows = conn.execute("SELECT chunks.text FROM chunks JOIN docs ON docs.id = chunks.doc_id "
                            "WHERE docs.name = ? ORDER BY chunks.ord", (doc_name,)).fetchall()
        if not rows:
            return error(f"No document called {doc_name!r} in {name}")
        manifest = dict(self.lib.collections()).get(name)
        header = [doc_name, "=" * len(doc_name), ""]
        return text_page("\n".join(header) + join_parts([r[0] for r in rows])
                         + "\n" + "\n".join(self.provenance(name, manifest, doc_name)))

    def provenance(self, name: str, manifest: dict | None, doc_name: str | None = None) -> list[str]:
        """Where this text came from, the way `ai-2 doc search` and `doc ask`
        put it: the document's own source URL when the manifest has one, then
        the pack with its licence, then the attribution the licence asks for."""
        from . import pack
        if not manifest:
            return [""]
        out = [""]
        url = pack.source_url(manifest, doc_name) if doc_name else None
        if url:
            out += textwrap.wrap(f"Source: {url}", width=WRAP)
        out += textwrap.wrap(f"From the pack {self.lib.title(name, manifest)} "
                             f"({manifest.get('license', 'licence not stated')}), "
                             f"version {manifest.get('version', '')}.", width=WRAP)
        if manifest.get("attribution"):
            out += textwrap.wrap(str(manifest["attribution"]), width=WRAP)
        return out

    def search(self, name: str, query: str) -> str:
        conn = self.lib.store(name)
        if conn is None:
            return error(f"No knowledge called {name!r} here")
        query = query.strip()
        if not query:
            return error("Type a question")
        model_id = doc.store_model(conn)
        try:
            vector = self.embed_query(model_id, query)
        except Exception as exc:                       # the embedding server, not the client
            return error(f"Cannot answer right now ({exc})")
        hits = doc.search(conn, vector, top=MAX_HITS)
        if not hits:
            return error("Nothing here matches that")
        manifest = dict(self.lib.collections()).get(name)
        out = [info(f"{query}"), info()]
        from . import pack
        for i, hit in enumerate(hits, 1):
            out.append(info(f"[{i}] {doc.cite(hit)}"))
            for wrapped in textwrap.wrap(hit["text"], width=WRAP):
                out.append(info(f"    {wrapped}"))
            url = pack.source_url(manifest, hit["doc"])
            if url:
                out.append(info(f"    source: {url}"))
            out.append(line("0", f"    the whole of {hit['doc']}", f"/doc/{name}/{hit['doc']}",
                            self.host, self.port))
            out.append(info())
        for wrapped in self.provenance(name, manifest):
            out.append(info(wrapped))
        return "".join(out) + "." + CRLF

    def respond(self, request: str, local: bool = False) -> str:
        """The whole protocol except chat, which Handler writes as it comes: a
        selector, optionally a tab and a query."""
        selector, _, query = request.partition("\t")
        selector = selector.strip()
        if selector in ("", "/"):
            return self.root(local)
        parts = [p for p in selector.split("/") if p]
        if len(parts) == 2 and parts[0] == "list":
            return self.listing(parts[1])
        if len(parts) == 2 and parts[0] == "search":
            return self.search(parts[1], query)
        if len(parts) >= 3 and parts[0] == "doc":
            return self.document(parts[1], "/".join(parts[2:]))
        return error(f"Nothing here called {selector!r}")


class Handler(socketserver.StreamRequestHandler):
    timeout = TIMEOUT

    def handle(self):
        try:
            raw = self.rfile.readline(MAX_SELECTOR + 2)
        except (socket.timeout, OSError):
            return
        request = raw.decode("utf-8", "replace").rstrip("\r\n")
        local = self.client_address[0] in LOOPBACK
        selector, _, query = request.partition("\t")
        selector = selector.strip()
        if is_chat(selector):
            self._chat(selector, query, local)
            return
        gate = getattr(self.server, "gate", None)
        held = gate.acquire(timeout=BUSY_WAIT) if gate is not None else True
        if not held:
            body = error("Busy answering another question, try again in a moment")
        else:
            try:
                body = self.server.menus.respond(request, local)
            except Exception as exc:                    # one bad request must not end the server
                body = error(f"Something went wrong ({exc})")
            finally:
                if gate is not None:
                    gate.release()
        try:
            self.wfile.write(body.encode("utf-8", "replace"))
        except OSError:
            pass


    def _chat(self, selector: str, query: str, local: bool) -> None:
        chat = self.server.menus.chat
        send = lambda text: self.wfile.write(text.encode("utf-8", "replace"))   # noqa: E731
        watch = None
        try:
            if chat is None:
                send(error("Chat is not available on this server"))
            elif not local:
                send(error("Chat answers only on the computer it runs on"))
            else:
                wanted = selector[len(CHAT_SELECTOR) + 1:] or None
                watch = ClientWatch(self.connection)
                chat.answer(wanted, query, send, self.server.menus.port, watch)
        except OSError:
            pass                           # the client left; nothing more to say to it
        finally:
            if watch is not None:
                watch.stop()


def is_chat(selector: str) -> bool:
    return selector == CHAT_SELECTOR or selector.startswith(CHAT_SELECTOR + "/")


class Sequential(socketserver.TCPServer):
    """One question at a time. A search embeds the question and then scans
    every vector in the collection in plain Python, which on the machines AI-2
    is built for is seconds of one of its two cores (3.8 s per 20,000 parts on
    the 2011 laptop). Threads would let one eager client on the LAN start
    several of those at once and bury the machine, so the default is to queue
    in the listen backlog instead."""
    allow_reuse_address = True
    request_queue_size = 16

    def process_request(self, request, client_address):
        """A chat answer takes minutes and must not hold up Knowledge Packs
        searches, so it runs beside the queue. Chat keeps its own one-at-a-time
        lane (Chat.lane), so this does not add load on the model."""
        if self._is_chat_request(request):
            threading.Thread(target=self._chat_thread, args=(request, client_address), daemon=True).start()
        else:
            super().process_request(request, client_address)

    @staticmethod
    def _is_chat_request(request) -> bool:
        try:
            request.settimeout(TIMEOUT)
            head = request.recv(MAX_SELECTOR, socket.MSG_PEEK)
        except OSError:
            return False
        return is_chat(head.decode("utf-8", "replace").split("\t")[0].strip())

    def _chat_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


class Threaded(socketserver.ThreadingTCPServer):
    """More than one worker, when the machine can afford it. `gate` bounds how
    many requests do real work at a time; the rest wait, and say so rather
    than hanging, if the wait runs long."""
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 16


def serve(embed_query, host: str = "127.0.0.1", port: int = PORT, everything: bool = False,
          advertise: str | None = None, workers: int = WORKERS, chat_reply=None):
    """A running Gopher server. `embed_query(model_id, text)` returns the
    vector for a question, which is what turns a search item into an answer;
    `advertise` is the host name put into the menu lines the client follows;
    `workers` is how many questions may be answered at once; `chat_reply` turns
    on the chat item, see Chat."""
    menus = Menus(Library(everything), embed_query, advertise or host, port,
                  Chat(chat_reply) if chat_reply else None)
    workers = max(1, int(workers))
    if workers == 1:
        server = Sequential((host, port), Handler)
        server.gate = None
    else:
        server = Threaded((host, port), Handler)
        server.gate = threading.BoundedSemaphore(workers)
    server.menus = menus
    return server
