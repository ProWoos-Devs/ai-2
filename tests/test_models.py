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
