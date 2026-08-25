"""machine_profile() assembles what the other modules own; these tests pin
the shape and the JSON-serializability contract."""
import json

from ai2 import profile as profile_mod
from ai2.detect import Hardware


def _hw():
    return Hardware(cpu_model="Test CPU", logical_cores=2, flags={"sse2", "sse4a"},
                    ram_mib=3800, ram_nominal_gib=4, root_disk_rotational=True,
                    init_system="runit")


def test_profile_assembles_and_serializes(monkeypatch):
    monkeypatch.setattr(profile_mod, "installed_tier_id", lambda: "light")
    monkeypatch.setattr(profile_mod, "load_score",
                        lambda: {"ai_score": 29, "tg_tps": 1.93,
                                 "capabilities": {"chat": 2}})
    prof = profile_mod.machine_profile(_hw())
    assert prof["tier"] == {"assigned": "light", "configured": "light"}
    assert prof["hardware"]["cpu_variant"] == "baseline"
    assert prof["hardware"]["flags"] == ["sse2", "sse4a"]
    assert prof["benchmark"]["ai_score"] == 29
    assert prof["capabilities"] == {"chat": 2}
    json.dumps(prof)  # the whole dict must be JSON-clean as returned


def test_profile_before_benchmark_and_tuning(monkeypatch):
    monkeypatch.setattr(profile_mod, "installed_tier_id", lambda: None)
    monkeypatch.setattr(profile_mod, "load_score", lambda: None)
    prof = profile_mod.machine_profile(_hw())
    assert prof["tier"]["configured"] is None
    assert prof["benchmark"] is None
    assert prof["capabilities"] is None
    json.dumps(prof)
