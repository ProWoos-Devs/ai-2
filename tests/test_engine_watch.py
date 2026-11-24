"""tools/engine-watch.py: the pin bump it proposes and the PR text it writes.
No network and no git: the GitHub calls are replaced by a dict."""
import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("engine_watch", HERE.parent / "tools" / "engine-watch.py")
ew = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ew)

PKG = "pkgname=x\n_tag=b10398\npkgver=${_tag#b}\npkgrel=3\narch=('x86_64')\n"


def test_real_pkgbuilds_parse_and_flag_sources_exist():
    for cfg in ew.ENGINES.values():
        pins = ew.read_pins((ew.HERE / cfg["pkgbuild"]).read_text())
        ew.parse_tag(pins["tag"])
        assert ew.flags_in(cfg["flag_sources"]), cfg["flag_sources"]


def test_same_scheme_bump_resets_pkgrel():
    text, old, new = ew.bump(PKG, "b12000")
    assert "_tag=b12000\n" in text and "pkgrel=1\n" in text and "epoch" not in text
    assert ew.version_string(old) == "10398-3" and ew.version_string(new) == "12000-1"


def test_bump_only_goes_forward_within_the_scheme():
    for tag in ("b10398", "b10000", "v1.0.0"):            # same, older, other scheme
        with pytest.raises(ew.WatchError):
            ew.bump(PKG, tag)
    text, _, _ = ew.bump(PKG.replace("pkgrel=3", "pkgrel=3\nepoch=2"), "b12359")
    assert "epoch=2\n" in text and text.count("epoch=") == 1   # an existing epoch is kept, never added


REFS = {"v1.0.0": "c1", "b12359": "c1", "v1.0.0-b12359-b1b770d": "c1", "b12358": "c0", "b10398": "c9"}


def test_stable_release_is_pinned_by_the_b_tag_at_its_commit():
    assert ew.pin_tag_for("v1.0.0", "b", REFS) == "b12359"
    assert ew.pin_tag_for("v1.9.6", "v", {}) == "v1.9.6"
    with pytest.raises(ew.WatchError):
        ew.pin_tag_for("v1.0.0", "b", {"v1.0.0": "c1", "b12358": "c0"})
    with pytest.raises(ew.WatchError):
        ew.pin_tag_for("v2.0.0", "b", REFS)


def test_is_newer():
    assert ew.is_newer("v1.9.4", "v1.9.6") and not ew.is_newer("v1.9.6", "v1.9.4")
    assert ew.is_newer("v1.9.4", "v1.10.0")                # by number, not by text
    with pytest.raises(ew.WatchError):
        ew.is_newer("b10398", "v1.0.0")


@pytest.mark.parametrize("tag", ["v1.0.0-rc1", "1.0.0", "master", "", "b12a"])
def test_odd_tags_are_refused(tag):
    with pytest.raises(ew.WatchError):
        ew.parse_tag(tag)


@pytest.mark.parametrize("text", [PKG.replace("pkgver=${_tag#b}", "pkgver=10398"),
                                  PKG.replace("_tag=b10398", "_tag=v1.0.0"),
                                  PKG + "_tag=b1\n"])
def test_pkgbuilds_it_does_not_understand_are_refused(text):
    with pytest.raises(ew.WatchError):
        ew.read_pins(text)


def test_status_maps_the_release_to_the_pins_scheme(monkeypatch, tmp_path):
    pkg = tmp_path / "PKGBUILD"
    pkg.write_text(PKG)
    monkeypatch.setattr(ew, "HERE", tmp_path)
    cfg = {"repo": "o/r", "pkgbuild": "PKGBUILD"}
    answers = {"repos/o/r/releases/latest": {"tag_name": "v1.0.0", "published_at": "2026-11-13T10:20:19Z"}}
    st = ew.status("x", cfg, fetch=answers.__getitem__, refs=lambda repo: REFS)
    assert st["newer"] and st["pinned"] == "b10398" and st["pin_to"] == "b12359" and st["latest"] == "v1.0.0"
    pkg.write_text(PKG.replace("b10398", "b12359"))
    assert not ew.status("x", cfg, fetch=answers.__getitem__, refs=lambda repo: REFS)["newer"]
    answers["repos/o/r/releases/latest"]["prerelease"] = True
    with pytest.raises(ew.WatchError):
        ew.status("x", cfg, fetch=answers.__getitem__, refs=lambda repo: REFS)


def test_tag_refs_counts_annotated_tags_by_their_commit(monkeypatch):
    out = "a1\trefs/tags/v1.0.0\nc1\trefs/tags/v1.0.0^{}\nc1\trefs/tags/b12359\n"
    monkeypatch.setattr(ew, "run", lambda *a, **k: type("P", (), {"stdout": out})())
    assert ew.tag_refs("o/r") == {"v1.0.0": "c1", "b12359": "c1"}


def test_flag_lines_match_whole_flags_only():
    notes = ("- server: remove `--defrag-thold` (#1)\n- add --top-p-foo option\n"
             "- cli: --top-k now defaults to 40\n- unrelated line\n")
    got = ew.flag_lines(notes, ["--top-k", "--top-p", "--defrag-thold"])
    assert [h for _, h in got] == [["--defrag-thold"], ["--top-k"]]
    assert got[0][0] == "server: remove `--defrag-thold` (#1)"            # no doubled list marker


def test_body_stays_under_githubs_limit_and_says_what_was_cut():
    cfg = ew.ENGINES["llama-cpp"]
    _, old, new = ew.bump(PKG, "b12359")
    release = {"tag_name": "v1.0.0", "published_at": "2026-11-13T10:20:19Z",
               "html_url": "https://example.invalid/r", "body": "- ggml-cpu: drop SSE3 path\n" * 20000}
    body = ew.pr_body("llama-cpp", cfg, release, old, new, [f"f.py:{i}" for i in range(500)],
                      tests={"ok": False, "tail": "1 failed"}, run_url="https://example.invalid/run")
    assert len(body) < 65536
    assert "v1.0.0 is tag b12359" in body and "12359-1" in body and "epoch=" not in body
    assert "**FAILED**" in body and "cut at" in body
    assert ew.pr_title(cfg, "v1.0.0", "b12359", "b10398") == "ai2-llama-cpp: v1.0.0 is out as b12359 (pinned b10398)"
    assert "and 19940 more lines" in body and "and 440 more mentions" in body


def test_old_tag_mentions_skip_changelog_and_partial_numbers(monkeypatch, tmp_path):
    (tmp_path / "a.py").write_text("x = 1  # b10398 source\ny = 'b103980'\n")
    (tmp_path / "CHANGELOG.md").write_text("b10398\n")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "b.py").write_text("b10398\n")
    monkeypatch.setattr(ew, "HERE", tmp_path)
    assert ew.old_tag_mentions("b10398") == ["a.py:1"]
