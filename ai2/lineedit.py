"""Line editing for every prompt a person types into.

Python's input() only understands the arrow keys, Home and End once the
readline module has been imported. Without it the terminal's own escape codes
land in the line as text, which is what Rafael saw in the terminal chat: "when
I use the arrow keys, instead of moving the cursor it types things like [[C"
(2026-09-19). The same was true of Search Knowledge and of the setup's first
question. Importing readline fixes all of them, and brings the up arrow's
recall of earlier lines with it, which suits a chat and a search."""

from __future__ import annotations

import sys


def enable(stdin=None, stdout=None) -> bool:
    """Turn line editing on for the input() calls that follow. Only for a
    person at a terminal (readline may write control codes of its own, which a
    pipe or a log must never receive), and never an error where Python was
    built without the module. True when it is on."""
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    try:
        if not (stdin.isatty() and stdout.isatty()):
            return False
    except (AttributeError, ValueError):
        return False
    try:
        import readline  # noqa: F401  (the import itself is what enables it)
    except ImportError:
        return False
    return True
