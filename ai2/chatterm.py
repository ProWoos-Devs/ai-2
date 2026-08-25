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


def stream_reply(url: str, messages: list[dict]):
    """POST the conversation, yield the reply as it generates. Sampling is
    left to the server's own defaults (the tier/model set them)."""
    body = json.dumps({"messages": messages, "stream": True}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=READ_TIMEOUT_S) as resp:
        for payload in sse_events(resp):
            piece = delta_text(payload)
            if piece:
                yield piece


def repl(url: str, stream=stream_reply, ask=input, say=print) -> int:
    """Chat until Ctrl-C/Ctrl-D. Ctrl-C during an answer only stops that
    answer. `stream`, `ask` and `say` are injectable for tests."""
    say(tr("Chat in this terminal. Enter sends, Ctrl-C or Ctrl-D leaves, /new starts a fresh conversation."))
    messages: list[dict] = []
    while True:
        try:
            line = ask("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            say("")
            return 0
        if not line:
            continue
        if line == "/new":
            messages = []
            say(tr("New conversation."))
            continue
        messages.append({"role": "user", "content": line})
        parts: list[str] = []
        try:
            for piece in stream(url, messages):
                parts.append(piece)
                say(piece, end="", flush=True)
            say("")
        except KeyboardInterrupt:
            say("")
        except OSError as exc:
            say(tr("The server went away ({exc}). It may have stopped after idling; run  ai-2 chat --terminal  again.")
                .format(exc=exc))
            return 1
        if parts:
            messages.append({"role": "assistant", "content": "".join(parts)})
        else:
            messages.pop()   # an aborted answer must not poison the history
