from ai2 import doctor
from ai2.detect import Hardware
from tests.test_tuning import FakeBackend


def test_render_and_verdict():
    checks = [doctor.Check(doctor.OK, "A", "fine"), doctor.Check(doctor.WARN, "B", "meh")]
    assert doctor.verdict(checks) == 1
    checks.append(doctor.Check(doctor.FAIL, "C", "broken"))
    assert doctor.verdict(checks) == 2
    text = doctor.render(checks)
    assert "WARN  B" in text and "FAIL  C" in text


def test_service_check_against_expectation():
    b = FakeBackend(enabled={"earlyoom", "cupsd"}, unknown={"avahi-daemon"})
    assert doctor.check_service(b, "earlyoom", True).status == doctor.OK
    assert doctor.check_service(b, "cupsd", False).status == doctor.WARN
    assert doctor.check_service(b, "avahi-daemon", False).status == doctor.INFO


def test_runtime_check_names_the_package(monkeypatch):
    monkeypatch.setattr(doctor, "find_runtime", lambda v: None)
    hw = Hardware(flags=set())
    c = doctor.check_runtime(hw)
    assert c.status == doctor.FAIL and "ai2-llama-cpp-baseline" in c.detail


def test_report_has_no_home_path(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    hw = Hardware(cpu_model="test cpu", logical_cores=2, ram_mib=3000, ram_nominal_gib=4, flags=set())
    text = doctor.report_text(hw, [doctor.Check(doctor.OK, "A", "fine")])
    assert "== Hardware" in text and "test cpu" in text
    assert str(tmp_path) not in text


def test_update_check_does_not_call_a_failed_check_current(tmp_path, monkeypatch):
    """checkupdates exits 1 when it cannot check (offline, mirror down); that
    is "unknown", not "system is current", and the hint is ai-2 update."""
    from tests.test_updates import _fake_checkupdates
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    _fake_checkupdates(tmp_path, monkeypatch, "#!/bin/sh\nexit 1\n")
    c = doctor.check_updates()
    assert "could not check" in c.detail and "current" not in c.detail
    _fake_checkupdates(tmp_path, monkeypatch, "#!/bin/sh\necho 'a 1-1 -> 1-2'\necho 'b 1-1 -> 1-2'\n")
    c = doctor.check_updates()
    assert c.detail.startswith("2 package update(s)") and "ai-2 update" in c.detail
    assert "pacman -Syu" not in c.detail
