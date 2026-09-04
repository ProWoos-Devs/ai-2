"""Workflow profiles: the gate (tier grant + star minimums), the remote way
out, and the read-only install (models pulled, packages only printed)."""
import os

from ai2 import cli, workflows
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
    assert ids == ["chat", "documents", "translation"]
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
    r = _ev("translation", _score(translation=0), remote={"url": "http://10.0.0.5:8080"})
    assert r["verdict"] == "remote" and "10.0.0.5" in r["why"]


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
    monkeypatch.setattr(cli, "detect", lambda: LIGHT)
    monkeypatch.setattr(cli, "_load_score", lambda: _score())
    monkeypatch.setattr(cli, "_recommended_model", lambda hw: REC)
    monkeypatch.setattr("shutil.which", lambda n: None)
    pulled = []
    monkeypatch.setattr(cli, "_pull_model", lambda m, force=False: pulled.append(m["id"]) or 0)
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
