"""Tests for T3 — applying a clip template in the render pipeline.

Covers the verifiable, FFmpeg-free units:
- template → render plan mapping (incl. no-regression vs the current splitscreen style)
- split-height math driven by wide_height_ratio (default reproduces 608/1312)
- per-job template_id validation (unknown → HTTP 422)
- constructor wiring of template_id through SingleVideoProcessor → BatchProcessor
"""

from datetime import datetime

import pytest

from packages.clips.subtitles.generator import STYLES
from packages.clips.templates.builtins import get_builtin
from packages.clips.templates.models import ClipTemplate, LayoutSpec, SubtitleSpec


def _now() -> str:
    return datetime(2026, 1, 1).isoformat()


# ── render plan mapping ──────────────────────────────────────────────────────


def test_resolve_default_template_matches_current_splitscreen_style():
    """No-regression: the splitscreen built-in must map to the exact SubtitleStyle
    the pipeline used before templates, with cumulative animation / 5 words."""
    from packages.clips.templates.render import template_to_render_plan

    plan = template_to_render_plan(get_builtin("splitscreen"))

    assert plan.style == STYLES["splitscreen"]
    assert plan.animation == "cumulative"
    assert plan.words_per_line == 5
    assert plan.layout_type == "split"
    # The default ratio must reproduce the historical 608px wide shot.
    assert round(1920 * plan.wide_height_ratio) == 608


def test_render_plan_maps_custom_subtitle_fields():
    from packages.clips.templates.render import template_to_render_plan

    template = ClipTemplate(
        id="my-brand",
        name="My Brand",
        created_at=_now(),
        updated_at=_now(),
        subtitles=SubtitleSpec(
            font_name="Impact", font_size=64, animation="karaoke", words_per_line=3
        ),
        layout=LayoutSpec(type="fullscreen"),
    )

    plan = template_to_render_plan(template)

    assert plan.style.font_name == "Impact"
    assert plan.style.font_size == 64
    assert plan.animation == "karaoke"
    assert plan.words_per_line == 3
    assert plan.layout_type == "fullscreen"


# ── split-height math ────────────────────────────────────────────────────────


def test_compute_split_heights_default_reproduces_608_1312():
    from packages.clips.vision.reframer import compute_split_heights

    wide, closeup = compute_split_heights(608 / 1920)
    assert wide == 608
    assert closeup == 1312
    assert wide + closeup == 1920


def test_compute_split_heights_scales_with_ratio():
    from packages.clips.vision.reframer import compute_split_heights

    wide, closeup = compute_split_heights(0.40)
    assert wide + closeup == 1920
    assert wide % 2 == 0 and closeup % 2 == 0
    # A bigger ratio means a taller wide shot than the default.
    assert wide > 608


# ── per-job template validation ──────────────────────────────────────────────


def test_resolve_template_or_422_unknown_raises(tmp_path):
    from fastapi import HTTPException

    from packages.clips.templates.store import TemplateStore
    from server.routes.clips import _resolve_template_or_422

    store = TemplateStore(tmp_path)
    with pytest.raises(HTTPException) as exc:
        _resolve_template_or_422(store, "does-not-exist")
    assert exc.value.status_code == 422


def test_resolve_template_or_422_known_returns_id(tmp_path):
    from packages.clips.templates.store import TemplateStore
    from server.routes.clips import _resolve_template_or_422

    store = TemplateStore(tmp_path)
    # Built-in resolves fine.
    assert _resolve_template_or_422(store, "splitscreen") == "splitscreen"
    # None is allowed (falls back to the profile default downstream).
    assert _resolve_template_or_422(store, None) is None


# ── constructor wiring ───────────────────────────────────────────────────────


def test_single_video_processor_stores_template_id(tmp_path):
    from server.processor import SingleVideoProcessor

    proc = SingleVideoProcessor(output_dir=tmp_path, template_id="my-brand")
    assert proc.template_id == "my-brand"


def test_single_video_processor_defaults_template_id_none(tmp_path):
    from server.processor import SingleVideoProcessor

    proc = SingleVideoProcessor(output_dir=tmp_path)
    assert proc.template_id is None
