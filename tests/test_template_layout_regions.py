"""T16 — Region-based layouts (multi-speaker).

LayoutSpec gains an optional region model so a template can express more than
the single split/fullscreen: 2-guest stacked, grids, etc. Back-compat: the
existing `split`/`fullscreen` types still resolve to their canonical regions, so
old .azt templates render identically. Pure geometry — no FFmpeg here.
"""

import pytest
from pydantic import ValidationError

from packages.clips.templates.models import ClipTemplate, LayoutSpec, Region, RegionSource
from packages.clips.templates.layout import resolve_regions, two_guest_split, grid_layout


def test_fullscreen_resolves_to_one_active_speaker_region():
    regions = resolve_regions(LayoutSpec(type="fullscreen"))
    assert len(regions) == 1
    r = regions[0]
    assert (r.x, r.y, r.w, r.h) == (0.0, 0.0, 1.0, 1.0)
    assert r.source.mode == "active_speaker"


def test_split_resolves_to_closeup_over_wide():
    regions = resolve_regions(LayoutSpec(type="split", wide_height_ratio=0.32))
    assert len(regions) == 2
    top, bottom = regions
    assert top.source.mode == "active_speaker"
    assert bottom.source.mode == "wide"
    # the wide band height matches the ratio; together they fill the frame
    assert round(bottom.h, 4) == 0.32
    assert round(top.h + bottom.h, 4) == 1.0
    assert round(top.y, 4) == 0.0
    assert round(bottom.y, 4) == round(top.h, 4)


def test_two_guest_split_stacks_two_locked_speakers():
    layout = two_guest_split("host", "guest")
    assert layout.type == "regions"
    regions = resolve_regions(layout)
    assert len(regions) == 2
    top, bottom = regions
    assert top.source.mode == "speaker" and top.source.speaker_ref == "host"
    assert bottom.source.mode == "speaker" and bottom.source.speaker_ref == "guest"
    assert round(top.h, 4) == 0.5 and round(bottom.h, 4) == 0.5
    assert round(bottom.y, 4) == 0.5


def test_grid_layout_tiles_n_speakers():
    layout = grid_layout(["a", "b", "c", "d"])
    regions = resolve_regions(layout)
    assert len(regions) == 4
    # 2x2 grid: each tile half-width, half-height
    assert all(round(r.w, 4) == 0.5 and round(r.h, 4) == 0.5 for r in regions)
    # tiles cover all four quadrants
    corners = {(round(r.x, 2), round(r.y, 2)) for r in regions}
    assert corners == {(0.0, 0.0), (0.5, 0.0), (0.0, 0.5), (0.5, 0.5)}


def test_region_rejects_out_of_bounds():
    with pytest.raises(ValidationError):
        Region(x=0.0, y=0.0, w=1.5, h=1.0)  # w>1
    with pytest.raises(ValidationError):
        Region(x=-0.1, y=0.0, w=0.5, h=0.5)  # x<0


def test_regions_type_requires_nonempty_regions():
    with pytest.raises(ValidationError):
        LayoutSpec(type="regions", regions=[])


def test_v1_azt_loads_with_default_split_regions():
    """An old split template (no regions field) still resolves to closeup+wide."""
    t = ClipTemplate.model_validate_json(
        '{"schema_version":1,"id":"x","name":"X","created_at":"2025-01-01T00:00:00",'
        '"updated_at":"2025-01-01T00:00:00",'
        '"subtitles":{"font_name":"Arial","font_size":52,"primary_color":"&H00FFFFFF",'
        '"secondary_color":"&H0000FFFF","outline_color":"&H00000000","back_color":"&H80000000",'
        '"bold":true,"outline":3,"shadow":2,"alignment":2,"margin_v":50,'
        '"animation":"cumulative","words_per_line":5},'
        '"layout":{"type":"split","output_width":1080,"output_height":1920,"wide_height_ratio":0.3167}}'
    )
    assert t.layout.regions == []
    regions = resolve_regions(t.layout)
    assert len(regions) == 2 and regions[1].source.mode == "wide"


def test_render_plan_carries_regions_only_for_regions_type():
    """T18 — the pipeline gets resolved regions for 'regions', None otherwise."""
    from datetime import datetime
    from packages.clips.templates.render import template_to_render_plan

    def _mk(layout):
        now = datetime(2026, 1, 1).isoformat()
        from packages.clips.templates.models import SubtitleSpec
        return ClipTemplate(id="t", name="T", created_at=now, updated_at=now,
                            subtitles=SubtitleSpec(), layout=layout)

    assert template_to_render_plan(_mk(LayoutSpec(type="split"))).regions is None
    assert template_to_render_plan(_mk(LayoutSpec(type="fullscreen"))).regions is None
    plan = template_to_render_plan(_mk(two_guest_split("host", "guest")))
    assert plan.regions is not None and len(plan.regions) == 2
    assert plan.regions[0].source.mode == "speaker"
