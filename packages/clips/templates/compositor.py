"""Pure FFmpeg compositor for region-based layouts (T17).

Given pre-rendered region clips and their normalized rects, build the command
that lays each onto a canvas and muxes the (compressed/normalized) source audio.
No FFmpeg execution here so the filter graph is unit-testable; the reframer
renders each region then calls this.
"""

from __future__ import annotations

# Same audio chain the reframer already uses (compressor → EBU R128 loudnorm).
_AUDIO_FILTER = (
    "compand=attacks=0.05:decays=0.3:points=-80/-80|-45/-25|-20/-15|-5/-5|0/-3:gain=3,"
    "loudnorm=I=-16:TP=-1.5:LRA=7"
)


def _even(n: float) -> int:
    v = int(round(n))
    return v - (v % 2)


def build_composite_command(
    ffmpeg_exe: str,
    region_clips: list[str],
    regions: list,
    audio_source: str,
    output: str,
    out_w: int = 1080,
    out_h: int = 1920,
) -> list[str]:
    """Composite region clips onto a black canvas, mux normalized source audio.

    region_clips[i] is the already-reframed clip for regions[i]. Each is scaled
    to its rect's pixel size and overlaid at its rect's pixel origin.
    """
    if len(region_clips) != len(regions):
        raise ValueError("region_clips and regions must be the same length")

    cmd = [ffmpeg_exe, "-y"]
    for clip in region_clips:
        cmd += ["-i", clip]
    audio_idx = len(region_clips)
    cmd += ["-i", audio_source]

    steps = [f"color=c=black:s={out_w}x{out_h}:r=30[bg]"]
    prev = "bg"
    for i, r in enumerate(regions):
        w, h = _even(r.w * out_w), _even(r.h * out_h)
        x, y = _even(r.x * out_w), _even(r.y * out_h)
        out_label = f"c{i}"
        steps.append(f"[{i}:v]scale={w}:{h}[r{i}]")
        steps.append(f"[{prev}][r{i}]overlay={x}:{y}[{out_label}]")
        prev = out_label
    steps.append(f"[{audio_idx}:a]{_AUDIO_FILTER}[a]")

    cmd += [
        "-filter_complex", ";".join(steps),
        "-map", f"[{prev}]", "-map", "[a]",
        "-shortest",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        output,
    ]
    return cmd
