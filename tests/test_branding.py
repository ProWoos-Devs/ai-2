from ai2 import branding


def test_marks_are_plain_when_color_off():
    # No ANSI escapes when color is disabled (piped output stays grep-friendly).
    for s in (branding.inline(color=False), branding.compact(color=False),
              branding.icon(color=False), branding.full(color=False)):
        assert "\033[" not in s


def test_color_adds_escapes():
    assert "\033[" in branding.compact(color=True)


def test_full_lockup_is_the_bare_box():
    full = branding.full(color=False)
    assert "brain" not in full          # tagline dropped 2026-08-16
    assert "Artix" not in full          # attribution line dropped 2026-08-16
    assert full == branding.compact(color=False)
    assert "> AI-2" in full


def test_inline_is_one_line():
    assert "\n" not in branding.inline(color=False)
