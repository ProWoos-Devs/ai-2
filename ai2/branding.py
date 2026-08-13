"""AI-2 visual identity, ASCII-first.

One motif, the terminal prompt that typed its own name (> AI-2 █), rendered at
a size ladder. The full spec is 000/design/ai2-logo-concepts.txt. Color is
emitted only to a TTY; piped/redirected output stays plain so the marks remain
copy-pasteable and grep-friendly.
"""

from __future__ import annotations

import sys

# Phosphor green #35D07F, the brand color, as a 24-bit ANSI escape.
_GREEN = "\033[38;2;53;208;127m"
_DIM = "\033[38;2;107;122;114m"   # slate, for the attribution line
_RESET = "\033[0m"

TAGLINE = "your old PC gets a new AI brain"
ATTRIBUTION = "Based on Artix Linux"

INLINE = "> AI-2 █"          # > AI-2 █

_COMPACT = (
    "╭──────────────╮\n"
    "│ > AI-2 █     │\n"
    "╰──────────────╯"
)

_ICON = (
    "╭───╮\n"
    "│>█ │\n"
    "╰───╯"
)


def _paint(text: str, use_color: bool) -> str:
    if not use_color:
        return text
    return f"{_GREEN}{text}{_RESET}"


def _want_color(color: bool | None) -> bool:
    if color is None:
        return sys.stdout.isatty()
    return color


def inline(color: bool | None = None) -> str:
    return _paint(INLINE, _want_color(color))


def icon(color: bool | None = None) -> str:
    return _paint(_ICON, _want_color(color))


def compact(color: bool | None = None) -> str:
    return _paint(_COMPACT, _want_color(color))


def full(color: bool | None = None) -> str:
    use_color = _want_color(color)
    mark = _paint(_COMPACT, use_color)
    tag = f"{_DIM}{TAGLINE}{_RESET}" if use_color else TAGLINE
    attr = f"{_DIM}{ATTRIBUTION}{_RESET}" if use_color else ATTRIBUTION
    return f"{mark}\n {tag}\n {attr}"
