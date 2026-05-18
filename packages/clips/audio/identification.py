"""Pre-flight speaker identification — drives the L3 manual labeling UX.

When the user clicks "Extract Clips" on an episode and no labels exist
yet, we run this preflight to produce the artifacts the modal needs:

  - One face thumbnail per detected identity (`face_XX.jpg`).
  - One audio sample per diarized speaker (`speaker_XX.wav`).
  - A JSON manifest with the (face_id, speaker_id) pairs the user
    can match by clicking + naming.

Artifacts live under `{episode_folder}/.identification/`. They're a
one-time cost per episode (cached). After the user submits labels via
the modal, the per-clip face tracker uses the locked mapping instead
of mouth-motion guessing.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# We sample frames at this stride. 30 evenly distributed frames over a 30 min
# episode is enough to detect every persistent face cluster reliably without
# burning the user's time on the full 2 fps detection.
_PREFLIGHT_FRAME_COUNT = 30
_SAMPLE_DURATION_SEC = 6.5  # length of the audio sample per speaker


def _video_duration(video_path: Path) -> float:
    """ffprobe-based duration; falls back to 0 on failure."""
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(video_path),
            ],
            capture_output=True, text=True, timeout=15,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _extract_thumbnail(video_path: Path, timestamp: float, out_path: Path) -> bool:
    """Grab a single frame at `timestamp` seconds via ffmpeg. Returns True on success."""
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-ss", str(timestamp), "-i", str(video_path),
                "-frames:v", "1", "-q:v", "3", str(out_path),
            ],
            capture_output=True, check=True, timeout=15,
        )
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception as e:
        logger.warning("Thumbnail extraction failed at %.1fs: %s", timestamp, e)
        return False


def _crop_face_from_frame(
    frame_path: Path,
    bbox: tuple[int, int, int, int],
    out_path: Path,
    margin: float = 0.35,
) -> bool:
    """Crop a face from `frame_path` with `margin` extra context on each side.

    Keeps a chunky border so the modal shows hair/shoulders too, which is
    easier for the user to recognize than a tight face crop.
    """
    try:
        import cv2
        img = cv2.imread(str(frame_path))
        if img is None:
            return False
        h, w = img.shape[:2]
        x1, y1, x2, y2 = bbox
        bw, bh = x2 - x1, y2 - y1
        mx, my = int(bw * margin), int(bh * margin)
        cx1, cy1 = max(0, x1 - mx), max(0, y1 - my)
        cx2, cy2 = min(w, x2 + mx), min(h, y2 + my)
        crop = img[cy1:cy2, cx1:cx2]
        if crop.size == 0:
            return False
        # Cap the output at ~320 px wide so thumbnails are light over HTTP.
        target_w = 320
        if crop.shape[1] > target_w:
            scale = target_w / crop.shape[1]
            new_h = int(crop.shape[0] * scale)
            crop = cv2.resize(crop, (target_w, new_h), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(out_path), crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return True
    except Exception as e:
        logger.warning("Face crop failed: %s", e)
        return False


def detect_face_identities(
    video_path: Path,
    out_dir: Path,
    frame_count: int = _PREFLIGHT_FRAME_COUNT,
    max_identities: int = 4,
) -> dict[str, Path]:
    """Sample frames, run MTCNN+FaceNet, cluster, save thumbnails.

    Returns a dict mapping face_id → thumbnail path. Faces seen in only
    one sampled frame (probably noise — passers-by, motion blur, etc.)
    are dropped before returning.
    """
    from packages.clips.vision.face_tracker import FaceTracker

    duration = _video_duration(video_path)
    if duration <= 0:
        logger.error("Could not determine video duration")
        return {}

    out_dir.mkdir(parents=True, exist_ok=True)

    # Spread the sampled timestamps across the middle 90% of the video so
    # we skip credits/intros that often show the host's logo instead of a
    # person's face.
    inset = duration * 0.05
    timestamps = [
        inset + (duration - 2 * inset) * (i + 0.5) / frame_count
        for i in range(frame_count)
    ]

    # Reuse FaceTracker for detection (MTCNN+FaceNet) on each sampled frame.
    # We could call MTCNN directly but reusing the tracker means we
    # inherit identity clustering for free.
    tracker = FaceTracker(sample_fps=2.0)
    # The tracker's detect_faces() reads the FULL video; here we'd rather
    # detect on a small set of frames. So we sample frames to disk first
    # and then build a "mini video" or detect frame-by-frame.
    # Simplest: write frames to a temp folder and run MTCNN on each.

    # NOTE: frames are written to `out_dir/.frames/` instead of a
    # TemporaryDirectory because we need the frame files to OUTLIVE the
    # detection loop — cropping happens AFTER clustering, and tmp dirs
    # auto-delete on exit, leaving cv2.imread to silently fail. We clean
    # up these frames at the end.
    frames_dir = out_dir / ".frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    detections: list[dict] = []
    if True:  # keep structural scope so the rest of the body indents the same
        tmp = frames_dir
        # 1. Extract frames
        frame_paths: list[tuple[float, Path]] = []
        for i, ts in enumerate(timestamps):
            fp = tmp / f"f_{i:04d}.jpg"
            if _extract_thumbnail(video_path, ts, fp):
                frame_paths.append((ts, fp))
        if not frame_paths:
            logger.error("No frames could be sampled from the video")
            return {}

        # 2. MTCNN per frame + FaceNet embeddings
        try:
            import cv2
            from facenet_pytorch import MTCNN, InceptionResnetV1
            import torch
        except ImportError as e:
            logger.error("facenet_pytorch not installed: %s", e)
            return {}

        # Force CPU for the preflight pass. MPS adaptive pooling crashes on
        # input sizes that don't divide evenly by the pool kernel
        # (https://github.com/pytorch/pytorch/issues/96056), and MTCNN's
        # P-Net hits exactly that path on arbitrary frame dimensions. The
        # main FaceTracker happens to avoid it because it pre-resizes
        # frames consistently; the preflight pulls raw ffmpeg frames which
        # can be any size. Since this only runs once per episode (~30 s),
        # CPU is fine.
        device = "cpu"
        # post_process=True normalizes the cropped face tensor to the
        # range InceptionResnetV1 was trained on. Without it the
        # embeddings collapse — different people land at cosine sim
        # ~0.96, which makes the whole clustering useless. The
        # FaceTracker hits this same gotcha (its detect_faces() uses
        # the default post_process=True), so we mirror that.
        mtcnn = MTCNN(keep_all=True, device=device, post_process=True)
        embedder = InceptionResnetV1(pretrained="vggface2").eval().to(device)

        for ts, fp in frame_paths:
            img = cv2.imread(str(fp))
            if img is None:
                continue
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            boxes, probs = mtcnn.detect(rgb)
            if boxes is None:
                continue
            faces_t = mtcnn.extract(rgb, boxes, save_path=None)
            if faces_t is None:
                continue
            with torch.no_grad():
                embs = embedder(faces_t.to(device)).cpu().numpy()
            for box, prob, emb in zip(boxes, probs, embs):
                if prob is None or prob < 0.9:
                    continue
                x1, y1, x2, y2 = [int(v) for v in box]
                detections.append({
                    "timestamp": ts,
                    "frame_path": fp,
                    "bbox": (x1, y1, x2, y2),
                    "embedding": emb,
                    "prob": float(prob),
                })

    if not detections:
        logger.warning("No faces detected in any sampled frame")
        return {}

    # 3. Cluster by cosine similarity on the embeddings.
    import numpy as np
    embeddings = np.stack([d["embedding"] for d in detections])
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normalized = embeddings / np.clip(norms, 1e-6, None)

    cluster_ids: list[int] = [-1] * len(detections)
    centroids: list[np.ndarray] = []
    # FaceNet/VGGFace2 same-person cosine sim is typically 0.65-0.85;
    # different-person sits around 0.2-0.5. 0.65 errs slightly toward
    # under-merging — when a real person ends up split into 2-3
    # clusters because of lighting/angle drift, the UI lets the user
    # multi-select those phantoms onto the same speaker. Better than
    # the opposite failure (two distinct people merged into one),
    # which the user CAN'T fix from the modal.
    SIM_THRESHOLD = 0.65
    for i, e in enumerate(normalized):
        if not centroids:
            centroids.append(e.copy())
            cluster_ids[i] = 0
            continue
        sims = [float(np.dot(e, c)) for c in centroids]
        best_idx = int(np.argmax(sims))
        if sims[best_idx] >= SIM_THRESHOLD:
            cluster_ids[i] = best_idx
            # Update centroid as running mean
            n = sum(1 for cid in cluster_ids[:i] if cid == best_idx) + 1
            centroids[best_idx] = (centroids[best_idx] * (n - 1) + e) / n
        else:
            centroids.append(e.copy())
            cluster_ids[i] = len(centroids) - 1

    # Keep the TOP clusters by member count. We don't drop singletons
    # outright — in a podcast that mostly shows one person on screen,
    # the second face can legitimately appear only once or twice in a
    # 30-frame sample, and dropping it would leave us with one identity.
    # `max_identities` is the user's declared speaker count (capped via
    # the L3 modal step) so we don't surface background extras as
    # selectable thumbnails. Default 4 stays as the open-ended cap.
    counts: dict[int, int] = {}
    for cid in cluster_ids:
        counts[cid] = counts.get(cid, 0) + 1
    sorted_clusters = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    valid_clusters = {cid for cid, _ in sorted_clusters[:max(1, max_identities)]}

    # 4. For each valid cluster, save the highest-confidence frame's face
    # crop AND the centroid embedding. The embedding is what lets the
    # per-clip face_tracker match local FACE_XX clusters back to the
    # labeled global identity at render time.
    thumbnails: dict[str, Path] = {}
    embeddings_out: dict[str, list[float]] = {}
    for cid in sorted(valid_clusters):
        members = [d for d, c in zip(detections, cluster_ids) if c == cid]
        best = max(members, key=lambda d: d["prob"])
        face_id = f"FACE_{cid:02d}"
        thumb_path = out_dir / f"{face_id}.jpg"
        if _crop_face_from_frame(best["frame_path"], best["bbox"], thumb_path):
            thumbnails[face_id] = thumb_path
            # Mean of L2-normalized embeddings = the cluster centroid.
            cluster_embs = np.stack(
                [d["embedding"] for d, c in zip(detections, cluster_ids) if c == cid]
            )
            norms = np.linalg.norm(cluster_embs, axis=1, keepdims=True)
            centroid = (cluster_embs / np.clip(norms, 1e-6, None)).mean(axis=0)
            centroid = centroid / max(float(np.linalg.norm(centroid)), 1e-6)
            embeddings_out[face_id] = centroid.tolist()

    if embeddings_out:
        (out_dir / "face_embeddings.json").write_text(
            json.dumps(embeddings_out, indent=2)
        )

    logger.info(
        "Identity detection: %d detections → %d clusters → %d kept",
        len(detections), len(counts), len(thumbnails),
    )

    # Clean up the intermediate sampled frames — we only needed them to
    # detect + crop. Keeping them around would litter the user's drive.
    try:
        import shutil as _shutil
        _shutil.rmtree(frames_dir, ignore_errors=True)
    except Exception:
        pass

    return thumbnails


def extract_speaker_samples(
    video_path: Path,
    speaker_segments: list[dict],
    out_dir: Path,
    sample_duration: float = _SAMPLE_DURATION_SEC,
) -> dict[str, Path]:
    """For each speaker label, find the longest run and extract a clean WAV.

    `speaker_segments` is a list of dicts with `start`, `end`, `speaker`.
    Returns mapping speaker_id → wav path.
    """
    if not speaker_segments:
        return {}
    out_dir.mkdir(parents=True, exist_ok=True)
    speakers = sorted({s["speaker"] for s in speaker_segments if s.get("speaker")})

    results: dict[str, Path] = {}
    for spk in speakers:
        # Build contiguous runs of this speaker.
        runs: list[tuple[float, float]] = []
        cur: Optional[list[float]] = None
        for seg in speaker_segments:
            if seg["speaker"] == spk:
                if cur is None:
                    cur = [seg["start"], seg["end"]]
                else:
                    if seg["start"] - cur[1] < 1.5:
                        cur[1] = seg["end"]
                    else:
                        runs.append((cur[0], cur[1]))
                        cur = [seg["start"], seg["end"]]
            elif cur is not None:
                runs.append((cur[0], cur[1]))
                cur = None
        if cur is not None:
            runs.append((cur[0], cur[1]))
        if not runs:
            continue
        # Pick the longest run that's at least sample_duration; fall back
        # to longest available.
        runs.sort(key=lambda r: r[1] - r[0], reverse=True)
        best = runs[0]
        start = best[0]
        end = min(best[1], start + sample_duration)
        if end - start < 1.0:
            continue

        wav_path = out_dir / f"{spk}.wav"
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-ss", str(start), "-i", str(video_path),
                    "-t", str(end - start), "-ac", "1", "-ar", "16000",
                    "-vn", str(wav_path),
                ],
                capture_output=True, check=True, timeout=30,
            )
            if wav_path.exists() and wav_path.stat().st_size > 0:
                results[spk] = wav_path
        except Exception as e:
            logger.warning("Audio sample failed for %s: %s", spk, e)

    return results


def _diarize_full_episode(
    video_path: Path,
    num_speakers: int | None = None,
) -> tuple[list[dict], dict]:
    """Run ECAPA diarization on the full episode.

    Args:
        num_speakers: When set, force this exact k instead of silhouette-
            based auto-detect. The L3 modal asks the user up front how
            many speakers their podcast has so we can skip auto-detect
            entirely — it's the single most reliable accuracy lever.

    Returns (segments, voice_centroids). The centroids are 192-D L2-
    normalized vectors that the per-clip renderer uses to relabel its
    own local SPEAKER_NN back into the stable episode-level IDs.
    """
    try:
        from packages.clips.audio.speaker_id import SpeakerIdentifier
    except ImportError:
        return [], {}
    try:
        if num_speakers is not None and num_speakers > 0:
            identifier = SpeakerIdentifier(num_speakers=num_speakers)
        else:
            identifier = SpeakerIdentifier(
                num_speakers=None, min_speakers=2, max_speakers=4
            )
        with tempfile.TemporaryDirectory(prefix="azelia_preflight_diariz_") as tmp:
            wav = Path(tmp) / "audio.wav"
            SpeakerIdentifier._extract_audio(video_path, wav)
            segs = identifier.diarize(wav) or []
        # last_centroids is populated by diarize() — capture it now before
        # the SpeakerIdentifier instance falls out of scope.
        return segs, dict(identifier.last_centroids)
    except Exception as e:
        logger.warning("Preflight ECAPA fallback failed: %s", e)
        return [], {}


def prepare_identification(
    episode_folder: Path,
    speaker_segments: list[dict],
    num_speakers: int | None = None,
) -> dict:
    """Run the full preflight: face thumbnails + voice samples + manifest.

    `speaker_segments` comes from the user's transcript (Supabase or
    local Whisper). If it's empty (the user's source doesn't carry
    speaker labels for this episode), we run an episode-level ECAPA
    pass to generate them — costs ~30-60 s but unblocks the L3 flow
    on transcripts that are otherwise unusable.

    `num_speakers` is the count the user declared in the L3 modal's
    first step. When set, both ECAPA and the face-cluster top-N are
    pinned to it for maximum accuracy.
    """
    out_dir = episode_folder / ".identification"
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = episode_folder / "video.mp4"
    if not video_path.exists():
        # Try other common names
        for cand in episode_folder.glob("*.mp4"):
            video_path = cand
            break
    if not video_path.exists():
        raise FileNotFoundError(f"No video found in {episode_folder}")

    # 1. Faces. Cap surface-area to the declared speaker count so we
    # don't show background extras as selectable thumbnails.
    face_cap = num_speakers if (num_speakers and num_speakers > 0) else 4
    thumbnails = detect_face_identities(video_path, out_dir, max_identities=face_cap)

    # 2. Voice samples + voice fingerprints. If the transcript brought no
    # speaker info, run ECAPA on the full episode now. We ALSO capture
    # the per-speaker centroid embeddings (192-D voice fingerprints) and
    # persist them so the per-clip renderer can relabel its own local
    # ECAPA output back into the stable episode-level IDs the labels
    # file references — without that step the labels never line up with
    # the per-clip speaker IDs and the camera follows the wrong person.
    voice_centroids: dict = {}
    # Always re-derive episode-level voice centroids when num_speakers is
    # declared — even if the transcript already has labels, those came
    # from a different source (Supabase A/B) and may not match the user's
    # actual speaker count, leading to bad clustering.
    needs_diarize = not speaker_segments or (num_speakers and num_speakers > 0)
    if needs_diarize:
        logger.info(
            "Running episode-level ECAPA (num_speakers=%s)", num_speakers,
        )
        speaker_segments, voice_centroids = _diarize_full_episode(
            video_path, num_speakers=num_speakers,
        )

    samples = extract_speaker_samples(video_path, speaker_segments, out_dir)

    if voice_centroids:
        (out_dir / "voice_embeddings.json").write_text(
            json.dumps(
                {k: v.tolist() if hasattr(v, "tolist") else list(v) for k, v in voice_centroids.items()},
                indent=2,
            )
        )

    manifest = {
        "video": video_path.name,
        "faces": sorted(thumbnails.keys()),
        "speakers": sorted(samples.keys()),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def load_labels(episode_folder: Path) -> Optional[dict]:
    """Return `speaker_face_labels.json` if it exists, else None.

    Shape: {"SPEAKER_00": {"name": "Juan Pablo", "face_id": "FACE_01"}, ...}
    A `_skipped: true` key means the user explicitly chose auto-detect.
    """
    path = episode_folder / "speaker_face_labels.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def save_labels(episode_folder: Path, labels: dict) -> None:
    """Persist the user-confirmed speaker→face mapping."""
    path = episode_folder / "speaker_face_labels.json"
    path.write_text(json.dumps(labels, indent=2, ensure_ascii=False))
