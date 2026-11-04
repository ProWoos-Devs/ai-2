"""The model's reading of AI-2's instructions, kept on disk (ai2/warmstart.py)."""

import urllib.error

from ai2 import warmstart


class Server:
    def __init__(self, slots):
        self.slots = iter(slots)
        self.calls = []

    def __call__(self, path, body, timeout):
        self.calls.append(path)
        if path == "/slots":
            return next(self.slots)
        return {}


def warm(tmp_path, server, name="m-abc.bin"):
    w = warmstart.WarmStart("http://x", str(tmp_path), name, "instructions", call=server, sleep=lambda s: None)
    return w


def test_a_saved_start_is_restored_and_nothing_is_made(tmp_path):
    (tmp_path / "m-abc.bin").write_bytes(b"x")
    server = Server([[{"is_processing": False}]])
    warm(tmp_path, server).run()
    assert server.calls == ["/slots", "/slots/0?action=restore"]


def test_a_saved_start_the_server_refuses_is_removed(tmp_path):
    (tmp_path / "m-abc.bin").write_bytes(b"x")

    def server(path, body, timeout):
        if "restore" in path:
            raise urllib.error.HTTPError(path, 400, "no", {}, None)
        return []
    warm(tmp_path, server).run()
    assert not (tmp_path / "m-abc.bin").exists()


def test_it_is_made_only_after_real_use_and_a_quiet_moment(tmp_path, monkeypatch):
    idle, busy = [{"is_processing": False}], [{"is_processing": True}]
    (tmp_path / "m-old.bin").write_bytes(b"old")
    (tmp_path / "other-old.bin").write_bytes(b"other")
    server = Server([idle, idle, busy, idle, idle, idle])
    w = warm(tmp_path, server)
    ticks = iter([0, 10, 40, 41])
    w.clock = lambda: next(ticks)
    w.run()
    assert server.calls[-2:] == ["/v1/chat/completions", "/slots/0?action=save"]
    assert server.calls.count("/slots") == 5
    assert not (tmp_path / "m-old.bin").exists()         # this model's older file
    assert (tmp_path / "other-old.bin").exists()         # another model's stays


def test_a_failure_only_means_reading_as_always(tmp_path, capsys):
    polls = iter([[], [{"is_processing": True}]])

    def server(path, body, timeout):
        if path == "/slots":
            return next(polls, [])
        raise OSError("no")
    w = warm(tmp_path, server)
    w.clock = iter(range(0, 10000, 100)).__next__
    w.run()
    assert "was not used" in capsys.readouterr().out


def test_the_name_changes_with_whatever_makes_an_old_file_wrong(tmp_path):
    binary = tmp_path / "llama-server"
    binary.write_bytes(b"1")
    one = warmstart.file_name("m", "/a/m.gguf", "s", 2048, 32, str(binary))
    assert one.startswith("m-") and one == warmstart.file_name("m", "/b/m.gguf", "s", 2048, 32, str(binary))
    assert one != warmstart.file_name("m", "/a/m.gguf", "other", 2048, 32, str(binary))
    assert one != warmstart.file_name("m", "/a/m.gguf", "s", 1024, 32, str(binary))
    binary.write_bytes(b"22")
    assert one != warmstart.file_name("m", "/a/m.gguf", "s", 2048, 32, str(binary))


def test_the_folder_exists_before_the_server_starts(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    path = warmstart.state_dir()
    assert path.endswith("/") and (tmp_path / "ai2" / "prompt-state").is_dir()


def test_a_folder_that_cannot_be_made_means_no_saved_start(tmp_path, monkeypatch):
    (tmp_path / "ai2").write_text("a file in the way")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert warmstart.state_dir() is None
