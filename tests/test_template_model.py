"""Tests for ClipTemplate domain models (T1 - RED phase).

All tests are expected to FAIL until the implementation is written.
"""

import pytest
from pydantic import ValidationError
from datetime import datetime

from packages.clips.templates.models import (
    ClipTemplate,
    SubtitleSpec,
    LayoutSpec,
    SCHEMA_VERSION,
)


def test_clip_template_rejects_out_of_range_font_size():
    """Font size must be in range 12-200."""
    # Test below minimum
    with pytest.raises(ValidationError) as exc_info:
        SubtitleSpec(font_size=5)
    assert "font_size" in str(exc_info.value)

    # Test above maximum
    with pytest.raises(ValidationError) as exc_info:
        SubtitleSpec(font_size=500)
    assert "font_size" in str(exc_info.value)


def test_clip_template_rejects_invalid_ass_color():
    """ASS colors must match the pattern ^&H[0-9A-Fa-f]{8}$."""
    with pytest.raises(ValidationError) as exc_info:
        SubtitleSpec(primary_color="red")
    assert "primary_color" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        SubtitleSpec(secondary_color="#FFFFFF")
    assert "secondary_color" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        SubtitleSpec(outline_color="&H00FFFF")  # Too short
    assert "outline_color" in str(exc_info.value)


def test_clip_template_validates_animation_enum():
    """Animation must be one of the allowed literal values."""
    with pytest.raises(ValidationError) as exc_info:
        SubtitleSpec(animation="fade")  # type: ignore
    assert "animation" in str(exc_info.value)


def test_clip_template_validates_wide_height_ratio_range():
    """wide_height_ratio must be between 0.20 and 0.50."""
    # Test below minimum
    with pytest.raises(ValidationError) as exc_info:
        LayoutSpec(wide_height_ratio=0.10)
    assert "wide_height_ratio" in str(exc_info.value)

    # Test above maximum
    with pytest.raises(ValidationError) as exc_info:
        LayoutSpec(wide_height_ratio=0.75)
    assert "wide_height_ratio" in str(exc_info.value)


def test_azt_roundtrip_preserves_fields():
    """Serializing to .azt bytes and back should preserve all fields."""
    now = datetime.utcnow().isoformat()
    original = ClipTemplate(
        id="test-template",
        name="Test Template",
        description="A test template",
        author="Test Author",
        is_builtin=False,
        created_at=now,
        updated_at=now,
        subtitles=SubtitleSpec(
            font_name="Impact",
            font_size=64,
            primary_color="&H00FFFFFF",
            secondary_color="&H0000FFFF",
            animation="karaoke",
            words_per_line=3,
        ),
        layout=LayoutSpec(
            type="split",
            wide_height_ratio=0.40,
        ),
    )

    # Round-trip
    azt_bytes = original.to_azt_bytes()
    restored = ClipTemplate.from_azt_bytes(azt_bytes)

    # All fields should match
    assert restored.schema_version == SCHEMA_VERSION
    assert restored.id == original.id
    assert restored.name == original.name
    assert restored.description == original.description
    assert restored.author == original.author
    assert restored.is_builtin == original.is_builtin
    assert restored.created_at == original.created_at
    assert restored.updated_at == original.updated_at
    assert restored.subtitles.font_name == original.subtitles.font_name
    assert restored.subtitles.font_size == original.subtitles.font_size
    assert restored.subtitles.animation == original.subtitles.animation
    assert restored.layout.type == original.layout.type
    assert restored.layout.wide_height_ratio == original.layout.wide_height_ratio
