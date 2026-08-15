import http.server
import os
import threading

import pytest

from ai2 import runtime
from ai2.detect import Hardware
from ai2.tiers import load_tiers, resolve_config
from ai2.tuning import build_plan
from tests.test_tuning import FakeBackend, FakePkgBackend


def test_runtime_package_per_variant():
    assert runtime.runtime_package("baseline") == "ai2-llama-cpp-baseline"
    assert runtime.runtime_package("noavx") == "ai2-llama-cpp-noavx"
    assert runtime.runtime_package("avx2") == "ai2-llama-cpp-avx2"
    assert runtime.runtime_package("weird") is None


def test_plan_installs_runtime_for_cpu_variant_not_tier():
    tiers = load_tiers()
    tier = tiers["light"]
    # A Light-tier machine (4 GB) with a pre-SSE4.1 CPU must get the baseline package.
    hw = Hardware(ram_nominal_gib=4, logical_cores=2, init_system="runit", flags=set())
    plan = build_plan(hw, tier, resolve_config(tier, tiers), FakeBackend(), FakePkgBackend())
    cmds = [c for a in plan for c in a.commands]
    assert ["fake-install", "ai2-llama-cpp-baseline"] in cmds
    assert not any("ai2-llama-cpp-avx2" in c for c in cmds)


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
    with pytest.raises(RuntimeError):
        runtime.download_model(model, str(dest))
    assert not (dest / "m.gguf").exists()
    assert not (dest / "m.gguf.part").exists()


def test_model_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("AI2_MODEL_DIR", str(tmp_path))
    assert runtime.model_dir() == str(tmp_path)
