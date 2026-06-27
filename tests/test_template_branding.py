"""T10 — Logo / watermark branding overlay.

BrandingSpec adds an optional logo overlaid via FFmpeg. Default-off keeps the
burn command byte-for-byte unchanged (no-regression). The logo path is stored
relative to the profile data dir; absolute or traversing paths are rejected at
validation. The FFmpeg command is built by a pure helper so we can assert on it
without running ffmpeg.
"""

import pytest
from pydantic import ValidationError

from packages.clips.templates.models import BrandingSpec, ClipTemplate
from packages.clips.templates.ffmpeg_filters import build_burn_command


# ── model validation ─────────────────────────────────────────────────────────


def test_branding_accepts_relative_path_and_ranges():
    b = BrandingSpec(logo_path="brand/logo.png", scale=0.12, opacity=0.8, margin=30)
    assert b.logo_path == "brand/logo.png"
    assert b.position == "top-right"  # default


def test_branding_rejects_path_outside_profile():
    # Absolute path escapes the profile data dir.
    with pytest.raises(ValidationError):
        BrandingSpec(logo_path="/etc/passwd")
    # Parent-traversal escapes it too.
    with pytest.raises(ValidationError):
        BrandingSpec(logo_path="../../secrets/logo.png")


def test_branding_rejects_out_of_range():
    with pytest.raises(ValidationError):
        BrandingSpec(scale=0.5)
    with pytest.raises(ValidationError):
        BrandingSpec(opacity=2.0)


def test_v1_azt_loads_with_branding_none():
    """A template without branding loads fine and defaults branding to None."""
    t = ClipTemplate.model_validate_json(
        '{"schema_version":1,"id":"x","name":"X","created_at":"2025-01-01T00:00:00",'
        '"updated_at":"2025-01-01T00:00:00",'
        '"subtitles":' + _SUBS + ',"layout":' + _LAYOUT + "}"
    )
    assert t.branding is None


# ── command construction ─────────────────────────────────────────────────────


def test_no_branding_keeps_render_command_unchanged():
    """Without branding (or progress bar) the command equals today's burn cmd."""
    cmd = build_burn_command("ffmpeg", "/tmp/in.mp4", "/tmp/subs.ass", "/tmp/out.mp4")
    assert cmd == [
        "ffmpeg", "-y",
        "-i", "/tmp/in.mp4",
        "-vf", "ass=/tmp/subs.ass",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "/tmp/out.mp4",
    ]


def test_render_plan_includes_overlay_when_logo_present(tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG\r\n")
    branding = BrandingSpec(logo_path="logo.png", position="bottom-right", scale=0.1, margin=40)
    cmd = build_burn_command(
        "ffmpeg", "/tmp/in.mp4", "/tmp/subs.ass", "/tmp/out.mp4",
        branding=branding, data_dir=tmp_path,
    )
    joined = " ".join(cmd)
    # Second input is the resolved logo, composed via filter_complex overlay.
    assert "-filter_complex" in cmd
    assert "overlay=" in joined
    assert str(logo) in cmd
    assert "ass=/tmp/subs.ass" in joined  # subtitles still burned


def test_missing_logo_file_skips_overlay(tmp_path):
    """A logo path that doesn't exist on disk is skipped (non-fatal)."""
    branding = BrandingSpec(logo_path="nope.png")
    cmd = build_burn_command(
        "ffmpeg", "/tmp/in.mp4", "/tmp/subs.ass", "/tmp/out.mp4",
        branding=branding, data_dir=tmp_path,
    )
    assert "-filter_complex" not in cmd  # falls back to the plain -vf command


_SUBS = (
    '{"font_name":"Arial","font_size":52,"primary_color":"&H00FFFFFF",'
    '"secondary_color":"&H0000FFFF","outline_color":"&H00000000",'
    '"back_color":"&H80000000","bold":true,"outline":3,"shadow":2,'
    '"alignment":2,"margin_v":50,"animation":"cumulative","words_per_line":5}'
)
_LAYOUT = '{"type":"split","output_width":1080,"output_height":1920,"wide_height_ratio":0.3167}'
