"""T9 — Font fidelity: detect which fonts the machine actually has installed.

The ASS render can only honor a font that exists on the machine; otherwise it
silently falls back. These helpers let the editor warn the user instead of
promising a font the render won't use. Pure detection — no rendering here.
"""

from packages.clips.templates.fonts import (
    is_font_installed,
    list_installed_fonts,
)


def test_list_installed_fonts_nonempty_and_strings():
    fonts = list_installed_fonts()
    assert isinstance(fonts, (list, tuple))
    assert len(fonts) > 0, "every OS ships with at least one font"
    assert all(isinstance(f, str) and f for f in fonts)


def test_is_font_installed_true_for_a_listed_font():
    # Round-trip: anything the detector reports as present must read back True.
    fonts = list_installed_fonts()
    assert is_font_installed(fonts[0]) is True


def test_is_font_installed_false_for_made_up_name():
    assert is_font_installed("Zzz Definitely Not A Real Font 99173") is False


def test_is_font_installed_is_case_and_space_insensitive():
    name = list_installed_fonts()[0]
    assert is_font_installed(f"  {name.upper()}  ") is True


def test_is_font_installed_empty_name_is_false():
    assert is_font_installed("") is False
    assert is_font_installed("   ") is False
