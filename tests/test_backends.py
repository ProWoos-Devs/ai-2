"""Package backends: a stalled local-database query is "unknown", never a hang
and never "missing"."""
import subprocess

from ai2.backends.apt import AptBackend
from ai2.backends.pacman import PacmanBackend


def test_query_timeout_is_unknown(monkeypatch):
    def hang(cmd, **kw):
        assert kw.get("timeout"), "query must be time-boxed"
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])
    for backend in (PacmanBackend(), AptBackend()):
        monkeypatch.setattr(backend, "available", lambda: True)
        monkeypatch.setattr(subprocess, "run", hang)
        assert backend.is_installed("anything") is None
