"""The terminal chat client: SSE parsing, history handling, and one
end-to-end run against a real HTTP server speaking the chat-completions
stream format (stdlib http.server, no network beyond localhost)."""
import http.server
import json
import threading

from ai2 import chatterm


def test_sse_events_stop_at_done():
    stream = [b"data: one\n", b"\n", b"data: two\n", b"data: [DONE]\n", b"data: after\n"]
    assert list(chatterm.sse_events(iter(stream))) == ["one", "two"]


def test_delta_text():
    ok = json.dumps({"choices": [{"delta": {"content": "hi"}}]})
    empty = json.dumps({"choices": [{"delta": {}}]})
    assert chatterm.delta_text(ok) == "hi"
    assert chatterm.delta_text(empty) == ""
    assert chatterm.delta_text("not json") == ""


def _run_repl(inputs, stream):
    """Drive repl() with scripted input; return (exit code, said lines)."""
    it = iter(inputs)

    def ask(prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    said = []

    def say(text="", **kwargs):
        said.append(text)

    rc = chatterm.repl("http://x/", stream=stream, ask=ask, say=say)
    return rc, said


def test_repl_history_and_new():
    seen = []

    def stream(url, messages):
        seen.append([dict(m) for m in messages])
        yield "ok"

    rc, said = _run_repl(["hello", "again", "/new", "fresh"], stream)
    assert rc == 0
    # history grows across turns and resets at /new
    assert [len(m) for m in seen] == [1, 3, 1]
    assert seen[1][1]["role"] == "assistant" and seen[1][1]["content"] == "ok"
    assert seen[2] == [{"role": "user", "content": "fresh"}]


def test_repl_aborted_answer_leaves_history_clean():
    calls = []

    def stream(url, messages):
        calls.append(len(messages))
        if len(calls) == 1:
            raise KeyboardInterrupt   # user hit Ctrl-C before any token
        yield "answer"

    rc, _ = _run_repl(["one", "two"], stream)
    assert rc == 0
    # the aborted question was removed, so turn 2 starts a 1-message history
    assert calls == [1, 1]


class _SSEHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert body["stream"] is True and body["messages"]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for piece in ("Hel", "lo"):
            chunk = json.dumps({"choices": [{"delta": {"content": piece}}]})
            self.wfile.write(f"data: {chunk}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, *args):
        pass


def test_stream_reply_against_real_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), _SSEHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        got = "".join(chatterm.stream_reply(url, [{"role": "user", "content": "hi"}]))
        assert got == "Hello"
    finally:
        server.shutdown()


def test_repl_opens_every_conversation_with_the_system_message():
    seen = []

    def stream(url, messages):
        seen.append([dict(m) for m in messages])
        yield "ok"

    it = iter(["hello", "/new", "again"])

    def ask(prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    rc = chatterm.repl("http://x/", stream=stream, ask=ask, say=lambda *a, **k: None,
                       system="You are the assistant of AI-2.")
    assert rc == 0
    assert [m["role"] for m in seen[0]] == ["system", "user"]
    assert seen[0][0]["content"] == "You are the assistant of AI-2."
    assert [m["role"] for m in seen[1]] == ["system", "user"]   # /new keeps the persona
