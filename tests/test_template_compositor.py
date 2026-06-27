"""T17 — Pure FFmpeg compositor for region layouts.

Given N pre-rendered region clips + their normalized rects, build the
filter_complex that scales each onto its rect over a canvas and muxes the
source audio. Pure: asserts on the command, runs no ffmpeg.
"""

from packages.clips.templates.compositor import build_composite_command
from packages.clips.templates.layout import resolve_regions, two_guest_split


def test_composite_two_regions_overlays_each_on_canvas():
    regions = resolve_regions(two_guest_split("host", "guest"))
    cmd = build_composite_command(
        "ffmpeg",
        ["/tmp/r0.mp4", "/tmp/r1.mp4"],
        regions,
        audio_source="/tmp/src.mp4",
        output="/tmp/out.mp4",
        out_w=1080,
        out_h=1920,
    )
    joined = " ".join(cmd)
    fc = cmd[cmd.index("-filter_complex") + 1]
    # one overlay per region
    assert fc.count("overlay=") == 2
    # a black canvas at the output size
    assert "color=" in fc and "1080x1920" in fc
    # each region clip is an input, plus the audio source
    assert cmd.count("-i") == 3
    assert "/tmp/r0.mp4" in cmd and "/tmp/r1.mp4" in cmd and "/tmp/src.mp4" in cmd
    # two stacked halves → each scaled to 1080x960, placed at y=0 and y=960
    assert "scale=1080:960" in fc
    assert "overlay=0:0" in fc
    assert "overlay=0:960" in fc
    # audio + final video are mapped
    assert "-map" in cmd


def test_composite_dims_are_even():
    # An odd split would yield odd pixel heights; the builder must round to even.
    from packages.clips.templates.models import LayoutSpec, Region, RegionSource

    layout = LayoutSpec(
        type="regions",
        regions=[
            Region(x=0, y=0, w=1, h=0.333, source=RegionSource(mode="speaker", speaker_ref="a")),
            Region(x=0, y=0.333, w=1, h=0.667, source=RegionSource(mode="speaker", speaker_ref="b")),
        ],
    )
    cmd = build_composite_command(
        "ffmpeg", ["/a.mp4", "/b.mp4"], resolve_regions(layout),
        audio_source="/s.mp4", output="/o.mp4",
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    import re

    for w, h in re.findall(r"scale=(\d+):(\d+)", fc):
        assert int(w) % 2 == 0 and int(h) % 2 == 0
