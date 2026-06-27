"""T12 — Intro / outro bumpers concatenated around the clip.

The concat plan is pure (no FFmpeg): it resolves the bumper paths, orders them
[intro, clip, outro], skips any that don't exist on disk (non-fatal warning),
and tells the caller whether a concat step is needed at all. Paths are stored
relative to the profile data dir; absolute/traversing paths are rejected.
"""

import pytest
from pydantic import ValidationError

from packages.clips.templates.bumpers import build_concat_plan, needs_concat
from packages.clips.templates.models import BumpersSpec, ClipTemplate


def test_bumpers_rejects_path_outside_profile():
    with pytest.raises(ValidationError):
        BumpersSpec(intro_path="/etc/evil.mp4")
    with pytest.raises(ValidationError):
        BumpersSpec(outro_path="../escape.mp4")


def test_no_bumpers_no_concat_step():
    inputs, warnings = build_concat_plan(None, "/clip.mp4", "/data")
    assert inputs == ["/clip.mp4"]
    assert warnings == []
    assert needs_concat(inputs) is False


def test_concat_plan_orders_intro_clip_outro(tmp_path):
    (tmp_path / "intro.mp4").write_bytes(b"\x00")
    (tmp_path / "outro.mp4").write_bytes(b"\x00")
    spec = BumpersSpec(intro_path="intro.mp4", outro_path="outro.mp4")
    inputs, warnings = build_concat_plan(spec, "/clip.mp4", tmp_path)
    assert inputs == [str(tmp_path / "intro.mp4"), "/clip.mp4", str(tmp_path / "outro.mp4")]
    assert warnings == []
    assert needs_concat(inputs) is True


def test_missing_bumper_path_skipped_with_warning(tmp_path):
    (tmp_path / "outro.mp4").write_bytes(b"\x00")
    spec = BumpersSpec(intro_path="ghost.mp4", outro_path="outro.mp4")
    inputs, warnings = build_concat_plan(spec, "/clip.mp4", tmp_path)
    # intro missing → dropped; outro present → kept.
    assert inputs == ["/clip.mp4", str(tmp_path / "outro.mp4")]
    assert "intro" in warnings
    assert needs_concat(inputs) is True


def test_v1_azt_loads_with_bumpers_none():
    t = ClipTemplate.model_validate_json(
        '{"schema_version":1,"id":"x","name":"X","created_at":"2025-01-01T00:00:00",'
        '"updated_at":"2025-01-01T00:00:00",'
        '"subtitles":{"font_name":"Arial","font_size":52,"primary_color":"&H00FFFFFF",'
        '"secondary_color":"&H0000FFFF","outline_color":"&H00000000","back_color":"&H80000000",'
        '"bold":true,"outline":3,"shadow":2,"alignment":2,"margin_v":50,'
        '"animation":"cumulative","words_per_line":5},'
        '"layout":{"type":"split","output_width":1080,"output_height":1920,"wide_height_ratio":0.3167}}'
    )
    assert t.bumpers is None
