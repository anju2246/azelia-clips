"""Plan and build the intro/outro concat around a rendered clip (T12).

Pure planning (path resolution + ordering + missing-file warnings) is separated
from the FFmpeg command so it's unit-testable without running anything. Bumpers
of arbitrary size/codec are normalized to the clip canvas and re-encoded on
concat (the concat *demuxer* would choke on mismatched parameters).
"""

from __future__ import annotations

from pathlib import Path

OUT_W = 1080
OUT_H = 1920
FPS = 30

_CODEC_TAIL = [
    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
    "-c:a", "aac", "-b:a", "128k",
]


def _resolve(rel: str | None, data_dir) -> str | None:
    if not rel or data_dir is None:
        return None
    p = Path(data_dir) / rel
    return str(p) if p.is_file() else None


def build_concat_plan(bumpers, clip_path: str, data_dir) -> tuple[list[str], list[str]]:
    """Return (ordered_inputs, warnings).

    ordered_inputs is [intro?, clip, outro?] keeping only bumpers that exist.
    warnings names each configured bumper whose file was missing ("intro"/"outro").
    """
    if bumpers is None:
        return [clip_path], []

    warnings: list[str] = []
    inputs: list[str] = []

    intro_rel = getattr(bumpers, "intro_path", None)
    if intro_rel:
        intro = _resolve(intro_rel, data_dir)
        if intro:
            inputs.append(intro)
        else:
            warnings.append("intro")

    inputs.append(clip_path)

    outro_rel = getattr(bumpers, "outro_path", None)
    if outro_rel:
        outro = _resolve(outro_rel, data_dir)
        if outro:
            inputs.append(outro)
        else:
            warnings.append("outro")

    return inputs, warnings


def needs_concat(inputs: list[str]) -> bool:
    """True when there's more than just the clip to stitch."""
    return len(inputs) > 1


def build_concat_command(
    ffmpeg_exe: str,
    inputs: list[str],
    output: str,
    out_w: int = OUT_W,
    out_h: int = OUT_H,
    fps: int = FPS,
) -> list[str]:
    """FFmpeg command concatenating inputs, each normalized to the canvas.

    Each input is scaled+padded to out_w×out_h at a fixed fps so concat works
    regardless of the bumpers' original parameters.
    """
    cmd = [ffmpeg_exe, "-y"]
    for path in inputs:
        cmd += ["-i", path]

    parts = []
    for i in range(len(inputs)):
        parts.append(
            f"[{i}:v]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
            f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{i}];"
            f"[{i}:a]aresample=async=1[a{i}]"
        )
    streams = "".join(f"[v{i}][a{i}]" for i in range(len(inputs)))
    filtergraph = ";".join(parts) + f";{streams}concat=n={len(inputs)}:v=1:a=1[v][a]"

    cmd += [
        "-filter_complex", filtergraph,
        "-map", "[v]", "-map", "[a]",
        *_CODEC_TAIL,
        output,
    ]
    return cmd
