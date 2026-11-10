"""The computer's own health for `ai-2 doctor` (ai2/health.py): temperature,
battery and the disk's SMART record, against a made-up /sys."""

import json

from ai2 import doctor, health


def _tree(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text + "\n")
    return str(root)


def test_temperature_prefers_the_processor_sensor_and_the_firmware_limit(tmp_path):
    """Read off the 2011 HP: acpitz said 37 while k10temp said 50, and
    k10temp's "high" of 70 is no limit, the firmware acts at 95."""
    hw = _tree(tmp_path / "hwmon", {
        "hwmon1/name": "acpitz", "hwmon1/temp1_input": "37000",
        "hwmon3/name": "k10temp", "hwmon3/temp1_input": "50125",
        "hwmon3/temp1_max": "70000", "hwmon3/temp1_crit": "115000",
    })
    th = _tree(tmp_path / "thermal", {
        "thermal_zone0/trip_point_0_type": "hot", "thermal_zone0/trip_point_0_temp": "105000",
        "thermal_zone0/trip_point_1_type": "passive", "thermal_zone0/trip_point_1_temp": "95000",
    })
    assert health.firmware_limit(th) == (95, "passive")
    assert health.cpu_temperature(hw, th) == {"sensor": "k10temp", "now": 50, "limit": 95, "limit_kind": "passive"}
    # without a firmware limit k10temp gives none of its own
    assert health.cpu_temperature(hw, str(tmp_path / "none"))["limit"] is None


def test_temperature_takes_the_hottest_core_and_intels_own_limit(tmp_path):
    hw = _tree(tmp_path / "hwmon", {
        "hwmon0/name": "coretemp",
        "hwmon0/temp2_input": "61000", "hwmon0/temp2_max": "87000", "hwmon0/temp2_crit": "105000",
        "hwmon0/temp3_input": "66000", "hwmon0/temp3_max": "87000", "hwmon0/temp3_crit": "105000",
    })
    assert health.cpu_temperature(hw, str(tmp_path / "none")) == {
        "sensor": "coretemp", "now": 66, "limit": 87, "limit_kind": "passive"}
    th = _tree(tmp_path / "thermal", {
        "thermal_zone0/trip_point_0_type": "critical", "thermal_zone0/trip_point_0_temp": "103000"})
    assert health.cpu_temperature(hw, th)["limit_kind"] == "critical"


def test_no_sensor_is_no_line(tmp_path, monkeypatch):
    assert health.cpu_temperature(_tree(tmp_path, {"hwmon0/name": "nvme"}), str(tmp_path / "none")) is None
    monkeypatch.setattr(health, "cpu_temperature", lambda: None)
    assert doctor.check_temperature() is None


def test_temperature_warns_only_near_the_real_limit(monkeypatch):
    """74 right after a start was a WARN against k10temp's 70, on a
    computer that acts at 95."""
    def at(now):
        monkeypatch.setattr(health, "cpu_temperature", lambda: {
            "sensor": "k10temp", "now": now, "limit": 95, "limit_kind": "passive"})
        return doctor.check_temperature()
    assert at(74).status == doctor.OK and "slows itself down at 95" in at(74).detail
    assert at(91).status == doctor.WARN and "fan" in at(91).detail
    monkeypatch.setattr(health, "cpu_temperature", lambda: {
        "sensor": "acpitz", "now": 50, "limit": None, "limit_kind": None})
    assert doctor.check_temperature().status == doctor.INFO


def test_battery_capacity_against_new(tmp_path):
    ps = _tree(tmp_path, {
        "ACAD/type": "Mains",
        "BAT0/type": "Battery", "BAT0/present": "1", "BAT0/capacity": "100",
        "BAT0/energy_full": "54150000", "BAT0/energy_full_design": "58140000", "BAT0/cycle_count": "28",
        "BAT1/type": "Battery", "BAT1/present": "1",
        "BAT1/charge_full": "1000000", "BAT1/charge_full_design": "4400000",
        "hidpp_battery_0/type": "Battery", "hidpp_battery_0/scope": "Device",
        "BAT2/type": "Battery", "BAT2/present": "0",
    })
    found = health.batteries(ps)
    assert [(b["name"], b["percent_of_new"]) for b in found] == [("BAT0", 93), ("BAT1", 23)]
    assert found[0]["cycles"] == 28


def test_battery_lines(monkeypatch):
    monkeypatch.setattr(health, "batteries", lambda: [
        {"name": "BAT0", "percent_of_new": 23, "charge": 100, "cycles": 900}])
    c = doctor.check_battery()[0]
    assert c.status == doctor.WARN and "23%" in c.detail
    # a laptop without one says so; a desktop says nothing
    monkeypatch.setattr(health, "batteries", lambda: [])
    monkeypatch.setattr(health, "is_portable", lambda: True)
    assert "charger" in doctor.check_battery()[0].detail
    monkeypatch.setattr(health, "is_portable", lambda: False)
    assert doctor.check_battery() == []


NVME_OK = {"smart_status": {"passed": True}, "power_on_time": {"hours": 4773},
           "nvme_smart_health_information_log": {"critical_warning": 0, "media_errors": 0, "percentage_used": 12}}


def _ata(reallocated=0, pending=0, passed=True):
    return {"smart_status": {"passed": passed}, "power_on_time": {"hours": 21000},
            "ata_smart_attributes": {"table": [
                {"id": 5, "name": "Reallocated_Sector_Ct", "raw": {"value": reallocated}},
                {"id": 9, "name": "Power_On_Hours", "raw": {"value": 21000}},
                {"id": 197, "name": "Current_Pending_Sector", "raw": {"value": pending}}]}}


def test_smart_summary():
    assert health.summarize_smart(NVME_OK) == {"state": "ok", "detail": "", "hours": 4773}
    worn = health.summarize_smart(_ata(reallocated=8, pending=8))
    assert worn["state"] == "worn" and "8 sectors moved away" in worn["detail"] and "8 sectors waiting to be moved" in worn["detail"]
    failing = health.summarize_smart(_ata(reallocated=900, passed=False))
    assert failing["state"] == "failing" and failing["detail"].startswith("the disk says it is about to fail")
    used = dict(NVME_OK, nvme_smart_health_information_log={"critical_warning": 0, "media_errors": 0,
                                                             "percentage_used": 97})
    assert health.summarize_smart(used)["state"] == "worn"
    assert health.summarize_smart({"device": {"name": "/dev/sda"}})["state"] == "unknown"


def test_internal_disks_leave_out_sticks_and_usb(tmp_path):
    real = tmp_path / "devices"
    for path in ("pci0/ata1/sda", "pci0/usb2/2-1/sdb", "pci0/ata2/sdc", "pci0/nvme/nvme0n1", "virtual/zram0"):
        (real / path).mkdir(parents=True)
    (real / "pci0/ata2/sdc/removable").write_text("1\n")
    block = tmp_path / "block"
    block.mkdir()
    for path in ("pci0/ata1/sda", "pci0/usb2/2-1/sdb", "pci0/ata2/sdc", "pci0/nvme/nvme0n1", "virtual/zram0"):
        (block / path.rsplit("/", 1)[1]).symlink_to(real / path)
    assert health.internal_disks(str(block)) == ["nvme0n1", "sda"]


def test_doctor_reads_the_record_left_at_boot(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "sda.json").write_text(json.dumps(_ata(reallocated=8, pending=8)))
    (cache / "sdb.json").write_text(json.dumps(_ata()))
    monkeypatch.setattr(health, "internal_disks", lambda sys_block="/sys/block": ["sda", "sdb", "sdc"])
    monkeypatch.setattr(health, "DISK_CACHE", str(cache))
    monkeypatch.setattr(health.os, "geteuid", lambda: 1000)
    real = health.read_disks
    monkeypatch.setattr(health, "read_disks", lambda: real(cache=str(cache)))
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/" + name)
    a, b, c = doctor.check_disk_health()
    assert a.status == doctor.WARN and "keep a copy" in a.detail
    assert b.status == doctor.OK and "21000 hours" in b.detail
    assert c.status == doctor.INFO and "sudo ai-2 doctor" in c.detail
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    assert "smartmontools" in doctor.check_disk_health()[2].detail


def test_doctor_warns_outside_runit():
    from ai2.detect import Hardware
    assert doctor.check_init(Hardware(init_system="runit")) is None
    c = doctor.check_init(Hardware(init_system="systemd"))
    assert c.status == doctor.WARN and "not supported" in c.detail


def test_the_package_ships_nothing_for_systemd():
    from pathlib import Path
    pkgbuild = (Path(__file__).resolve().parents[1] / "packaging" / "ai-2" / "PKGBUILD").read_text()
    assert "systemd" not in pkgbuild
