"""Arrow keys at the prompts (the terminal chat typed [[C instead of moving the
cursor, 2026-09-19)."""
import sys

from ai2 import cli, lineedit


class Tty:
    def __init__(self, tty):
        self._tty = tty

    def isatty(self):
        return self._tty


def test_on_for_a_person_at_a_terminal():
    assert lineedit.enable(Tty(True), Tty(True)) is True
    assert "readline" in sys.modules


def test_off_for_pipes_and_logs():
    assert lineedit.enable(Tty(False), Tty(True)) is False
    assert lineedit.enable(Tty(True), Tty(False)) is False
    assert lineedit.enable(object(), Tty(True)) is False      # no isatty at all


def test_a_python_without_readline_is_not_an_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "readline", None)        # makes the import raise ImportError
    assert lineedit.enable(Tty(True), Tty(True)) is False


def test_every_command_gets_it(monkeypatch, capsys):
    """One call in main(), before the command runs, so no prompt can be added
    later without it."""
    seen = []
    monkeypatch.setattr(lineedit, "enable", lambda *a, **k: seen.append(True) or True)
    assert cli.main(["about"]) == 0
    assert seen == [True]
