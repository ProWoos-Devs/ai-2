"""Workflow profiles: the gate (tier grant + star minimums), the remote way
out, and the read-only install (models pulled, packages only printed)."""
import os

import pytest

from ai2 import cli, runner, runtime, workflows
from ai2.detect import Hardware
from ai2.models import load_catalog

LIGHT = Hardware(ram_mib=3800, ram_nominal_gib=4, logical_cores=2, flags=set())
CATALOG = load_catalog()
REC = next(m for m in CATALOG if m["id"] == "qwen2.5-0.5b")


def _score(**stars):
    caps = {c: 1 for c in ("chat", "translation", "ocr", "doc_qa", "voice")}
    caps.update({"coding": 0, "image_generation": 0, "video": 0})
    caps.update(stars)
    return {"ai_score": 23, "tg_tps": 1.34, "capabilities": caps}


def _no_pacman(cmd, **kw):
    class P:
        returncode = 1
    return P()


def _ev(profile_id, score=None, remote=None, present=lambda f: True, run=_no_pacman, hw=LIGHT):
    p = workflows.get_profile(profile_id)
    return workflows.evaluate(p, hw, score, REC, remote, lambda f: "/x" if present(f) else None, CATALOG, run=run)


def test_profiles_ship_and_resolve_the_config_tier():
    ids = [p["id"] for p in workflows.load_profiles()]
    assert ids == ["chat", "documents", "speech", "translation"]
    assert workflows.config_tier_id(LIGHT) == "light"
    big = Hardware(ram_mib=64000, ram_nominal_gib=64, logical_cores=16, flags=set())
    assert workflows.config_tier_id(big) in ("standard", "creator")   # a config_from tier maps down


def test_chat_is_ready_when_the_star_minimum_is_met(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: None)
    r = _ev("chat", _score())
    assert r["verdict"] == "ready" and r["models"] == [REC] and r["ctx"] == 2048


def test_no_score_means_unknown_and_zero_stars_means_slow_with_the_way_out(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: None)
    assert _ev("chat", None)["verdict"] == "unknown"
    r = _ev("translation", _score(translation=0))
    assert r["verdict"] == "slow" and "ai-2 remote set" in r["why"]
    r = _ev("translation", _score(translation=0), remote={"url": "http://10.0.0.5:8080", "default": True})
    assert r["verdict"] == "remote" and "10.0.0.5" in r["why"]
    # a remote that is not the default is used only when asked for
    r = _ev("translation", _score(translation=0), remote={"url": "http://10.0.0.5:8080", "default": False})
    assert r["verdict"] == "slow" and "--remote" in r["why"] and "10.0.0.5" in r["why"]


def test_documents_lists_missing_packages_and_install_plan_prints_pacman(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/pacman")
    calls = []

    def run(cmd, **kw):
        calls.append(cmd[-1])

        class P:
            returncode = 0 if cmd[-1] == "poppler" else 1
        return P()

    r = _ev("documents", _score(), run=run)
    assert r["verdict"] == "missing" and r["pkg_state"]["poppler"] is True
    assert r["missing_pkgs"] == ["tesseract", "tesseract-data-eng", "tesseract-data-spa", "tesseract-data-deu", "img2pdf"]
    models, line = workflows.install_plan(r)
    assert models == [] and line == "sudo pacman -S --needed tesseract tesseract-data-eng tesseract-data-spa tesseract-data-deu img2pdf"
    assert "tesseract" in workflows.render_info(r) and "How to use" in workflows.render_info(r)


def test_missing_model_is_in_the_plan(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: None)
    r = _ev("chat", _score(), present=lambda f: False)
    assert r["verdict"] == "missing" and workflows.install_plan(r)[0] == [REC]


def test_denied_on_a_tier_that_grants_nothing():
    p = {"id": "x", "description": "x", "requests": ["image_generation"], "minimum": {}, "remote": False,
         "tiers": {}}
    r = workflows.evaluate(p, LIGHT, _score(), REC, None, lambda f: None, CATALOG)
    assert r["verdict"] == "unavailable" and "Image" in r["why"]


def test_cli_list_info_status_install(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("AI2_MODEL_DIR", str(tmp_path / "models"))
    # Models are also looked for under the real home, whatever AI2_MODEL_DIR
    # says, so a developer machine that has an embedding model on it reported
    # the documents workflow as ready and failed this test (2026-09-18, after a
    # pack rebuild had downloaded one). The test gets a home of its own.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cli, "detect", lambda: LIGHT)
    monkeypatch.setattr(cli, "_load_score", lambda: _score())
    monkeypatch.setattr(cli, "_recommended_model", lambda hw: REC)
    monkeypatch.setattr("shutil.which", lambda n: None)
    pulled = []
    monkeypatch.setattr(runner, "_pull_model", lambda m, force=False: pulled.append(m["id"]) or 0)
    assert cli.main(["workflow"]) == 0
    out = capsys.readouterr().out
    assert "chat" in out and "needs setup" in out
    assert cli.main(["workflow", "info", "translation"]) == 0
    assert "Translate to Spanish" in capsys.readouterr().out
    assert cli.main(["workflow", "install", "translation"]) == 0
    out = capsys.readouterr().out
    assert pulled == ["qwen2.5-0.5b"] and "How to use it" in out
    assert cli.main(["workflow", "info", "nope"]) == 1
    assert cli.main(["workflow", "status"]) == 0
    assert "none yet" in capsys.readouterr().out


# --- speech: whisper's own dependencies, no chat model and no AI Score ---------

TINY = Hardware(ram_mib=1900, ram_nominal_gib=2, logical_cores=2, flags=set())
BIG = Hardware(ram_mib=31000, ram_nominal_gib=32, logical_cores=16, flags=set())


def _speech(monkeypatch, engine=True, **kw):
    from ai2 import speech
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/pacman")
    monkeypatch.setattr(speech, "find_runtime", lambda: "/x/whisper" if engine else None)
    return _ev("speech", **kw)


def test_speech_never_plans_a_chat_model_and_needs_no_score(monkeypatch):
    r = _speech(monkeypatch, engine=False, score=None, present=lambda f: False)
    assert r["verdict"] == "missing"                            # not "no score yet"
    assert [m["id"] for m in r["models"]] == ["base"] and REC not in r["models"]
    models, line = workflows.install_plan(r)
    assert [m["file"] for m in models] == ["ggml-base-q8_0.bin"]
    assert line == "sudo pacman -S --needed ai2-whisper-cpp ffmpeg"


def test_speech_ready_only_with_engine_ffmpeg_and_model(monkeypatch):
    def pacman_ok(cmd, **kw):
        return type("P", (), {"returncode": 0})()
    r = _speech(monkeypatch, score=None, run=pacman_ok)
    assert r["verdict"] == "ready" and r["missing_pkgs"] == [] and r["missing_models"] == []
    r = _speech(monkeypatch, engine=False, score=None, run=pacman_ok)
    assert r["verdict"] == "missing" and r["missing_pkgs"] == ["ai2-whisper-cpp"]
    assert r["pkg_state"]["ai2-whisper-cpp"] is False


def test_speech_model_follows_the_tier(monkeypatch):
    assert [m["id"] for m in _speech(monkeypatch, hw=TINY)["models"]] == ["tiny"]
    assert [m["id"] for m in _speech(monkeypatch, hw=LIGHT)["models"]] == ["base"]
    big = _speech(monkeypatch, hw=BIG, run=_no_pacman)
    assert [m["id"] for m in big["models"]] == ["base"] and "ffmpeg" in big["packages"]
    assert workflows.speech_model_id(TINY) == "tiny" and workflows.speech_model_id(LIGHT) == "base"


def test_speech_info_names_the_whisper_model_and_no_empty_needs(monkeypatch):
    text = workflows.render_info(_speech(monkeypatch, present=lambda f: False))
    assert "Whisper base" in text and "to download, 82 MB" in text and "ai2-whisper-cpp" in text
    assert "Needs:" not in text


def test_workflow_install_speech_with_no_score_pulls_only_whisper(tmp_path, monkeypatch, capsys):
    from ai2 import speech
    pulled = []
    monkeypatch.setenv("AI2_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "detect", lambda: LIGHT)
    monkeypatch.setattr(cli, "_load_score", lambda: None)
    monkeypatch.setattr(cli.remote, "load", lambda: None)
    monkeypatch.setattr(speech, "find_runtime", lambda: None)
    monkeypatch.setattr(workflows, "installed_packages", lambda names, run=None: {n: False for n in names})
    monkeypatch.setattr(runner, "_pull_model", lambda m, force=False: pulled.append(m["file"]) or 0)
    assert cli.main(["workflow", "install", "speech"]) == 0
    out = capsys.readouterr().out
    assert pulled == ["ggml-base-q8_0.bin"]
    assert "sudo pacman -S --needed ai2-whisper-cpp ffmpeg" in out and "ai-2 transcribe" in out


def test_other_workflows_still_need_a_score(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: None)
    for name in ("chat", "documents", "translation"):
        assert _ev(name, None)["verdict"] == "unknown"


# --- every tier with its own configuration has a block in every profile ---------
# A missing block is silent: no packages, no profile models, and a verdict of
# "ready" that checked nothing. Creator had none, which Studio and Workstation
# inherit, so every machine of 16 GB or more got that.

EVERYTHING = load_catalog(kind=None)
LARGE = {"creator": Hardware(ram_mib=15800, ram_nominal_gib=16, logical_cores=4, flags=set()),
         "studio": Hardware(ram_mib=31800, ram_nominal_gib=32, logical_cores=4, flags=set()),
         "workstation": Hardware(ram_mib=63800, ram_nominal_gib=64, logical_cores=8, flags=set())}
DOC_PACKAGES = ["tesseract", "tesseract-data-eng", "tesseract-data-spa", "tesseract-data-deu", "poppler", "img2pdf"]


def _pacman(installed: bool):
    def run(cmd, **kw):
        return type("P", (), {"returncode": 0 if installed else 1})()
    return run


def _documents(hw, present, installed, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/pacman")
    return workflows.evaluate(workflows.get_profile("documents"), hw, _score(), REC, None,
                              lambda f: "/x" if present(f) else None, EVERYTHING, run=_pacman(installed))


def test_every_profile_covers_every_configured_tier():
    from ai2.tiers import load_tiers
    configured = {t.id for t in load_tiers().values() if not t.config_from}
    assert configured == {"tiny", "light", "standard", "creator"}
    for p in workflows.load_profiles():
        assert configured <= set(p["tiers"]), f"{p['id']} has no block for {configured - set(p['tiers'])}"


@pytest.mark.parametrize("name", LARGE)
def test_documents_on_large_tiers_is_the_embedder_and_packages_not_a_chat_model(name, monkeypatch):
    hw = LARGE[name]
    from ai2.tiers import assign, load_tiers, resolve_config
    tiers = load_tiers()
    assert assign(hw, tiers).id == name and workflows.config_tier_id(hw) == "creator"
    r = _documents(hw, present=lambda f: False, installed=False, monkeypatch=monkeypatch)
    assert r["verdict"] == "missing"
    assert [m["id"] for m in r["models"]] == [resolve_config(tiers[name], tiers)["rag"]["embedder"]]
    assert REC not in r["models"]
    assert r["packages"] == DOC_PACKAGES and r["missing_pkgs"] == DOC_PACKAGES
    models, line = workflows.install_plan(r)
    assert [m["id"] for m in models] == ["nomic-embed-text-v2-moe"]
    assert line == "sudo pacman -S --needed " + " ".join(DOC_PACKAGES)


@pytest.mark.parametrize("name", LARGE)
def test_documents_on_large_tiers_is_ready_only_with_embedder_and_packages(name, monkeypatch):
    hw = LARGE[name]
    assert _documents(hw, lambda f: True, True, monkeypatch)["verdict"] == "ready"
    assert _documents(hw, lambda f: False, True, monkeypatch)["missing_models"]     # the embedder is checked
    assert _documents(hw, lambda f: False, True, monkeypatch)["verdict"] == "missing"
    assert _documents(hw, lambda f: True, False, monkeypatch)["verdict"] == "missing"   # so are the packages
