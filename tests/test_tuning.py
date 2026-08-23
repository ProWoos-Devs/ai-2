import os
from ai2.detect import Hardware
from ai2.tiers import load_tiers, resolve_config
from ai2.tuning import build_plan, render_plan


class FakeBackend:
    # name must be 'runit' so the zram/oom provider tables resolve.
    name = "runit"

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


class FakePkgBackend:
    name = "fakepkg"

    def is_installed(self, pkg):
        return False

    def install_cmd(self, pkgs):
        return ["fake-install", *pkgs]


def tiny_plan(backend, pkg=None):
    tiers = load_tiers()
    tier = tiers["tiny"]
    # an SSE4 CPU (noavx build): the zstd default applies, see the baseline test below
    hw = Hardware(ram_nominal_gib=2, logical_cores=2, init_system="runit", flags={"sse4_1", "sse4_2"})
    return build_plan(hw, tier, resolve_config(tier, tiers), backend, pkg or FakePkgBackend())


def test_plan_is_pure_planning():
    text = render_plan(tiny_plan(FakeBackend(enabled={"cupsd"})))
    assert "/etc/sysctl.d/90-ai2.conf" in text
    assert "vm.swappiness=180" in text
    assert "fake-disable cupsd" in text
    assert "record assigned tier 'tiny'" in text


def test_zram_provisioned():
    text = render_plan(tiny_plan(FakeBackend()))
    assert "fake-install zramen zramen-runit" in text
    assert "configure zram (zstd, 100% of RAM)" in text
    assert "enable zram swap service 'zramen'" in text


def test_earlyoom_provisioned():
    text = render_plan(tiny_plan(FakeBackend()))
    assert "fake-install earlyoom earlyoom-runit" in text
    assert "enable OOM guard service 'earlyoom'" in text


def test_disabled_services_not_touched():
    text = render_plan(tiny_plan(FakeBackend(enabled=set())))
    assert "fake-disable" not in text


def test_unknown_service_reported_not_executed():
    text = render_plan(tiny_plan(FakeBackend(unknown={"ModemManager"})))
    assert "ModemManager not found" in text


class InstalledPkgBackend(FakePkgBackend):
    def is_installed(self, pkg):
        return True


def test_no_install_actions_when_tooling_already_installed():
    # An ISO install already carries zramen/earlyoom: the plan must not need a
    # package database or the network to apply.
    plan = tiny_plan(FakeBackend(), InstalledPkgBackend())
    descriptions = " ".join(a.description for a in plan)
    assert "install zram tooling" not in descriptions
    assert "install OOM guard" not in descriptions
    assert "configure zram" in descriptions and "enable OOM guard service" in descriptions


def test_weak_cpu_gets_cheaper_zram_algorithm():
    tiers = load_tiers()
    tier = tiers["tiny"]
    hw = Hardware(ram_nominal_gib=2, logical_cores=2, init_system="runit", flags=set())   # baseline build
    text = render_plan(build_plan(hw, tier, resolve_config(tier, tiers), FakeBackend(), FakePkgBackend()))
    assert "configure zram (lz4" in text


def test_zswap_tier_writes_memory_conf_and_boot_service(monkeypatch):
    from ai2 import tuning
    monkeypatch.setattr(tuning, "BOOT_TUNING", __file__)   # pretend the script is installed
    tiers = load_tiers()
    tier = tiers["standard"]
    hw = Hardware(ram_nominal_gib=8, logical_cores=4, init_system="runit", flags={"avx2"})
    text = render_plan(build_plan(hw, tier, resolve_config(tier, tiers), FakeBackend(), FakePkgBackend()))
    assert "memory.conf (mechanism=zswap, compressor=zstd, zpool=zsmalloc, mglru_min_ttl_ms=1000)" in text
    assert "fake-enable ai2-boot" in text
    assert "no provisioning implemented" not in text


def test_mglru_requested_on_low_ram_tiers(monkeypatch):
    from ai2 import tuning
    monkeypatch.setattr(tuning, "BOOT_TUNING", __file__)
    text = render_plan(tiny_plan(FakeBackend()))
    assert "mglru_min_ttl_ms=1000" in text


def test_apply_backs_up_and_revert_restores(tmp_path, monkeypatch):
    """apply_plan keeps a .ai2-orig copy of a pre-existing file, records what
    it wrote and enabled, and revert() undoes exactly that."""
    from ai2 import tuning
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(tuning, "STATE_DIR", str(tmp_path / "etc-ai2"))
    monkeypatch.setattr(tuning, "MANIFEST_PATH", str(tmp_path / "etc-ai2" / "manifest.json"))
    existing = tmp_path / "conf"
    existing.write_text("user's own settings\n")
    fresh = tmp_path / "new.conf"
    enabled = set()
    backend = FakeBackend()
    backend.is_enabled = lambda s: s in enabled
    actions = [
        tuning._write_file_action(str(existing), "# Managed by AI-2\nx=1\n", "write conf"),
        tuning._write_file_action(str(fresh), "# Managed by AI-2\ny=2\n", "write new"),
        tuning.Action("enable svc", run=lambda: enabled.add("svc"), enables="svc"),
    ]
    tuning.apply_plan(actions)
    assert (tmp_path / "conf.ai2-orig").read_text() == "user's own settings\n"
    assert existing.read_text().startswith("# Managed by AI-2")
    m = tuning._load_manifest()
    assert str(existing) in m["files"] and str(fresh) in m["files"] and m["services"] == ["svc"]
    backend.disable_cmd = lambda s: ["true"]
    done = tuning.revert(backend)
    assert existing.read_text() == "user's own settings\n"
    assert not fresh.exists() and not (tmp_path / "conf.ai2-orig").exists()
    assert any("svc" in d for d in done) and not os.path.exists(tuning.MANIFEST_PATH)
