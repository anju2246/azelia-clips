"""Resolve a LayoutSpec into concrete output regions, plus canonical builders.

Pure geometry: turns the high-level layout (split / fullscreen / regions) into
an ordered list of normalized rectangles each bound to a video source. The
reframer compositor consumes this; keeping it here makes the geometry testable
without FFmpeg, and lets the web preview render the exact same layout.
"""

from __future__ import annotations

import math

from packages.clips.templates.models import LayoutSpec, Region, RegionSource


def resolve_regions(layout: LayoutSpec) -> list[Region]:
    """The effective region list for any layout type.

    ``split``/``fullscreen`` map to their canonical regions so existing
    templates render identically; ``regions`` returns its own list.
    """
    if layout.type == "fullscreen":
        return [Region(x=0.0, y=0.0, w=1.0, h=1.0, source=RegionSource(mode="active_speaker"))]
    if layout.type == "split":
        wide_h = layout.wide_height_ratio
        closeup_h = 1.0 - wide_h
        return [
            Region(x=0.0, y=0.0, w=1.0, h=closeup_h, source=RegionSource(mode="active_speaker")),
            Region(x=0.0, y=closeup_h, w=1.0, h=wide_h, source=RegionSource(mode="wide")),
        ]
    return list(layout.regions)


def two_guest_split(top_ref: str, bottom_ref: str) -> LayoutSpec:
    """A 2-guest stacked split: each speaker locked to a half of the frame."""
    return LayoutSpec(
        type="regions",
        regions=[
            Region(x=0.0, y=0.0, w=1.0, h=0.5, source=RegionSource(mode="speaker", speaker_ref=top_ref)),
            Region(x=0.0, y=0.5, w=1.0, h=0.5, source=RegionSource(mode="speaker", speaker_ref=bottom_ref)),
        ],
    )


def grid_layout(speaker_refs: list[str]) -> LayoutSpec:
    """A grid of locked speakers (2×2 for up to 4; columns = ceil(sqrt(n)))."""
    n = len(speaker_refs)
    if n == 0:
        raise ValueError("grid_layout needs at least one speaker")
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    w, h = 1.0 / cols, 1.0 / rows
    regions = []
    for i, ref in enumerate(speaker_refs):
        r, c = divmod(i, cols)
        regions.append(
            Region(x=c * w, y=r * h, w=w, h=h, source=RegionSource(mode="speaker", speaker_ref=ref))
        )
    return LayoutSpec(type="regions", regions=regions)
