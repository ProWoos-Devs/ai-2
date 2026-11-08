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
and the conversation is kept here, saved for this account, and named in the selector
of the next item.
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
import time

from . import doc
from .chatterm import ContextFull, fit_start
from .i18n import tr

PORT = 7071                 # 70 needs root; this is the one AI-2 uses by default
MAX_SELECTOR = 4096         # a client that sends more is not asking a question (a chat line can be a paragraph)
MAX_HITS = 5
KNOWLEDGE_HITS = 3          # distinct topics from a search across the Knowledge Packs
WRAP = 70                   # Gopher menus are read in 80-column clients
TIMEOUT = 10.0              # a client that opens a socket and says nothing
WORKERS = 1                 # see Server: one question at a time by default
BUSY_WAIT = 20.0            # how long a waiting request holds on before saying busy
CHAT_SELECTOR = "/chat"
CHATS_SELECTOR = "/chats"
KNOWLEDGE_SELECTOR = "/knowledge"
KNOWLEDGE_SEARCH = "/knowledge/search"
CHAT_SESSIONS = 8           # conversations kept; the oldest is forgotten first
CHAT_BUDGET = 4096          # characters of a conversation sent to the model, for a 2048-token context
CHAT_SHOWN = 100            # exchanges a conversation shows on its page
CHAT_STATUS = "/chat-status"   # marks a line about this answer, not part of the conversation
LOOPBACK = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
LOCAL_NAMES = ("127.0.0.1", "::1", "localhost")
CRLF = "\r\n"


def line(kind: str, display: str, selector: str = "", host: str = "(NULL)", port: int = 0) -> str:
    """One menu line. Tabs are the field separator, so they cannot appear in
    the parts; a display name that contains one would split the line."""
    clean = lambda s: str(s).replace("\t", " ").replace("\r", " ").replace("\n", " ")   # noqa: E731
    return f"{kind}{clean(display)}\t{clean(selector)}\t{clean(host)}\t{port}{CRLF}"


def info(display: str = "") -> str:
    return line("i", display)


def offers_chat(port: int = PORT, timeout: float = 5.0) -> bool:
    """Is an AI-2 server with its chat item answering on this computer? A port
    that is merely open could be anything, so this reads the first menu."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(CRLF.encode())
            reply = b""
            while len(reply) < 65536:
                piece = sock.recv(4096)
                if not piece:
                    break
                reply += piece
    except OSError:
        return False
    return f"\t{CHAT_SELECTOR}\t".encode() in reply


def chat_url(port: int = PORT) -> str:
    """The chat page, which asks for nothing until a question is typed."""
    return f"gopher://127.0.0.1:{port}/7{CHAT_SELECTOR}"


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
    caller's, the same ones `ai-2 chat` uses. `store` keeps finished exchanges on
    disk, and `budget` is how many characters of a conversation fit the model."""

    def __init__(self, reply, store=None, budget: int = CHAT_BUDGET):
        self.reply = reply
        self.store = store
        self.budget = budget
        self.sessions: collections.OrderedDict[str, list[dict]] = collections.OrderedDict()
        self.starts: dict[str, int] = {}   # where the model's part of each conversation begins
        self.lane = threading.Lock()

    def _remember(self, key: str, history: list[dict]) -> list[dict]:
        self.sessions[key] = history
        self.sessions.move_to_end(key)
        while len(self.sessions) > CHAT_SESSIONS:      # out of memory only: the file stays
            forgotten, _ = self.sessions.popitem(last=False)
            self.starts.pop(forgotten, None)
        return history

    def _known(self, wanted: str | None) -> list[dict] | None:
        if wanted in self.sessions:
            return self.sessions[wanted]
        saved = self.store.load(wanted) if self.store and wanted else None
        if saved is None:
            return None
        # Reopened, the model has read none of it: the recent part only, or a
        # long conversation would take many minutes to answer.
        self.starts[wanted] = fit_start(saved, 0, self.budget // 2)
        return self._remember(wanted, saved)

    def _session(self, wanted: str | None) -> tuple[str, list[dict]]:
        history = self._known(wanted)
        if history is not None:
            return wanted, self._remember(wanted, history)
        key = secrets.token_hex(8)
        return key, self._remember(key, [])

    @staticmethod
    def _asked(question: str) -> str:
        return "".join(info(f"> {text}") for text in textwrap.wrap(question, width=WRAP)) + info()

    def _shown(self, history: list[dict]) -> str:
        out = []
        for m in history[-2 * CHAT_SHOWN:]:
            if m["role"] == "user":
                out.append(self._asked(m["content"]))
            else:
                wrap = LineWrap()
                out.extend(info(text) for text in wrap.feed(m["content"]) + wrap.tail())
                out.append(info())
        return "".join(out)

    def page(self, wanted: str | None, port: int) -> str:
        """The conversation so far, with nothing asked of the model: what a
        client shows before a question, and it may be the first thing it asks."""
        history = self._known(wanted)
        key = wanted if history else None
        if not history:
            return (info(tr("Type your question. Nothing you write leaves this computer.")) + info()
                    + self._items(None, port) + "." + CRLF)
        return self._shown(history) + self._items(key, port) + "." + CRLF

    def _items(self, key: str | None, port: int) -> str:
        if key is None:
            out = line("7", tr("Chat with the AI"), CHAT_SELECTOR, "127.0.0.1", port)
        else:
            out = (line("7", tr("Ask the next question"), f"{CHAT_SELECTOR}/{key}", "127.0.0.1", port)
                   + line("7", tr("Start a new conversation"), CHAT_SELECTOR, "127.0.0.1", port))
        out += line("1", tr("Search Knowledge Packs"), KNOWLEDGE_SELECTOR, "127.0.0.1", port)
        if self.store and self.store.keys():
            out += line("1", tr("Earlier conversations"), CHATS_SELECTOR, "127.0.0.1", port)
        if self.store and key and key in self.store.keys():
            out += line("1", tr("Delete this conversation"), f"{CHATS_SELECTOR}/forget/{key}", "127.0.0.1", port)
        return out

    def conversations(self, port: int, note: str = "") -> str:
        """The saved conversations, as an ordinary menu."""
        out = [info(note), info()] if note else []
        saved = self.store.listing() if self.store else []
        if saved:
            out += [info(tr("Earlier conversations")), info()]
        else:
            out += [info(tr("No saved conversations.")), info()]
        for c in saved:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(c["updated"]))
            first = " ".join(c["first"].split())
            first = first if len(first) <= 60 else first[:59] + "…"
            out.append(line("7", f"{when}  {first}", f"{CHAT_SELECTOR}/{c['key']}", "127.0.0.1", port))
        out.append(info())
        out.append(line("7", tr("Start a new conversation"), CHAT_SELECTOR, "127.0.0.1", port))
        if saved:
            out.append(line("1", tr("Delete all conversations"), f"{CHATS_SELECTOR}/forget/all", "127.0.0.1", port))
        return "".join(out) + "." + CRLF

    def forget(self, which: str, sure: bool, port: int) -> str:
        """Asks first: an address must not delete anything by being opened once."""
        everything = which == "all"
        if not self.store or (not everything and which not in self.store.keys()):
            return self.conversations(port)
        if not sure:
            question = tr("Delete all conversations?") if everything else tr("Delete this conversation?")
            return (info(question) + info()
                    + line("1", tr("Yes, delete"), f"{CHATS_SELECTOR}/forget/{which}/yes", "127.0.0.1", port)
                    + line("1", tr("No, keep them") if everything else tr("No, keep it"), CHATS_SELECTOR, "127.0.0.1", port) + "." + CRLF)
        if not self.lane.acquire(timeout=BUSY_WAIT):
            return error(tr("The AI is still answering another question, try again in a moment"))
        try:
            for key in self.store.keys() if everything else [which]:
                self.store.delete(key)
                self.sessions.pop(key, None)
                self.starts.pop(key, None)
        finally:
            self.lane.release()
        return self.conversations(port, tr("Deleted."))

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
            out(self.page(wanted, port))
            return
        if not self.lane.acquire(timeout=BUSY_WAIT):
            out(error(tr("The AI is still answering another question, try again in a moment")))
            return
        try:
            key, history = self._session(wanted)
            # the conversation first, in one piece: a client draws each write it gets
            out(self._shown(history) + self._asked(question))
            # before the model is asked: it says nothing until it has read everything
            out(line("i", tr("Processing ..."), CHAT_STATUS))
            out(line("i", "", CHAT_STATUS))
            history.append({"role": "user", "content": question})
            self.starts[key] = fit_start(history, self.starts.get(key, 0), self.budget)
            parts: list[str] = []
            wrap = LineWrap()
            pieces = None
            broke = False
            told = False
            while True:
                try:
                    pieces = self.reply(list(history[self.starts[key]:]))
                    if watch is not None:
                        watch.attach(pieces)
                    for piece in pieces:
                        parts.append(piece)
                        for text in wrap.feed(piece):
                            out(info(text))
                    for text in wrap.tail():
                        out(info(text))
                except ContextFull:
                    pieces = None
                    if self.starts[key] < len(history) - 1:     # all but this question, once
                        self.starts[key] = len(history) - 1
                        continue
                    told = True
                    out(info(tr("This is too long for this model. Try a shorter question.")))
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
                break
            if broke:
                history.pop()              # half an answer must not poison the conversation
                for text in wrap.tail():
                    out(info(text))
                out(info())
                out(info(tr("The AI stopped before it finished. Try asking again.")))
            elif "".join(parts).strip():
                history.append({"role": "assistant", "content": "".join(parts)})
                if self.store:
                    self.store.save(key, history)
            else:
                history.pop()              # no answer must not poison the conversation
                if pieces is not None and not told:
                    out(info(tr("The AI gave no answer to this. Try asking in other words.")))
            out(info())
            out(self._items(key if history else None, port) + "." + CRLF)
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

    def knowledge_packs(self) -> list[tuple[str, dict]]:
        """Only what has a Knowledge Pack manifest, imported ones included. A
        person's own collection is not one, even under --all."""
        return [(name, manifest) for name, manifest in self.collections() if manifest is not None]

    def title(self, name: str, manifest: dict | None) -> str:
        return str((manifest or {}).get("title") or name)

    def store(self, name: str):
        if not doc.valid_collection(name) or name not in {n for n, _ in self.collections()}:
            return None
        return doc.open_store(doc.read_index_path(name))


class Menus:
    """Builds every response. Kept apart from the socket handling so the
    tests can ask for a menu without opening a port."""

    def __init__(self, library: Library, embed_query, host: str, port: int, chat: Chat | None = None,
                 resident=None):
        self.lib = library
        self.embed_query = embed_query
        self.host = host
        self.port = port
        self.chat = chat
        self.resident = resident           # which embedding model is loaded now, if the caller knows

    def _link_host(self, local: bool) -> str:
        """The host in a menu's links. This computer gets its own address even
        when the server advertises a name to the network: the app treats any
        other host as remote, with a short time limit and nothing kept for Back."""
        return self.host if not local or self.host in LOCAL_NAMES else "127.0.0.1"

    def root(self, local: bool = False) -> str:
        from . import __version__
        out = [info(tr("AI-2 {version} knowledge, over Gopher").format(version=__version__)), info()]
        if self.chat is not None and local:
            out.append(line("7", tr("Chat with the AI"), CHAT_SELECTOR, "127.0.0.1", self.port))
            out.append(info())
        collections = self.lib.collections()
        if not collections:
            out.append(info(tr("Nothing is installed here yet.")))
            out.append(info(tr("On the AI-2 machine:  ai-2 knowledge install ai2-help")))
            return "".join(out) + "." + CRLF
        host = self._link_host(local)
        if local and self.lib.knowledge_packs():
            out.append(line("1", tr("Search Knowledge Packs"), KNOWLEDGE_SELECTOR, host, self.port))
            out.append(info())
        for name, manifest in collections:
            title = self.lib.title(name, manifest)
            out.append(line("7", tr("Ask {title}").format(title=title), f"/search/{name}", host, self.port))
            out.append(line("1", tr("What is in {title}").format(title=title), f"/list/{name}", host, self.port))
            if manifest:
                out.append(info(f"   {manifest.get('version', '')}, {manifest.get('license', '')}"))
            out.append(info())
        out.append(info(tr("Type a question into a search item. The answer is the text itself,")))
        out.append(info(tr("from the document that holds it, with its source named.")))
        return "".join(out) + "." + CRLF

    def knowledge(self, local: bool = False) -> str:
        """The Knowledge Packs on this computer, read afresh, as an ordinary menu."""
        from . import pack
        host = self._link_host(local)
        out = [info(tr("Knowledge Packs")), info()]
        packs = self.lib.knowledge_packs()
        if not packs:
            out.append(info(tr("No Knowledge Packs are installed yet.")))
            out.append(info(tr("On the AI-2 machine:  ai-2 knowledge install ai2-help")))
            out.append(info(tr("More Knowledge Packs: {url}").format(url=pack.CATALOG_URL)))
            return "".join(out) + "." + CRLF
        out += [info(text) for text in textwrap.wrap(tr(
            "Search the installed Knowledge Packs. Results are passages from their documents, "
            "with the source named."), width=WRAP)]
        out.append(info(tr("Each search stands alone and does not use your conversation.")))
        out.append(info())
        out.append(line("7", tr("Search all installed Knowledge Packs"), KNOWLEDGE_SEARCH, host, self.port))
        out.append(info())
        for name, manifest in packs:
            title = self.lib.title(name, manifest)
            languages = manifest.get("languages")
            known = ", ".join(str(lang) for lang in languages) if isinstance(languages, list) else ""
            out.append(info(f"{title} ({known})" if known else title))
            out.append(line("7", tr("Search {title}").format(title=title), f"/search/{name}", host, self.port))
            out.append(line("1", tr("Browse the topics of {title}").format(title=title), f"/list/{name}", host, self.port))
            out.append(info())
        out.append(info(tr("More Knowledge Packs: {url}").format(url=pack.CATALOG_URL)))
        return "".join(out) + "." + CRLF

    def listing(self, name: str, local: bool = False) -> str:
        conn = self.lib.store(name)
        if conn is None:
            return error(f"No knowledge called {name!r} here")
        manifest = dict(self.lib.collections()).get(name)
        out = [info(self.lib.title(name, manifest)), info()]
        for d in doc.list_documents(conn):
            out.append(line("0", f"{d['name']}  ({d['words']} words)", f"/doc/{name}/{d['name']}",
                            self._link_host(local), self.port))
        out.append(info())
        out.append(line("7", tr("Ask this one a question"), f"/search/{name}", self._link_host(local), self.port))
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
            out += textwrap.wrap(tr("Source: {url}").format(url=url), width=WRAP)
        out += textwrap.wrap(tr("From the Knowledge Pack {title} ({license}), version {version}.").format(
            title=self.lib.title(name, manifest),
            license=manifest.get("license", tr("license not stated")),
            version=manifest.get("version", "")), width=WRAP)
        if manifest.get("attribution"):
            out += textwrap.wrap(str(manifest["attribution"]), width=WRAP)
        return out

    def _results(self, query: str, hits: list[dict], stores: dict, again: str, local: bool,
                 titled: bool, omitted: list[str] | None = None) -> str:
        """A page of passages. The order is the search's; the source of each
        result is its own, and the terms of each Knowledge Pack appear once."""
        from . import pack
        host = self._link_host(local)
        manifests = dict(self.lib.collections())
        out = [info(tr("Closest passages")), info(query), info()]
        out += [info(text) for text in textwrap.wrap(
            tr("These are the passages closest to your question. A passage may not answer it."), width=WRAP)]
        if omitted:
            out += [info(text) for text in textwrap.wrap(
                tr("Not searched this time: {names}").format(names=", ".join(omitted)), width=WRAP)]
        out.append(info())
        if not hits:
            out += [info(tr("No passages were returned.")), info()]
        for i, hit in enumerate(hits, 1):
            name = hit["collection"]
            manifest = manifests.get(name)
            label = f"{self.lib.title(name, manifest)}: {doc.cite(hit)}" if titled else doc.cite(hit)
            out += [info(text) for text in textwrap.wrap(f"[{i}] {label}", width=WRAP)]
            for wrapped in textwrap.wrap(doc.finish_sentence(stores[name], hit), width=WRAP):
                out.append(info(f"    {wrapped}"))
            url = pack.source_url(manifest, hit["doc"])
            if url:
                out.append(info("    " + tr("source: {url}").format(url=url)))
            out.append(line("0", "    " + tr("Read the complete topic"), f"/doc/{name}/{hit['doc']}", host, self.port))
            out.append(info())
        for name in dict.fromkeys(hit["collection"] for hit in hits):
            out += [info(text) for text in self.provenance(name, manifests.get(name))]
        out.append(info())
        out.append(line("7", tr("Search again"), again, host, self.port))
        out.append(line("1", tr("Knowledge Packs"), KNOWLEDGE_SELECTOR, host, self.port))
        return "".join(out) + "." + CRLF

    def search_all(self, query: str, local: bool = False) -> str:
        """One question across every installed Knowledge Pack. Asks only the
        embedding server: this never reaches a chat model."""
        query = query.strip()
        if not query:
            return error(tr("Type a question"))
        titles = {name: self.lib.title(name, manifest) for name, manifest in self.lib.knowledge_packs()}
        stores = {name: doc.open_store(doc.read_index_path(name)) for name in titles}
        try:
            models = {name: doc.store_model(conn) for name, conn in stores.items()}
            usable = {name: model for name, model in models.items() if model and doc.list_documents(stores[name])}
            if not usable:
                return self.knowledge(local)
            groups = doc.group_by_model(usable)
            # The model already loaded goes first, which saves loading it again.
            # What is shown does not depend on it: see per_group below.
            loaded = self.resident() if self.resident else None
            found, reason = {}, ""
            for model_id in sorted(groups, key=lambda model: model != loaded):
                try:
                    vector = self.embed_query(model_id, query)
                except Exception as exc:               # the embedding server, not the client
                    reason = str(exc)
                    continue
                found[model_id] = doc.closest_documents({name: stores[name] for name in groups[model_id]},
                                                        vector, top=KNOWLEDGE_HITS)
            per_group = [found[model_id] for model_id in groups if model_id in found]
            omitted = [titles[name] for model_id in groups if model_id not in found for name in groups[model_id]]
            if not per_group:
                return (line("3", tr("Search is unavailable right now ({reason})").format(reason=reason))
                        + line("1", tr("Knowledge Packs"), KNOWLEDGE_SELECTOR, self._link_host(local), self.port)
                        + "." + CRLF)
            hits = doc.interleave(per_group)[:KNOWLEDGE_HITS]
            return self._results(query, hits, stores, KNOWLEDGE_SEARCH, local, titled=True, omitted=omitted)
        finally:
            for conn in stores.values():
                conn.close()

    def search(self, name: str, query: str, local: bool = False) -> str:
        conn = self.lib.store(name)
        if conn is None:
            return error(f"No knowledge called {name!r} here")
        query = query.strip()
        if not query:
            return error(tr("Type a question"))
        model_id = doc.store_model(conn)
        try:
            vector = self.embed_query(model_id, query)
        except Exception as exc:                       # the embedding server, not the client
            return error(tr("Cannot answer right now ({reason})").format(reason=exc))
        hits = doc.search(conn, vector, top=MAX_HITS)
        if not hits:
            return error(tr("Nothing here matches that"))
        for hit in hits:
            hit["collection"] = name
        return self._results(query, hits, {name: conn}, f"/search/{name}", local, titled=False)

    def respond(self, request: str, local: bool = False) -> str:
        """The whole protocol except chat, which Handler writes as it comes: a
        selector, optionally a tab and a query."""
        selector, _, query = request.partition("\t")
        selector = selector.strip()
        if selector in ("", "/"):
            return self.root(local)
        parts = [p for p in selector.split("/") if p]
        if parts == ["knowledge"]:
            return self.knowledge(local)
        if parts == ["knowledge", "search"]:
            return self.search_all(query, local)
        if len(parts) == 2 and parts[0] == "list":
            return self.listing(parts[1], local)
        if len(parts) == 2 and parts[0] == "search":
            return self.search(parts[1], query, local)
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
            body = error(tr("Busy answering another question, try again in a moment"))
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
                port = self.server.menus.port
                if selector == CHATS_SELECTOR or selector.startswith(CHATS_SELECTOR + "/"):
                    send(self._conversations(chat, selector, port))
                    return
                wanted = selector[len(CHAT_SELECTOR) + 1:] or None
                watch = ClientWatch(self.connection)
                chat.answer(wanted, query, send, port, watch)
        except OSError:
            pass                           # the client left; nothing more to say to it
        finally:
            if watch is not None:
                watch.stop()


    @staticmethod
    def _conversations(chat, selector: str, port: int) -> str:
        parts = [p for p in selector.split("/") if p]
        if len(parts) >= 3 and parts[1] == "forget":
            return chat.forget(parts[2], parts[3:] == ["yes"], port)
        return chat.conversations(port)


def is_chat(selector: str) -> bool:
    return any(selector == s or selector.startswith(s + "/") for s in (CHAT_SELECTOR, CHATS_SELECTOR))


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
          advertise: str | None = None, workers: int = WORKERS, chat_reply=None,
          chat_store=None, chat_budget: int = CHAT_BUDGET, resident=None):
    """A running Gopher server. `embed_query(model_id, text)` returns the
    vector for a question, which is what turns a search item into an answer;
    `advertise` is the host name put into the menu lines the client follows;
    `workers` is how many questions may be answered at once; `chat_reply` turns
    on the chat item, see Chat; `resident()` names the embedding model loaded now."""
    menus = Menus(Library(everything), embed_query, advertise or host, port,
                  Chat(chat_reply, chat_store, chat_budget) if chat_reply else None, resident)
    workers = max(1, int(workers))
    if workers == 1:
        server = Sequential((host, port), Handler)
        server.gate = None
    else:
        server = Threaded((host, port), Handler)
        server.gate = threading.BoundedSemaphore(workers)
    server.menus = menus
    return server
