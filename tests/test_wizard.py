"""The setup wizard flow, driven with canned answers and stubbed engine calls
(no hardware, no root, no network)."""
import os

import pytest

from ai2 import wizard as wz
from ai2.detect import Hardware


class FakeBackend:
    name = "runit"

    def is_enabled(self, service):
        return False

    def enable_cmd(self, service):
        return ["fake-enable", service]

    def disable_cmd(self, service):
        return ["fake-disable", service]


class FakePkgBackend:
    name = "fakepkg"

    def is_installed(self, pkg):
        return False

    def install_cmd(self, pkgs):
        return ["fake-install", *pkgs]


HW = Hardware(cpu_model="Test CPU", ram_nominal_gib=4, ram_mib=3800, logical_cores=2,
              init_system="runit", flags={"sse4_1", "sse4_2"}, root_disk_rotational=True)

SCORE = {"ai_score": 30, "tg_tps": 2.0, "pp_tps": 8.0, "bench_model": "m", "threads": 2,
         "capabilities": {k: 1 for k in wz.STAR_LABELS}, "cpu_variant": "noavx",
         "bench_params_b": 0.5, "recommended_model": "qwen2.5-0.5b", "remote_suggested": True}
REC = {"local": {"id": "qwen2.5-0.5b", "label": "Qwen2.5 0.5B Instruct", "params_b": 0.5,
                 "quant": "Q4_K_M", "file": "Qwen2.5-0.5B-Instruct-Q4_K_M.gguf", "file_mb": 380},
       "remote_suggested": True, "reason": "test"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A sandbox: user config dir in tmp, engine calls stubbed, recorder for
    what the wizard did."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("AI2_MODEL_DIR", str(tmp_path / "models"))
    calls = []
    monkeypatch.setattr(wz, "detect", lambda: HW)
    monkeypatch.setattr(wz, "get_service_backend", lambda init: FakeBackend())
    monkeypatch.setattr(wz, "get_package_backend", lambda: FakePkgBackend())
    monkeypatch.setattr(wz, "find_runtime", lambda variant: "/fake/runtime")
    monkeypatch.setattr(wz, "find_benchmark_model", lambda: str(tmp_path / "models" / "bench.gguf"))
    monkeypatch.setattr(wz, "best_present_model", lambda cat, ram=None: None)
    monkeypatch.setattr(wz, "find_model_file", lambda f: None)
    monkeypatch.setattr(wz, "have_internet", lambda *a, **k: True)
    monkeypatch.setattr(wz, "measure", lambda hw, m, r, t=None: (calls.append("measure") or (SCORE, REC)))

    def fake_download(model, dest, progress=None):
        calls.append(("download", model["id"]))
        return os.path.join(dest, model["file"])
    monkeypatch.setattr(wz, "download_model", fake_download)
    return {"calls": calls, "tmp": tmp_path}


def run(env, answers=None, yes=False):
    said = []
    answers = list(answers or [])

    def ask(q, default):
        return answers.pop(0) if answers else default

    def runner(cmd):
        env["calls"].append(("run", cmd))
        return 0
    w = wz.Wizard(ask=ask, say=said.append, run=runner, yes=yes)
    rc = w.go()
    return rc, w, "\n".join(said)


def test_full_run_with_defaults(env):
    rc, w, out = run(env, yes=True)
    assert rc == 0 and w.report["completed"]
    # tuning went through sudo ai-2 init --apply (we are not root in tests)
    assert any(c[0] == "run" and c[1][:2] == ["sudo", "ai-2"] for c in env["calls"])
    assert "measure" in env["calls"]
    assert ("download", "qwen2.5-0.5b") in env["calls"]   # the recommended model
    assert "AI Score   30 / 100" in out
    assert "ai-2 chat" in out
    from ai2.state import setup_done_path
    assert os.path.exists(setup_done_path())


def test_score_persisted_for_user(env):
    from ai2.state import load_score
    run(env, yes=True)
    assert load_score()["ai_score"] == 30


def test_decline_tuning_and_download(env):
    # answers: apply tuning? no; download recommended? no
    rc, w, out = run(env, answers=[False, False])
    assert rc == 0 and w.report["tuned"] is False
    assert not any(c[0] == "run" for c in env["calls"])
    assert not any(c[0] == "download" for c in env["calls"])
    assert "sudo ai-2 init --apply" in out


def test_no_engine_stops_early_and_offers_to_come_back(env, monkeypatch):
    monkeypatch.setattr(wz, "find_runtime", lambda variant: None)
    # answers: apply tuning? yes; install engine? no; show again at login? no
    rc, w, out = run(env, answers=[True, False, False])
    assert rc == 1 and not w.report["completed"]
    assert "runtime install" in out
    from ai2.state import setup_done_path
    assert os.path.exists(setup_done_path())   # user said: don't show again


def test_offline_no_bench_model_defers_score(env, monkeypatch):
    # No network and the benchmark model is not on disk: tune + engine happen,
    # the score is deferred, and the wizard offers to come back.
    monkeypatch.setattr(wz, "find_benchmark_model", lambda: None)
    monkeypatch.setattr(wz, "have_internet", lambda *a, **k: False)
    rc, w, out = run(env, yes=True)
    assert rc == 1 and "No internet" in out
    assert "measure" not in env["calls"]
    assert "Almost ready" in out and "AI Score" in out and "ai-2 chat" in out
    assert w.report["pending"] == ["score"] and w.report["stopped_at"] == 4
    assert os.path.exists(os.path.join(env["tmp"], "state", "ai2", "wizard.log"))


def test_offline_bundled_model_lets_you_chat_now(env, monkeypatch):
    # No network but a model is already on disk (bundled on the ISO): the
    # wizard says you can chat now and defers the score.
    monkeypatch.setattr(wz, "find_benchmark_model", lambda: None)
    monkeypatch.setattr(wz, "have_internet", lambda *a, **k: False)
    monkeypatch.setattr(wz, "best_present_model",
                        lambda cat, ram=None: {"id": "gemma3-270m", "label": "Gemma 3 270M Instruct",
                                               "params_b": 0.27})
    rc, w, out = run(env, yes=True)
    assert rc == 1
    assert "start straight away: Gemma 3 270M" in out and "You can already chat" in out
    # the starter model's limits are named plainly...
    assert "starter model" in out and "facts and simple math wrong" in out
    # ...and the RAM-based offer lists bigger fitting models with pull commands
    assert "4 GB RAM" in out and "ai-2 model pull qwen2.5-0.5b" in out
    assert "ai-2 model pull gemma3-1b" in out
    assert w.report["pending"] == ["score"] and w.report["model"] == "gemma3-270m"


def test_second_run_summarizes_the_first(env):
    run(env, yes=True)
    rc, w, out = run(env, yes=True)
    assert rc == 0
    assert "Last run" in out and "completed" in out and "AI Score 30" in out


def test_have_internet_rejects_captive_portal(monkeypatch):
    import urllib.request

    class Resp:
        url = "http://portal.example/login"
        def __enter__(self): return self
        def __exit__(self, *a): pass
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Resp())
    assert wz.have_internet("https://huggingface.co") is False
    Resp.url = "https://huggingface.co/"
    assert wz.have_internet("https://huggingface.co") is True


def test_downloads_test_model_when_missing(env, monkeypatch):
    rc, w, out = run(env, yes=True)
    assert rc == 0
    ids = [c[1] for c in env["calls"] if c[0] == "download"]
    assert ids[0] == wz.benchmark_model()["id"]


def test_format_score_has_bar_and_stars():
    out = wz.format_score(SCORE)
    assert "[###.......]" in out and "★☆☆☆☆  Chat" in out


def test_failed_download_leaves_the_score_pending(env, monkeypatch):
    """Online, but the benchmark download dies (network drop, checksum, disk
    full): the wizard must not declare itself done and write the marker."""
    from ai2.state import setup_done_path
    monkeypatch.setattr(wz, "find_benchmark_model", lambda: None)

    def failing_download(model, dest, progress=None):
        raise RuntimeError("download incomplete")
    monkeypatch.setattr(wz, "download_model", failing_download)
    rc, w, out = run(env, yes=True)
    assert "score" in w.report["pending"]
    assert not w.report.get("completed")
    assert "Download failed" in out
    assert rc == 1
