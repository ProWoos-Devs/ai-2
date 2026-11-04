"""The terminal chat: the same local AI, no browser around it. The lightest
client the project can have (stdlib only, a few MB next to the model), the
fastest to appear, and it works over SSH, so it is the recommended way to
chat on low-end machines. The server side is unchanged (`ai-2 serve`): the
browser page and this REPL are two views of the same thing, and the server
still exits by itself when idle."""

from __future__ import annotations

import http.client
import json
import socket
import urllib.error
import urllib.parse
import urllib.request

from .i18n import tr

READ_TIMEOUT_S = 600   # between stream chunks; worst measured machines do ~0.5 tok/s
CHARS_PER_CONTEXT_TOKEN = 2   # room for the instructions and the answer, at about 3 characters a token


class ContextFull(OSError):
    """The model refused the conversation: more than it can hold."""


def fit_start(messages: list[dict], start: int, budget: int | None) -> int:
    """Where the model's part of a conversation begins. Only when it has outgrown
    `budget` characters does that move, and then well past the minimum, so most
    questions keep what the model has already read. The newest message always
    stays, and the part sent begins with a question."""
    if not budget:
        return start
    total = sum(len(m["content"]) for m in messages[start:])
    if total <= budget:
        return start
    last = len(messages) - 1
    while start < last and (total > budget // 2 or messages[start]["role"] != "user"):
        total -= len(messages[start]["content"])
        start += 1
    return start


def _refusal(status: int, text: str) -> OSError:
    if status == 400 and "exceed_context_size" in text:
        return ContextFull("more than the model can hold")
    return OSError(f"the AI answered with an error ({status})")


def sse_events(fp):
    """Yield the data payload of each server-sent event from a byte stream,
    stopping at the [DONE] sentinel."""
    for raw in fp:
        line = raw.decode("utf-8", "replace").strip()
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            if payload == "[DONE]":
                return
            if payload:
                yield payload


def delta_text(payload: str) -> str:
    """The text carried by one chat-completions stream chunk ('' if none)."""
    try:
        chunk = json.loads(payload)
        return chunk["choices"][0]["delta"].get("content") or ""
    except (ValueError, KeyError, IndexError, TypeError):
        return ""


def stream_reply(url: str, messages: list[dict], headers: dict | None = None,
                 model: str | None = None, temperature: float | None = None):
    """POST the conversation, yield the reply as it generates. Sampling is
    left to the server's own defaults (the tier/model set them) unless
    `temperature` is given (`ai-2 doc ask` wants extraction, not creativity).
    `headers` and `model` are for a remote endpoint (API key, the model it
    must use)."""
    payload = {"messages": messages, "stream": True}
    if model:
        payload["model"] = model
    if temperature is not None:
        payload["temperature"] = temperature
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", data=body,
                                 headers=dict(headers or {"Content-Type": "application/json"}))
    try:
        resp = urllib.request.urlopen(req, timeout=READ_TIMEOUT_S)
    except urllib.error.HTTPError as exc:
        raise _refusal(exc.code, exc.read().decode("utf-8", "replace")) from exc
    with resp:
        for payload in sse_events(resp):
            piece = delta_text(payload)
            if piece:
                yield piece


class LocalReply:
    """`stream_reply` for the model on this computer, with a way out while the
    model is silent: `cancel()`, from another thread, ends the wait at once and
    drops the connection, which tells the model to stop. urllib offers no socket
    until the model has started to answer, and that can be minutes."""

    def __init__(self, url: str, messages: list[dict]):
        self.url = urllib.parse.urlsplit(url)
        self.messages = messages
        self.cancelled = False
        self.conn: http.client.HTTPConnection | None = None
        self.sock: socket.socket | None = None

    def __iter__(self):
        body = json.dumps({"messages": self.messages, "stream": True}).encode()
        self.conn = http.client.HTTPConnection(self.url.hostname, self.url.port, timeout=READ_TIMEOUT_S)
        try:
            self.conn.connect()
            self.sock = self.conn.sock
            self._check()
            self.conn.request("POST", "/v1/chat/completions", body=body,
                              headers={"Content-Type": "application/json"})
            resp = self.conn.getresponse()
            if resp.status != 200:
                raise _refusal(resp.status, resp.read().decode("utf-8", "replace"))
            last = b""

            def lines():
                nonlocal last
                for last in resp:
                    yield last
            for payload in sse_events(lines()):
                piece = delta_text(payload)
                if piece:
                    yield piece
            self._check()
            if b"[DONE]" not in last:     # a model that dies only looks like the end of the text
                raise OSError("the AI stopped before it finished")
        except http.client.HTTPException as exc:
            self._check()
            raise OSError(f"the AI stopped answering ({exc})") from exc
        except OSError:
            self._check()
            raise
        finally:
            self.close()

    def _check(self) -> None:
        if self.cancelled:
            raise ConnectionAbortedError("cancelled")

    def cancel(self) -> None:
        self.cancelled = True
        if self.sock is not None:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()


SENTENCE_ENDS = ".!?…"
FLUSH_AT = 400   # a run-on with no punctuation still flushes, at a word break


def _sentence_cut(buf: str) -> int | None:
    """Index AFTER which buf holds a complete sentence, or None to wait for
    more text. A terminator only counts when the next character is already
    known and is whitespace, so decimals (3.14) and trailing dots whose
    continuation has not arrived yet stay buffered."""
    nl = buf.find("\n")
    if nl >= 0:
        return nl + 1
    for i, ch in enumerate(buf[:-1]):
        if ch in SENTENCE_ENDS and buf[i + 1].isspace():
            return i + 1
    if len(buf) > FLUSH_AT:
        space = buf.rfind(" ", 0, FLUSH_AT)
        if space > 0:
            return space + 1
    return None


def sentences(pieces):
    """Group a token stream into whole sentences. Screen readers and TTS
    follow linewise output; token-by-token repaints are unreadable to them,
    which is why sentence mode is the default for everyone (accessibility
    plan P1.4), not something behind detection."""
    buf = ""
    for piece in pieces:
        buf += piece
        while True:
            cut = _sentence_cut(buf)
            if cut is None:
                break
            chunk, buf = buf[:cut].strip(), buf[cut:]
            if chunk:
                yield chunk
    tail = buf.strip()
    if tail:
        yield tail


def repl(url: str, stream=stream_reply, ask=input, say=print,
         streaming: bool = False, speak=None, system: str | None = None,
         budget: int | None = None) -> int:
    """Chat until Ctrl-C/Ctrl-D. Ctrl-C during an answer only stops that
    answer. Sentence-per-line output is the default (readable by screen
    readers, locally and over SSH); `streaming=True` restores token-by-token
    output. `speak` is a callable given each output line (spoken chat).
    `system` is sent as the system message that opens every conversation.
    `budget` is how many characters of conversation fit the model, see fit_start.
    `stream`, `ask`, `say` and `speak` are injectable for tests."""
    def out(text: str) -> None:
        say(text)
        if speak:
            speak(text)

    out(tr("Chat in this terminal. Enter sends, Ctrl-C or Ctrl-D leaves, /new starts a fresh conversation."))
    def fresh() -> list[dict]:
        return [{"role": "system", "content": system}] if system else []

    messages = fresh()
    while True:
        try:
            line = ask("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            say("")
            return 0
        if not line:
            continue
        if line == "/new":
            messages = fresh()
            out(tr("New conversation."))
            continue
        messages.append({"role": "user", "content": line})
        keep = 1 if system else 0
        del messages[keep:fit_start(messages, keep, budget)]
        parts: list[str] = []
        # the model says nothing until it has read everything: 54 s on the 2011
        # laptop, which looks exactly like a hang (RMM-PC, 2026-11-02). On the
        # screen only, so spoken chat does not repeat it every turn.
        say(tr("Processing ..."))

        def collected():
            for piece in stream(url, messages):
                parts.append(piece)
                yield piece

        def write_answer():
            if streaming:
                for piece in collected():
                    say(piece, end="", flush=True)
                say("")
            else:
                for sentence in sentences(collected()):
                    out(sentence)

        try:
            try:
                write_answer()
            except ContextFull:
                del messages[keep:-1]      # all but this question, once
                write_answer()
        except KeyboardInterrupt:
            say("")
        except ContextFull:
            out(tr("This is too long for this model. Try a shorter question."))
        except OSError as exc:
            out(tr("The server went away ({exc}). It may have stopped after idling; run  ai-2 chat --terminal  again.")
                .format(exc=exc))
            return 1
        if parts:
            messages.append({"role": "assistant", "content": "".join(parts)})
        else:
            messages.pop()   # an aborted answer must not poison the history
