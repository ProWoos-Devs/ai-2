"""Cross-file checks: the tier YAMLs, the catalog and the scoring code must
agree, or the drift stays silent until a user hits it (2026-08-21 review)."""
from ai2.benchmark import STAR_LABELS
from ai2.models import load_catalog
from ai2.tiers import load_tiers, resolve_config


def test_tier_models_exist_in_catalog():
    ids = {m["id"] for m in load_catalog()}
    tiers = load_tiers()
    for tier in tiers.values():
        for m in resolve_config(tier, tiers).get("models") or []:
            assert m["id"] in ids, f"{tier.id} names unknown model {m['id']}"


def test_tier_capability_keys_match_star_labels():
    tiers = load_tiers()
    for tier in tiers.values():
        caps = resolve_config(tier, tiers).get("capabilities") or {}
        unknown = set(caps) - set(STAR_LABELS)
        assert not unknown, f"{tier.id}: capability keys {unknown} are not scored"


def test_catalog_entries_are_consistent():
    seen = set()
    for m in load_catalog():
        assert m["id"] not in seen; seen.add(m["id"])
        assert m["ram_peak_mb"] > m["file_mb"], m["id"]
        assert m.get("license"), m["id"]
        assert m["file"].endswith(".gguf"), m["id"]


def test_exactly_one_benchmark_model():
    flagged = [m["id"] for m in load_catalog() if m.get("benchmark")]
    assert flagged == ["qwen2.5-0.5b"]


def test_version_single_source():
    import tomllib
    from ai2 import __version__
    data = tomllib.load(open("pyproject.toml", "rb"))
    assert "version" in data["project"]["dynamic"]
    assert data["tool"]["setuptools"]["dynamic"]["version"]["attr"] == "ai2.__version__"
    assert __version__.count(".") == 2
