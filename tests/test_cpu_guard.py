"""The processor guard (packaging/ai-2/cpu-guard.sh), one step at a time
(--once) against a made-up /sys shaped like the 2011 HP: boost on, a table of
frequencies from 1.9 down to 0.8 GHz, k10temp, firmware acting at 95."""

import os
import subprocess
from pathlib import Path

from ai2 import doctor, health

SCRIPT = Path(__file__).resolve().parents[1] / "packaging" / "ai-2" / "cpu-guard.sh"
TABLE = "1900000 1800000 1600000 1400000 1200000 1000000 800000"
CPUFREQ = "devices/system/cpu/cpufreq"


def _sys(tmp_path, table=TABLE, boost="1", policies=("policy0", "policy1")):
    files = {"class/hwmon/hwmon1/name": "acpitz", "class/hwmon/hwmon1/temp1_input": "30000",
             "class/hwmon/hwmon3/name": "k10temp", "class/hwmon/hwmon3/temp1_input": "40000",
             "class/thermal/thermal_zone0/trip_point_1_type": "passive",
             "class/thermal/thermal_zone0/trip_point_1_temp": "95000"}
    if boost is not None:
        files[f"{CPUFREQ}/boost"] = boost
    for p in policies:
        files[f"{CPUFREQ}/{p}/scaling_max_freq"] = "1900000"
        if table:
            files[f"{CPUFREQ}/{p}/scaling_available_frequencies"] = table
    for rel, text in files.items():
        f = tmp_path / "sys" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text + "\n")
    return tmp_path


def _step(root, temp, conf=None):
    (root / "sys/class/hwmon/hwmon3/temp1_input").write_text(f"{temp * 1000}\n")
    env = dict(os.environ, AI2_SYS=str(root / "sys"), AI2_RUN=str(root / "run"),
               AI2_CONF=str(conf or root / "no.conf"))
    subprocess.run(["sh", str(SCRIPT), "--once"], env=env, check=True, timeout=20)
    read = lambda rel: (root / "sys" / rel).read_text().strip()
    boost = read(f"{CPUFREQ}/boost") if (root / "sys" / CPUFREQ / "boost").exists() else None
    return boost, int(read(f"{CPUFREQ}/policy0/scaling_max_freq"))


def test_a_cool_processor_is_left_alone(tmp_path):
    root = _sys(tmp_path)
    assert _step(root, 60) == ("1", 1900000)
    assert _step(root, 84) == ("1", 1900000)
    assert health.cpu_guard(str(root / "run/cpu-guard/status")) == {
        "ceiling": 85, "held": False, "boost": "on", "max_khz": 1900000}


def test_down_one_step_at_a_time_to_half_and_back_up(tmp_path):
    root = _sys(tmp_path)
    assert _step(root, 85) == ("0", 1900000)          # the boost goes first
    assert _step(root, 87) == ("0", 1800000)
    assert _step(root, 86) == ("0", 1600000)
    assert (root / f"sys/{CPUFREQ}/policy1/scaling_max_freq").read_text().strip() == "1600000"
    status = health.cpu_guard(str(root / "run/cpu-guard/status"))
    assert status["held"] and status["boost"] == "off" and status["max_khz"] == 1600000
    for want in (1400000, 1200000, 1000000, 1000000):  # 800000 is under half of the top
        assert _step(root, 90) == ("0", want)
    assert _step(root, 82) == ("0", 1000000)           # between the two points nothing moves
    for want in (1200000, 1400000, 1600000, 1800000, 1900000):
        assert _step(root, 79) == ("0", want)
    assert _step(root, 79) == ("1", 1900000)           # the boost comes back last
    assert _step(root, 79) == ("1", 1900000)
    assert health.cpu_guard(str(root / "run/cpu-guard/status"))["held"] is False


def test_a_boost_that_was_off_stays_off(tmp_path):
    root = _sys(tmp_path, boost="0")
    assert _step(root, 90) == ("0", 1800000)
    assert _step(root, 70) == ("0", 1900000)
    assert _step(root, 70) == ("0", 1900000)


def test_without_a_table_the_steps_are_tenths_of_the_top(tmp_path):
    root = _sys(tmp_path, table=None, boost=None, policies=("policy0",))
    assert _step(root, 90) == (None, 1710000)
    for _ in range(6):
        last = _step(root, 90)
    assert last == (None, 950000)
    assert _step(root, 70) == (None, 1140000)


def test_the_ceiling_can_be_set_or_switched_off(tmp_path):
    root = _sys(tmp_path)
    conf = tmp_path / "cpu-guard.conf"
    conf.write_text("ceiling = 70\n")
    assert _step(root, 69, conf) == ("1", 1900000)
    assert _step(root, 70, conf) == ("0", 1900000)
    off = _sys(tmp_path / "second")
    conf.write_text("ceiling = off\n")
    assert _step(off, 99, conf) == ("1", 1900000)
    assert not (off / "run").exists()


def test_the_ceiling_stays_under_the_firmwares_own_point(tmp_path):
    root = _sys(tmp_path)
    (root / "sys/class/thermal/thermal_zone0/trip_point_1_temp").write_text("80000\n")
    assert _step(root, 74) == ("1", 1900000)
    assert _step(root, 75) == ("0", 1900000)


def test_doctor_says_when_the_processor_is_held(monkeypatch):
    monkeypatch.setattr(health, "cpu_temperature", lambda: {
        "sensor": "k10temp", "now": 84, "limit": 95, "limit_kind": "passive"})
    monkeypatch.setattr(health, "cpu_guard", lambda: {"ceiling": 85, "held": True, "boost": "off", "max_khz": 1600000})
    c = doctor.check_temperature()
    assert c.status == doctor.INFO and "top speed 1.6 GHz" in c.detail and "under 85 °C" in c.detail
    monkeypatch.setattr(health, "cpu_guard", lambda: {"ceiling": 85, "held": False, "boost": "on", "max_khz": 1900000})
    assert doctor.check_temperature().status == doctor.OK
