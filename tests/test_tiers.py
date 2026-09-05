import pytest

from ai2.detect import Hardware
from ai2.tiers import assign, load_tiers, resolve_config


def hw(gib, cores=4):
    return Hardware(ram_nominal_gib=gib, logical_cores=cores)


@pytest.fixture(scope="module")
def tiers():
    return load_tiers()


def test_six_tiers_load(tiers):
    assert set(tiers) == {"tiny", "light", "standard", "creator", "studio", "workstation"}


def test_assignment_ladder(tiers):
    assert assign(hw(2), tiers).id == "tiny"
    assert assign(hw(4), tiers).id == "light"
    assert assign(hw(8), tiers).id == "standard"
    assert assign(hw(16), tiers).id == "creator"
    assert assign(hw(32), tiers).id == "studio"
    assert assign(hw(64, cores=8), tiers).id == "workstation"


def test_below_floor_still_assigns_tiny(tiers):
    assert assign(hw(1, cores=1), tiers).id == "tiny"


def test_cores_gate(tiers):
    # 64 GB but 4 cores fails the workstation cores floor, lands on studio.
    assert assign(hw(64, cores=4), tiers).id == "studio"


def test_studio_and_workstation_share_creator_config(tiers):
    creator = resolve_config(tiers["creator"], tiers)
    assert resolve_config(tiers["studio"], tiers) is creator
    assert resolve_config(tiers["workstation"], tiers) is creator
    assert creator["runtime"]["provider"] == "llama.cpp"


def test_tiny_has_no_persistent_runtime(tiers):
    config = resolve_config(tiers["tiny"], tiers)
    assert config["runtime"] == {"provider": "llama.cpp", "service": "on-demand", "idle_timeout_s": 300}


def test_creator_does_not_claim_unimplemented_gpu_offload(tiers):
    config = resolve_config(tiers["creator"], tiers)
    assert "gpu_offload" not in config["runtime"]
