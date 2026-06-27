"""T11 — Progress bar: a bar that grows 0→100% across the clip via drawbox.

Default-off keeps the burn command unchanged. The bar width is a function of
presentation time, so it animates. ASS colors (ABGR) must convert to FFmpeg's
RRGGBB byte order — a classic place to get the bytes backwards.
"""

from packages.clips.templates.colors import ass_to_ffmpeg_hex
from packages.clips.templates.ffmpeg_filters import build_burn_command
from packages.clips.templates.models import ClipTemplate, ProgressBarSpec


def test_ass_color_to_ffmpeg_hex_byte_order():
    # ASS is &HAABBGGRR. Pure red in ASS is &H000000FF → FFmpeg 0xFF0000.
    assert ass_to_ffmpeg_hex("&H000000FF") == "0xFF0000"
    # Pure blue in ASS is &H00FF0000 → FFmpeg 0x0000FF.
    assert ass_to_ffmpeg_hex("&H00FF0000") == "0x0000FF"
    # Yellow (&H0000FFFF) → 0xFFFF00.
    assert ass_to_ffmpeg_hex("&H0000FFFF") == "0xFFFF00"


def test_progress_bar_disabled_adds_no_filter():
    base = build_burn_command("ffmpeg", "/i.mp4", "/s.ass", "/o.mp4")
    off = build_burn_command(
        "ffmpeg", "/i.mp4", "/s.ass", "/o.mp4",
        progress_bar=ProgressBarSpec(enabled=False), duration=30.0,
    )
    assert off == base
    assert "drawbox" not in " ".join(off)


def test_progress_bar_filter_width_is_time_dependent():
    cmd = build_burn_command(
        "ffmpeg", "/i.mp4", "/s.ass", "/o.mp4",
        progress_bar=ProgressBarSpec(enabled=True, height=14, position="bottom"),
        duration=30.0,
    )
    joined = " ".join(cmd)
    assert "drawbox" in joined
    # width depends on presentation time t and the clip duration.
    assert "iw*t/30.000" in joined
    # still a single -vf chain (no extra inputs needed for a drawbox)
    assert "-filter_complex" not in cmd
    assert "ass=/s.ass,drawbox" in joined


def test_progress_bar_without_duration_is_noop():
    cmd = build_burn_command(
        "ffmpeg", "/i.mp4", "/s.ass", "/o.mp4",
        progress_bar=ProgressBarSpec(enabled=True), duration=None,
    )
    assert "drawbox" not in " ".join(cmd)


def test_progressbar_validates_and_template_default_none():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ProgressBarSpec(color="not-ass")
    t = ClipTemplate.model_validate_json(
        '{"schema_version":1,"id":"x","name":"X","created_at":"2025-01-01T00:00:00",'
        '"updated_at":"2025-01-01T00:00:00",'
        '"subtitles":{"font_name":"Arial","font_size":52,"primary_color":"&H00FFFFFF",'
        '"secondary_color":"&H0000FFFF","outline_color":"&H00000000","back_color":"&H80000000",'
        '"bold":true,"outline":3,"shadow":2,"alignment":2,"margin_v":50,'
        '"animation":"cumulative","words_per_line":5},'
        '"layout":{"type":"split","output_width":1080,"output_height":1920,"wide_height_ratio":0.3167}}'
    )
    assert t.progress_bar is None
