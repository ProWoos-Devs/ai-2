"""Suite-wide guards."""
import pytest


@pytest.fixture(autouse=True)
def _no_real_update_checker(monkeypatch, tmp_path):
    """No test may run the real update checker. It syncs package databases
    over the network (the wizard tests spent about 12 s each doing exactly
    that on a machine with pacman-contrib, 2026-09-11), and in the build
    container pamac-checkupdates blocks without D-Bus, which hung the package
    build on 2026-09-14. The checker's name becomes one that exists only when
    a test installs its fake under that name (tests/test_updates.py), and
    pamac's refresh stamp and config point into the test's tmp dir. The stamp
    is created fresh, so no refresh is ever "due" and check_now() never waits
    for a daemon (that wait, 300 s per call, was the other half of the
    2026-09-14 hang, on the laptop the real stamp had happened to be fresh);
    a test of the due path sets its own stamp path or ages this one."""
    from ai2 import updates
    stamp = tmp_path / "pamac-refresh_timestamp"
    stamp.touch()
    monkeypatch.setattr(updates, "CHECK_CMD", "ai2-test-checkupdates")
    monkeypatch.setattr(updates, "PAMAC_REFRESH_STAMP", str(stamp))
    monkeypatch.setattr(updates, "PAMAC_CONF", str(tmp_path / "pamac.conf"))
