import http.server
import os
import threading

import pytest

from ai2 import runtime
from ai2.detect import Hardware
from ai2.tiers import load_tiers, resolve_config
from ai2.tuning import build_plan
from tests.test_tuning import FakeBackend, FakePkgBackend


def test_runtime_package_is_the_same_for_every_cpu_class():
    for v in ("baseline", "noavx", "avx2"):
        assert runtime.runtime_package(v) == "ai2-llama-cpp"
    assert runtime.runtime_package("weird") is None
    assert runtime.OLD_RUNTIME_PACKAGES["noavx"] == "ai2-llama-cpp-noavx"


def test_find_runtime_prefers_the_one_package_dir_then_the_old_per_cpu_dir(tmp_path, monkeypatch):
    new = tmp_path / "llama.cpp"; old = tmp_path / "llama.cpp-noavx"
    for d in (new, old):
        d.mkdir(); (d / "llama-bench").write_text("")
    monkeypatch.setattr(runtime, "RUNTIME_DIR", str(new))
    monkeypatch.setattr(runtime, "_runtime_candidates",
                        lambda v: [str(new), str(tmp_path / f"llama.cpp-{v}")])
    assert runtime.find_runtime("noavx") == str(new)
    (new / "llama-bench").unlink()
    assert runtime.find_runtime("noavx") == str(old)         # a machine that has not swapped yet
    assert runtime.find_runtime("avx2") is None


def test_loaded_backend_is_read_from_ggml_log():
    log = ("ggml_backend_load_best: ...\n"
           "load_backend: loaded CPU backend from /usr/lib/ai2/runtimes/llama.cpp/libggml-cpu-haswell.so\n"
           "build: 10398 (8e7f22b67)\n")
    assert runtime.loaded_backends(log) == {"CPU": "libggml-cpu-haswell.so"}
    assert runtime.cpu_variant_loaded(log) == "haswell"
    assert runtime.cpu_variant_loaded("load_backend: loaded CPU backend from /x/libggml-cpu.so\n") == "static"
    assert runtime.cpu_variant_loaded("nothing here") is None
    assert runtime.cpu_variant_loaded("") is None


def test_plan_installs_runtime_for_cpu_variant_not_tier():
    tiers = load_tiers()
    tier = tiers["light"]
    # A Light-tier machine (4 GB) with a pre-SSE4.1 CPU must get the baseline package.
    hw = Hardware(ram_nominal_gib=4, logical_cores=2, init_system="runit", flags=set())
    plan = build_plan(hw, tier, resolve_config(tier, tiers), FakeBackend(), FakePkgBackend())
    cmds = [c for a in plan for c in a.commands]
    assert ["fake-install", "ai2-llama-cpp"] in cmds


def test_plan_skips_runtime_when_installed():
    class Installed(FakePkgBackend):
        def is_installed(self, pkg):
            return True
    tiers = load_tiers()
    tier = tiers["light"]
    hw = Hardware(ram_nominal_gib=4, logical_cores=2, init_system="runit", flags=set())
    plan = build_plan(hw, tier, resolve_config(tier, tiers), FakeBackend(), Installed())
    assert not any("ai2-llama-cpp" in " ".join(c) for a in plan for c in a.commands)


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass


@pytest.fixture
def served_dir(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "m.gguf").write_bytes(b"x" * 100_000)
    httpd = http.server.HTTPServer(("127.0.0.1", 0),
                                   lambda *a, **k: _Handler(*a, directory=str(src), **k))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_port}", src
    httpd.shutdown()


def test_download_model_verifies_size_and_uses_part_file(tmp_path, served_dir, monkeypatch):
    url, _ = served_dir
    monkeypatch.setattr(runtime, "hf_url", lambda m: f"{url}/m.gguf")
    model = {"id": "t", "file": "m.gguf", "repo": "x/y", "file_mb": 0}
    seen = []
    dest = tmp_path / "models"
    path = runtime.download_model(model, str(dest), progress=lambda d, t: seen.append((d, t)))
    assert path == str(dest / "m.gguf")
    assert os.path.getsize(path) == 100_000
    assert seen[-1] == (100_000, 100_000)
    assert not (dest / "m.gguf.part").exists()
    # second call is a no-op
    assert runtime.download_model(model, str(dest)) == path


def test_download_model_rejects_truncated(tmp_path, served_dir, monkeypatch):
    url, _ = served_dir

    class Resp:
        headers = {"Content-Length": "200000"}
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, n):
            data = getattr(self, "_d", b"y" * 100_000)
            self._d = b""
            return data
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Resp())
    model = {"id": "t", "file": "m.gguf", "repo": "x/y", "file_mb": 0}
    dest = tmp_path / "models"
    with pytest.raises(RuntimeError, match="resume"):
        runtime.download_model(model, str(dest))
    assert not (dest / "m.gguf").exists()
    assert (dest / "m.gguf.part").exists()      # kept, so the next attempt resumes


def test_model_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("AI2_MODEL_DIR", str(tmp_path))
    assert runtime.model_dir() == str(tmp_path)


# --- resume + checksum (2026-08-21 review items 2 and 3) ---------------------

class _RangeHandler(http.server.BaseHTTPRequestHandler):
    """Serves one file with Range support, like Hugging Face's CDN."""
    data = b""
    ignore_range = False

    def do_GET(self):
        start = 0
        rng = self.headers.get("Range")
        if rng and not self.ignore_range:
            start = int(rng.split("=")[1].split("-")[0])
            if start >= len(self.data):
                self.send_response(416); self.end_headers(); return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(self.data)-1}/{len(self.data)}")
        else:
            self.send_response(200)
        body = self.data[start:]
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def range_server():
    import hashlib
    payload = bytes(range(256)) * 400          # 102400 bytes
    handler = type("H", (_RangeHandler,), {"data": payload, "ignore_range": False})
    httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/m.gguf", payload, hashlib.sha256(payload).hexdigest(), handler
    httpd.shutdown()


def test_download_resumes_partial_file(tmp_path, range_server, monkeypatch):
    url, payload, sha, _ = range_server
    monkeypatch.setattr(runtime, "hf_url", lambda m: url)
    dest = tmp_path / "models"; dest.mkdir()
    (dest / "m.gguf.part").write_bytes(payload[:30000])     # interrupted earlier
    seen = []
    model = {"id": "t", "file": "m.gguf", "repo": "x/y", "file_mb": 0, "sha256": sha}
    path = runtime.download_model(model, str(dest), progress=lambda d, t: seen.append((d, t)))
    assert (dest / "m.gguf").read_bytes() == payload
    assert seen[0][0] >= 30000 and seen[-1] == (len(payload), len(payload))   # continued, not restarted
    assert not os.path.exists(path + ".part")


def test_download_restarts_when_server_ignores_range(tmp_path, range_server, monkeypatch):
    url, payload, sha, handler = range_server
    handler.ignore_range = True
    monkeypatch.setattr(runtime, "hf_url", lambda m: url)
    dest = tmp_path / "models"; dest.mkdir()
    (dest / "m.gguf.part").write_bytes(b"garbage" * 1000)
    model = {"id": "t", "file": "m.gguf", "repo": "x/y", "file_mb": 0, "sha256": sha}
    runtime.download_model(model, str(dest))
    assert (dest / "m.gguf").read_bytes() == payload


def test_download_rejects_bad_checksum(tmp_path, range_server, monkeypatch):
    url, payload, sha, _ = range_server
    monkeypatch.setattr(runtime, "hf_url", lambda m: url)
    dest = tmp_path / "models"
    model = {"id": "t", "file": "m.gguf", "repo": "x/y", "file_mb": 0, "sha256": "0" * 64}
    with pytest.raises(RuntimeError, match="checksum"):
        runtime.download_model(model, str(dest))
    assert not (dest / "m.gguf").exists() and not (dest / "m.gguf.part").exists()


def test_catalog_entries_carry_checksums():
    from ai2.models import load_catalog
    for m in load_catalog():
        assert len(m.get("sha256", "")) == 64, m["id"]
        assert m.get("verified"), m["id"]


def test_download_preflight_reports_full_disk(tmp_path, monkeypatch):
    from ai2 import sysinfo
    monkeypatch.setattr(sysinfo, "free_disk_mb", lambda p: 100)
    model = {"id": "t", "file": "m.gguf", "file_mb": 4470}
    msg = runtime.download_preflight(model, str(tmp_path))
    assert msg and "4470 MB needed" in msg
    monkeypatch.setattr(sysinfo, "free_disk_mb", lambda p: 10_000)
    assert runtime.download_preflight(model, str(tmp_path)) is None


def test_mem_available_parses_meminfo(tmp_path):
    from ai2.sysinfo import mem_available_mib
    f = tmp_path / "meminfo"
    f.write_text("MemTotal:  3462000 kB\nMemFree:  100000 kB\nMemAvailable:  2048000 kB\n")
    assert mem_available_mib(str(f)) == 2000


def test_the_user_model_dir_follows_xdg_data_home(monkeypatch, tmp_path):
    """A scratch run that redirects XDG_DATA_HOME must not download models
    into the real home (85 MB landed there on 2026-09-18). AI2_MODEL_DIR
    still wins, and /var/lib/ai2 still wins for root."""
    monkeypatch.delenv("AI2_MODEL_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(runtime.os, "access", lambda p, mode: False)
    monkeypatch.setattr(runtime.os, "geteuid", lambda: 1000)
    assert runtime.model_dir() == str(tmp_path / "data" / "ai2" / "models")
    assert str(tmp_path / "data" / "ai2" / "models") in runtime._model_dirs()
    monkeypatch.setenv("AI2_MODEL_DIR", str(tmp_path / "elsewhere"))
    assert runtime.model_dir() == str(tmp_path / "elsewhere")
    monkeypatch.delenv("XDG_DATA_HOME")
    monkeypatch.delenv("AI2_MODEL_DIR")
    assert runtime.model_dir() == os.path.expanduser("~/.local/share/ai2/models")
