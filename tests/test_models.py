from ai2.models import estimate_tps, load_catalog, recommend


def test_catalog_loads_sorted():
    cat = load_catalog()
    assert len(cat) >= 4
    sizes = [m["params_b"] for m in cat]
    assert sizes == sorted(sizes)
    assert cat[0]["id"] == "gemma3-270m"


def test_estimate_scales_inverse_with_params():
    # 2 tok/s on 0.5B -> ~0.67 on 1.5B
    assert round(estimate_tps(2.0, 0.5, 1.5), 2) == 0.67


def test_rmm_pc_gets_small_model_and_remote():
    # The real RMM-PC case: 4 GB (3381 MiB), 1.93 tok/s measured on 0.5B.
    rec = recommend(3381, 1.93, 0.5)
    assert rec["local"]["id"] == "qwen2.5-0.5b"   # only the 0.5B is fast enough
    assert rec["remote_suggested"] is True         # 1.5B fits RAM but is too slow


def test_rmm_pc_on_the_clang_engine_keeps_the_small_model():
    # RMM-PC with the clang engine: 3.18 to 3.3 tok/s on the 0.5B (2026-11-25).
    # Gemma 3 1B measured 1.62 tok/s there, too slow; the 0.8B must not flip in
    # and out with run-to-run noise.
    for tps in (3.18, 3.21, 3.25, 3.3, 3.4):
        assert recommend(3381, tps, 0.5)["local"]["id"] == "qwen2.5-0.5b"


def test_slow_machine_is_not_pushed_down_to_the_270m():
    # The higher line is only for models larger than the benchmark model.
    for tps in (1.5, 1.93, 2.1):
        assert recommend(3381, tps, 0.5)["local"]["id"] == "qwen2.5-0.5b"
    assert recommend(3381, 1.3, 0.5)["local"]["id"] == "gemma3-270m"


def test_rafaminu_pc_gets_the_1b():
    # E1-7010, 6889 MiB, 5.12 to 5.32 tok/s on the 0.5B (2026-11-26): the 1.7B is
    # estimated at 1.56, under the line for a larger model, the 1B at 2.6.
    for tps in (5.12, 5.3, 5.32):
        rec = recommend(6889, tps, 0.5)
        assert rec["local"]["id"] == "gemma3-1b" and rec["remote_suggested"] is True


def test_fast_machine_gets_larger_model():
    # 32 GB, 40 tok/s measured on a 0.5B (a strong CPU/GPU): should pick the 7B.
    rec = recommend(32000, 40.0, 0.5)
    assert rec["local"]["params_b"] == 7.0


def test_tiny_ram_no_local_model():
    # 1 GB machine: nothing in the catalog fits the RAM budget.
    rec = recommend(1024, 5.0, 0.5)
    assert rec["local"] is None
    assert rec["remote_suggested"] is True


def test_starter_and_ram_fit():
    from ai2.models import is_starter, load_catalog, models_that_fit
    cat = load_catalog()
    by_id = {m["id"]: m for m in cat}
    assert is_starter(by_id["gemma3-270m"]) and is_starter(by_id["qwen2.5-0.5b"])
    assert not is_starter(by_id["gemma3-1b"])
    fit = [m["id"] for m in models_that_fit(3800, cat)]     # 4 GB machine
    assert "gemma3-1b" in fit and "smollm3-3b" not in fit


def test_catalog_kinds_are_separated():
    """Embedders never reach recommend(), the picker or the tiers: load_catalog()
    is chat-only by default, kind="embedding" is the documents workflow's list."""
    from ai2.models import embedding_models, load_catalog, recommend
    chat = load_catalog()
    assert all(m.get("kind", "chat") == "chat" for m in chat)
    emb = embedding_models()
    assert {m["id"] for m in emb} >= {"nomic-embed-text-v2-moe", "nomic-embed-text-v1.5"}
    assert all(m["kind"] == "embedding" for m in emb)
    assert len(load_catalog(kind=None)) == len(chat) + len(emb)
    # a 2 GB box at 5 tok/s must still be handed a chat model, not the 137M embedder
    rec = recommend(2048, 5.0, 0.5)
    assert rec["local"] is not None and rec["local"].get("kind", "chat") == "chat"
