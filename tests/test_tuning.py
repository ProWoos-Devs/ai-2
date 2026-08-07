from ai2.detect import Hardware
from ai2.tiers import load_tiers, resolve_config
from ai2.tuning import build_plan, render_plan


class FakeBackend:
    name = "fake"

    def __init__(self, enabled=(), unknown=()):
        self._enabled = set(enabled)
        self._unknown = set(unknown)

    def is_enabled(self, service):
        if service in self._unknown:
            return None
        return service in self._enabled

    def enable_cmd(self, service):
        return ["fake-enable", service]

    def disable_cmd(self, service):
        return ["fake-disable", service]


def tiny_plan(backend):
    tiers = load_tiers()
    tier = tiers["tiny"]
    hw = Hardware(ram_nominal_gib=2, logical_cores=2, init_system="runit")
    return build_plan(hw, tier, resolve_config(tier, tiers), backend)


def test_plan_is_pure_planning(tmp_path):
    backend = FakeBackend(enabled={"cupsd"})
    plan = tiny_plan(backend)
    text = render_plan(plan)
    assert "/etc/sysctl.d/90-ai2.conf" in text
    assert "vm.swappiness=180" in text
    assert "fake-disable cupsd" in text
    assert "earlyoom" in text
    assert "provider llama.cpp" in text
    assert "record assigned tier 'tiny'" in text


def test_disabled_services_not_touched():
    backend = FakeBackend(enabled=set())  # nothing enabled
    text = render_plan(tiny_plan(backend))
    assert "fake-disable" not in text


def test_unknown_service_reported_not_executed():
    backend = FakeBackend(unknown={"ModemManager"})
    text = render_plan(tiny_plan(backend))
    assert "ModemManager not found" in text
