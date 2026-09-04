"""The terminal chat: the same local AI, no browser around it. The lightest
client the project can have (stdlib only, a few MB next to the model), the
fastest to appear, and it works over SSH, so it is the recommended way to
chat on low-end machines. The server side is unchanged (`ai-2 serve`): the
browser page and this REPL are two views of the same thing, and the server
still exits by itself when idle."""

from __future__ import annotations

import json
import urllib.request

from .i18n import tr

READ_TIMEOUT_S = 600   # between stream chunks; worst measured machines do ~0.5 tok/s


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
                 model: str | None = None):
    """POST the conversation, yield the reply as it generates. Sampling is
    left to the server's own defaults (the tier/model set them). `headers`
    and `model` are for a remote endpoint (API key, the model it must use)."""
    payload = {"messages": messages, "stream": True}
    if model:
        payload["model"] = model
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", data=body,
                                 headers=dict(headers or {"Content-Type": "application/json"}))
    with urllib.request.urlopen(req, timeout=READ_TIMEOUT_S) as resp:
        for payload in sse_events(resp):
            piece = delta_text(payload)
            if piece:
                yield piece


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
         streaming: bool = False, speak=None, system: str | None = None) -> int:
    """Chat until Ctrl-C/Ctrl-D. Ctrl-C during an answer only stops that
    answer. Sentence-per-line output is the default (readable by screen
    readers, locally and over SSH); `streaming=True` restores token-by-token
    output. `speak` is a callable given each output line (spoken chat).
    `system` is sent as the system message that opens every conversation.
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
        parts: list[str] = []

        def collected():
            for piece in stream(url, messages):
                parts.append(piece)
                yield piece

        try:
            if streaming:
                for piece in collected():
                    say(piece, end="", flush=True)
                say("")
            else:
                for sentence in sentences(collected()):
                    out(sentence)
        except KeyboardInterrupt:
            say("")
        except OSError as exc:
            out(tr("The server went away ({exc}). It may have stopped after idling; run  ai-2 chat --terminal  again.")
                .format(exc=exc))
            return 1
        if parts:
            messages.append({"role": "assistant", "content": "".join(parts)})
        else:
            messages.pop()   # an aborted answer must not poison the history
