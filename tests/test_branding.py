from ai2 import branding


def test_marks_are_plain_when_color_off():
    # No ANSI escapes when color is disabled (piped output stays grep-friendly).
    for s in (branding.inline(color=False), branding.compact(color=False),
              branding.icon(color=False), branding.full(color=False)):
        assert "\033[" not in s


def test_color_adds_escapes():
    assert "\033[" in branding.compact(color=True)


def test_full_lockup_has_tagline_and_attribution():
    full = branding.full(color=False)
    assert branding.TAGLINE in full
    assert branding.ATTRIBUTION in full
    assert "> AI-2" in full


def test_inline_is_one_line():
    assert "\n" not in branding.inline(color=False)
