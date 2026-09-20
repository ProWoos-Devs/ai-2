"""Suite-wide guards."""
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "real_download: exercises the model downloader itself")


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


@pytest.fixture(autouse=True)
def _no_real_model_download(monkeypatch, request):
    """No test may download a model. Until 0.18.7 the model directory ignored
    XDG_DATA_HOME, so a test that reached a download quietly found the
    developer's own copy in their real home and did nothing; with the
    directory honoring XDG (as it should), the same tests began fetching the
    344 MB embedder into a temp dir, five times per run, over the network.

    A test that needs a model on disk says so, by replacing find_model_file
    or download_model itself; anything else stops here with the name of the
    test, rather than silently costing a download. The tests of the
    downloader itself carry @pytest.mark.real_download."""
    if request.node.get_closest_marker("real_download"):
        return
    from ai2 import cli, runner, runtime

    def refuse(model, dest_dir=None, progress=None):
        raise AssertionError(f"{request.node.name} tried to download {model.get('file')}: "
                             "a test must not fetch a model (replace find_model_file, "
                             "or download_model itself, if it needs one)")

    # every name it is imported under: the modules import the function, so
    # patching runtime alone leaves the path that actually downloads
    # (runner._pull_model) untouched
    for mod in (runtime, runner, cli):
        if hasattr(mod, "download_model"):
            monkeypatch.setattr(mod, "download_model", refuse)


@pytest.fixture(autouse=True)
def _no_real_window(monkeypatch, request):
    """No test may really open a terminal window on the developer's screen,
    which is how a missing bit of isolation was found on 2026-09-20. A test
    that exercises the code which opens one puts the real function back
    (`monkeypatch.setattr(about, "open_window", about_open_window)`) and
    replaces Popen with its own recorder."""
    from ai2 import about

    def refuse(cmd=None):
        raise AssertionError(f"{request.node.name} tried to open a terminal window: {cmd}")

    monkeypatch.setattr(about, "open_window", refuse)
