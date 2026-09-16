"""`ai-2 gopher`: serve this computer's knowledge packs over Gopher (RFC 1436).

Why Gopher. The protocol's search item (type 7) is exactly the shape of
`ai-2 doc search`: the client sends a selector and a query, the server sends
back a menu. So an old machine holding the packs can answer questions for
every other machine in the house, over a protocol that costs nothing in
bandwidth and that clients exist for on anything with a network stack. No AI-2
code is needed on the asking side.

What is served. By default only knowledge packs, because a pack is published
material; a person's own indexed documents are exposed only with --all. The
menu offers, per collection, a search item and a list of its documents; a
document comes back as plain text with its parts joined.

What is not served. The chat model. An answer takes minutes on the machines
AI-2 is built for, far longer than any Gopher client waits, and the passages
are the part that is reliable there anyway (knowledge packs review, 2026-09-16).
"""

from __future__ import annotations

import socket
import socketserver
import textwrap

from . import doc

PORT = 7070                 # 70 needs root; this is the one AI-2 uses by default
MAX_SELECTOR = 512          # a client that sends more is not asking a question
MAX_HITS = 5
WRAP = 70                   # Gopher menus are read in 80-column clients
TIMEOUT = 30.0
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
    """The document's text from its parts. Consecutive parts overlap by about
    twenty words (that is what keeps a sentence whole in at least one part),
    so the repeated words are trimmed at the seam rather than printed twice."""
    if not parts:
        return ""
    out = parts[0].split()
    for part in parts[1:]:
        words = part.split()
        for n in range(min(max_overlap, len(out), len(words)), 0, -1):
            if out[-n:] == words[:n]:
                words = words[n:]
                break
        out += words
    return "\n".join(textwrap.wrap(" ".join(out), width=WRAP)) or ""


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
        return doc.open_store(doc.index_path(name))


class Menus:
    """Builds every response. Kept apart from the socket handling so the
    tests can ask for a menu without opening a port."""

    def __init__(self, library: Library, embed_query, host: str, port: int):
        self.lib = library
        self.embed_query = embed_query
        self.host = host
        self.port = port

    def root(self) -> str:
        from . import __version__
        out = [info(f"AI-2 {__version__} knowledge, over Gopher"), info()]
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
        footer = [""]
        if manifest and manifest.get("attribution"):
            footer += textwrap.wrap(str(manifest["attribution"]), width=WRAP)
        return text_page("\n".join(header) + join_parts([r[0] for r in rows]) + "\n".join(footer))

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
        for i, hit in enumerate(hits, 1):
            out.append(info(f"[{i}] {doc.cite(hit)}"))
            for wrapped in textwrap.wrap(hit["text"], width=WRAP):
                out.append(info(f"    {wrapped}"))
            out.append(line("0", f"    the whole of {hit['doc']}", f"/doc/{name}/{hit['doc']}",
                            self.host, self.port))
            out.append(info())
        if manifest and manifest.get("attribution"):
            for wrapped in textwrap.wrap(f"From {self.lib.title(name, manifest)} "
                                         f"({manifest.get('license')}). {manifest['attribution']}", width=WRAP):
                out.append(info(wrapped))
        return "".join(out) + "." + CRLF

    def respond(self, request: str) -> str:
        """The whole protocol: a selector, optionally a tab and a query."""
        selector, _, query = request.partition("\t")
        selector = selector.strip()
        if selector in ("", "/"):
            return self.root()
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
        try:
            body = self.server.menus.respond(request)
        except Exception as exc:                        # one bad request must not end the server
            body = error(f"Something went wrong ({exc})")
        try:
            self.wfile.write(body.encode("utf-8", "replace"))
        except OSError:
            pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(embed_query, host: str = "127.0.0.1", port: int = PORT, everything: bool = False,
          advertise: str | None = None) -> Server:
    """A running Gopher server. `embed_query(model_id, text)` returns the
    vector for a question, which is what turns a search item into an answer;
    `advertise` is the host name put into the menu lines the client follows."""
    menus = Menus(Library(everything), embed_query, advertise or host, port)
    server = Server((host, port), Handler)
    server.menus = menus
    return server
