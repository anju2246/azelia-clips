"""Pure builders for the subtitle-burn FFmpeg command and its optional overlays.

Kept free of subprocess/FFmpeg execution so the exact command — including the
branding logo overlay (T10) and progress bar (T11) — is unit-testable. With no
extensions enabled the command is byte-for-byte the historical burn command, so
existing renders are unaffected.
"""

from __future__ import annotations

from pathlib import Path

# Output canvas (fixed in v1, see LayoutSpec).
OUT_W = 1080
OUT_H = 1920

_OVERLAY_POS = {
    "top-left": "{m}:{m}",
    "top-right": "W-w-{m}:{m}",
    "bottom-left": "{m}:H-h-{m}",
    "bottom-right": "W-w-{m}:H-h-{m}",
}

_CODEC_TAIL = [
    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
    "-c:a", "aac", "-b:a", "128k",
]


def resolve_logo(branding, data_dir) -> str | None:
    """Absolute path to the logo if it exists on disk, else None (skip overlay)."""
    if branding is None or not getattr(branding, "logo_path", None) or data_dir is None:
        return None
    candidate = Path(data_dir) / branding.logo_path
    return str(candidate) if candidate.is_file() else None


def progress_bar_filter(spec, out_w: int, out_h: int, duration: float | None) -> str | None:
    """A drawbox whose filled width grows 0→full across the clip (T11).

    Returns a filter string for the ``-vf``/filter_complex chain, or None when
    disabled. ``duration`` (clip length, seconds) anchors the growth; without it
    we can't compute the rate, so we no-op.
    """
    if spec is None or not getattr(spec, "enabled", False) or not duration:
        return None
    from packages.clips.templates.colors import ass_to_ffmpeg_hex

    h = int(getattr(spec, "height", 12))
    y = 0 if getattr(spec, "position", "bottom") == "top" else out_h - h
    color = ass_to_ffmpeg_hex(getattr(spec, "color", "&H0000FFFF"))
    # w grows with presentation time t over the clip duration.
    return f"drawbox=x=0:y={y}:w=iw*t/{duration:.3f}:h={h}:color={color}@1:t=fill"


def build_burn_command(
    ffmpeg_exe: str,
    video: str,
    ass_path: str,
    output: str,
    *,
    branding=None,
    progress_bar=None,
    data_dir=None,
    out_w: int = OUT_W,
    out_h: int = OUT_H,
    duration: float | None = None,
) -> list[str]:
    """Build the FFmpeg arg list to burn subtitles plus optional overlays.

    No branding and no progress bar → the exact historical command.
    """
    pb = progress_bar_filter(progress_bar, out_w, out_h, duration)
    logo = resolve_logo(branding, data_dir)

    sub_chain = f"ass={ass_path}"
    if pb:
        sub_chain += f",{pb}"

    if logo is None:
        return [
            ffmpeg_exe, "-y",
            "-i", video,
            "-vf", sub_chain,
            *_CODEC_TAIL,
            output,
        ]

    # Logo overlay needs a second input and a filter graph.
    lw = max(1, int(out_w * float(getattr(branding, "scale", 0.10))))
    logo_chain = f"[1:v]scale={lw}:-1"
    opacity = float(getattr(branding, "opacity", 1.0))
    if opacity < 1.0:
        logo_chain += f",format=rgba,colorchannelmixer=aa={opacity:g}"
    logo_chain += "[lg]"

    pos = _OVERLAY_POS[getattr(branding, "position", "top-right")].format(
        m=int(getattr(branding, "margin", 40))
    )
    fc = f"[0:v]{sub_chain}[v0];{logo_chain};[v0][lg]overlay={pos}[v]"

    return [
        ffmpeg_exe, "-y",
        "-i", video,
        "-i", logo,
        "-filter_complex", fc,
        "-map", "[v]", "-map", "0:a?",
        *_CODEC_TAIL,
        output,
    ]
