"""Still-frame previews of the close-up crop, for the pre-render framing gate.

Rendering a clip to judge its framing costs ~30s; judging it from a single
frame costs ~2s, and the crop geometry is identical either way. Face detection
is the expensive half, so detections are cached per episode: after the first
preview, moving the framing slider only re-runs the (pure) crop math and one
FFmpeg frame grab.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

from packages.clips.templates.layout import DEFAULT_SAFE_ZONE_MULT


def _detections_to_json(detections) -> list[dict]:
    return [asdict(d) for d in detections]


def _detections_from_json(raw: list[dict]) -> list:
    from packages.clips.vision.face_tracker import FaceDetection

    out = []
    for d in raw:
        try:
            out.append(FaceDetection(**d))
        except TypeError:
            continue
    return out


def _load_or_detect(video_path: Path, start: float, end: float, cache_path: Path | None):
    """Face detections for [start, end], reusing a cached scan when present."""
    if cache_path and cache_path.exists():
        try:
            payload = json.loads(cache_path.read_text())
            if (
                abs(payload.get("start", -1) - start) < 0.01
                and abs(payload.get("end", -1) - end) < 0.01
            ):
                return _detections_from_json(payload.get("detections", []))
        except Exception:
            pass  # unreadable cache is just a cache miss

    from packages.clips.vision.face_tracker import FaceTracker

    detections = FaceTracker(sample_fps=2.0).detect_faces(video_path, start, end)
    if cache_path:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(
                    {"start": start, "end": end, "detections": _detections_to_json(detections)}
                )
            )
        except Exception:
            pass  # a preview must not fail over a cache write
    return detections


def _source_size(video_path: Path) -> tuple[int, int]:
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    out = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(video_path)],
        capture_output=True, text=True, timeout=30,
    )
    w, h = out.stdout.strip().split("x")[:2]
    return int(w), int(h)


def compute_crop_rect(
    detections,
    src_w: int,
    src_h: int,
    safe_zone_mult: float,
    out_w: int = 1080,
    out_h: int = 1920,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> dict:
    """The crop rectangle the render would use, in source pixels.

    Mirrors ``VideoReframer.reframe_dynamic``: a full-height 9:16 window scaled
    by the safe-zone zoom, centred on the dominant face.
    """
    from packages.clips.vision.face_tracker import FaceTracker

    try:
        zoom = FaceTracker.compute_safe_zoom(detections, src_h, safe_zone_mult=safe_zone_mult)
    except Exception:
        zoom = 0.7

    target_aspect = out_w / out_h
    crop_h = src_h
    crop_w = int(crop_h * target_aspect)
    if crop_w > src_w:
        crop_w = src_w
        crop_h = int(crop_w / target_aspect)

    crop_w = min(int(crop_w * zoom), src_w)
    crop_h = min(int(crop_h * zoom), src_h)
    crop_w -= crop_w % 2
    crop_h -= crop_h % 2

    # Centre on the biggest detected face (the speaker the crop will follow).
    cx, cy = src_w // 2, src_h // 2
    if detections:
        face = max(detections, key=lambda d: d.height)
        cx = face.x + face.width // 2
        cy = face.y + face.height // 2

    cx += int(offset_x * crop_w)
    cy += int(offset_y * crop_h)
    x = max(0, min(cx - crop_w // 2, src_w - crop_w))
    y = max(0, min(cy - crop_h // 2, src_h - crop_h))
    return {"x": x, "y": y, "w": crop_w, "h": crop_h, "zoom": round(zoom, 4),
            "faces": len(detections)}


def build_framing_preview(
    video_path: Path | str,
    at_time: float,
    out_path: Path | str,
    *,
    safe_zone_mult: float = DEFAULT_SAFE_ZONE_MULT,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    cache_path: Path | str | None = None,
    out_w: int = 1080,
    out_h: int = 1920,
    window_s: float = 3.0,
) -> dict:
    """Write a 9:16 JPEG of the proposed crop at ``at_time``. Returns its geometry."""
    video_path, out_path = Path(video_path), Path(out_path)
    cache_path = Path(cache_path) if cache_path else None

    src_w, src_h = _source_size(video_path)
    start = max(0.0, at_time - window_s / 2)
    detections = _load_or_detect(video_path, start, start + window_s, cache_path)
    rect = compute_crop_rect(
        detections, src_w, src_h, safe_zone_mult, out_w, out_h, offset_x, offset_y
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-ss", str(at_time), "-i", str(video_path),
         "-frames:v", "1",
         "-vf", f"crop={rect['w']}:{rect['h']}:{rect['x']}:{rect['y']},scale={out_w}:{out_h}",
         "-q:v", "4", str(out_path)],
        check=True, capture_output=True, timeout=120,
    )
    return {**rect, "path": str(out_path), "safe_zone_mult": safe_zone_mult,
            "offset_x": offset_x, "offset_y": offset_y,
            "at_time": at_time, "src_w": src_w, "src_h": src_h}
