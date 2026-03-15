"""Face detection and identity tracking with MTCNN + FaceNet (facenet-pytorch).

Architecture:
    MTCNN  → detects faces in any frame (multi-scale, handles any angle/size)
    InceptionResnetV1 → generates 512-D embeddings for biometric identity
    IdentityStore → clusters embeddings into persistent FACE_XX identities

This replaces the broken DeepFace/TensorFlow stack. Identity persists across
camera cuts via cosine similarity of embeddings — no frame-to-frame tracking
dependency for who-is-who.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import torch
from PIL import Image
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn

console = Console()

# ─── Cosine similarity threshold ────────────────────────────────────────────
# Embeddings with similarity >= this value are considered the same person.
# Lower = more aggressive merging (fewer identities, risk of merging different people)
# Higher = more conservative (more identities, risk of splitting same person)
# 0.65 works well for podcast-style video with lighting/angle variations.
SIMILARITY_THRESHOLD = 0.65

# Minimum face bounding box size (pixels) — below this, embeddings are unreliable
MIN_FACE_SIZE = 40


# ─── Data classes ────────────────────────────────────────────────────────────

@dataclass
class FaceDetection:
    """A detected face in a video frame."""
    frame_idx: int
    timestamp: float
    x: int          # Top-left X
    y: int          # Top-left Y
    width: int
    height: int
    identity_id: str | None = None   # e.g. "FACE_00"
    track_id: int | None = None      # optional short-term tracker ID
    confidence: float = 1.0

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2


@dataclass
class FaceIdentity:
    """A persistent face identity with running-average embedding."""
    face_id: str                    # e.g. "FACE_00"
    embedding: np.ndarray           # 512-D prototype (L2-normalized)
    count: int = 1                  # how many times seen
    thumbnail: str | None = None    # filename of best thumbnail
    role: str | None = None         # user-assigned label ("Host", "Guest", etc.)


# ─── Identity Store ──────────────────────────────────────────────────────────

class IdentityStore:
    """Manages N face identity clusters with prototype averaging.
    
    Each identity has a running-average 512-D embedding that becomes more
    stable with each new observation of the same face.
    """

    def __init__(self, similarity_threshold: float = SIMILARITY_THRESHOLD):
        self.sim_thresh = similarity_threshold
        self.identities: list[FaceIdentity] = []

    @staticmethod
    def _normalize(v: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(v)
        return v / (norm + 1e-8)

    def match_or_create(self, embedding: np.ndarray) -> FaceIdentity:
        """Match embedding to known identity or create a new one.
        
        Args:
            embedding: 512-D face embedding (will be L2-normalized).
            
        Returns:
            The matched or newly created FaceIdentity.
        """
        emb = self._normalize(embedding)

        if not self.identities:
            identity = FaceIdentity(
                face_id=f"FACE_{len(self.identities):02d}",
                embedding=emb.copy(),
                count=1,
            )
            self.identities.append(identity)
            return identity

        # Cosine similarity against all prototypes
        protos = np.stack([i.embedding for i in self.identities])
        sims = protos @ emb  # (N,) — cosine similarity (both normalized)

        best_idx = int(np.argmax(sims))
        best_sim = float(sims[best_idx])

        if best_sim >= self.sim_thresh:
            # Update running-average prototype
            identity = self.identities[best_idx]
            n = identity.count
            new_proto = (identity.embedding * n + emb) / (n + 1)
            identity.embedding = self._normalize(new_proto)
            identity.count = n + 1
            return identity
        else:
            # New identity
            identity = FaceIdentity(
                face_id=f"FACE_{len(self.identities):02d}",
                embedding=emb.copy(),
                count=1,
            )
            self.identities.append(identity)
            return identity

    def match(self, embedding: np.ndarray) -> FaceIdentity | None:
        """Match embedding to known identity (read-only, no update).
        
        Returns None if no match above threshold.
        """
        if not self.identities:
            return None

        emb = self._normalize(embedding)
        protos = np.stack([i.embedding for i in self.identities])
        sims = protos @ emb

        best_idx = int(np.argmax(sims))
        if float(sims[best_idx]) >= self.sim_thresh:
            return self.identities[best_idx]
        return None


# ─── Face Tracker ────────────────────────────────────────────────────────────

class FaceTracker:
    """Face detection + identity tracking using MTCNN + InceptionResnetV1.
    
    Usage:
        tracker = FaceTracker(sample_fps=2.0)
        detections = tracker.detect_faces(video_path)
        trajectory = tracker.get_smooth_crop_trajectory(
            detections, video_width, video_height
        )
    """

    def __init__(
        self,
        sample_fps: float = 10.0,
        smoothing_factor: float = 0.15,
        similarity_threshold: float = SIMILARITY_THRESHOLD,
    ):
        self.sample_fps = sample_fps
        self.smoothing_factor = smoothing_factor
        self.identity_store = IdentityStore(similarity_threshold)

        # Lazy-load models on first use
        self._mtcnn = None
        self._embedder = None
        self._device = None

    def _ensure_models(self):
        """Lazy-load MTCNN + InceptionResnetV1."""
        if self._mtcnn is not None:
            return

        from facenet_pytorch import MTCNN, InceptionResnetV1

        if torch.cuda.is_available():
            self._device = torch.device("cuda")
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            self._device = torch.device("mps")
        else:
            self._device = torch.device("cpu")

        console.print(f"[dim]   Loading face models (embedder on {self._device})...[/dim]")

        # MTCNN must run on CPU — MPS doesn't support adaptive_avg_pool2d
        # for non-divisible input sizes (PyTorch issue #96056)
        self._mtcnn = MTCNN(
            keep_all=True,
            device=torch.device("cpu"),
            min_face_size=MIN_FACE_SIZE,
            thresholds=[0.6, 0.7, 0.7],  # P-Net, R-Net, O-Net
        )

        # Embedder benefits from GPU (batch matrix ops)
        self._embedder = InceptionResnetV1(
            pretrained="vggface2"
        ).eval().to(self._device)

    # ─── Core: detect faces ──────────────────────────────────────────────

    def detect_faces(
        self,
        video_path: Path | str,
        start_time: float = 0,
        end_time: float | None = None,
    ) -> list[FaceDetection]:
        """Detect and identify faces across video frames.
        
        Uses MTCNN for detection + InceptionResnetV1 for embeddings.
        Returns FaceDetection objects with identity_id assigned.
        
        Args:
            video_path: Path to video file.
            start_time: Start time in seconds.
            end_time: End time in seconds (None = entire video).
            
        Returns:
            List of FaceDetection with identity_id assigned.
        """
        self._ensure_models()

        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")

        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0

        if end_time is None:
            end_time = duration

        frame_interval = max(1, int(fps / self.sample_fps))
        start_frame = int(start_time * fps)
        end_frame = int(end_time * fps)

        detections: list[FaceDetection] = []

        console.print(f"[blue]👤 Face Detection (MTCNN + FaceNet)[/blue]")
        console.print(
            f"[dim]   Sampling at {self.sample_fps} FPS | "
            f"{start_time:.1f}s - {end_time:.1f}s[/dim]"
        )

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            frames_to_process = max(1, (end_frame - start_frame) // frame_interval)
            task = progress.add_task("Detecting faces...", total=frames_to_process)

            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            frame_idx = start_frame
            processed = 0

            while frame_idx < end_frame:
                ret, frame = cap.read()
                if not ret:
                    break

                if (frame_idx - start_frame) % frame_interval == 0:
                    timestamp = frame_idx / fps
                    height, width = frame.shape[:2]

                    # Convert BGR → RGB PIL Image for MTCNN
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    pil_img = Image.fromarray(rgb)

                    # Detect faces
                    try:
                        boxes, probs = self._mtcnn.detect(pil_img)
                    except Exception:
                        frame_idx += 1
                        continue

                    if boxes is not None and len(boxes) > 0:
                        # Get aligned face tensors for embedding
                        try:
                            face_tensors = self._mtcnn(pil_img)
                        except Exception:
                            frame_idx += 1
                            continue

                        if face_tensors is not None:
                            # Ensure batch dimension
                            if face_tensors.dim() == 3:
                                face_tensors = face_tensors.unsqueeze(0)

                            # Compute embeddings
                            with torch.no_grad():
                                embeddings = self._embedder(
                                    face_tensors.to(self._device)
                                )
                                embeddings = torch.nn.functional.normalize(
                                    embeddings, p=2, dim=1
                                )

                            embs_np = embeddings.cpu().numpy()

                            for i, (box, prob) in enumerate(zip(boxes, probs)):
                                if i >= len(embs_np):
                                    break

                                x1, y1, x2, y2 = map(int, box)
                                w = x2 - x1
                                h = y2 - y1

                                # Skip tiny faces
                                if w < MIN_FACE_SIZE or h < MIN_FACE_SIZE:
                                    continue

                                # Clamp to frame bounds
                                x1 = max(0, x1)
                                y1 = max(0, y1)
                                w = min(w, width - x1)
                                h = min(h, height - y1)

                                # Identify via embeddings
                                identity = self.identity_store.match_or_create(
                                    embs_np[i]
                                )

                                detections.append(FaceDetection(
                                    frame_idx=frame_idx,
                                    timestamp=timestamp,
                                    x=x1,
                                    y=y1,
                                    width=w,
                                    height=h,
                                    identity_id=identity.face_id,
                                    confidence=float(prob) if prob else 1.0,
                                ))

                    processed += 1
                    progress.advance(task)

                frame_idx += 1

        cap.release()

        n_ids = len(self.identity_store.identities)
        console.print(
            f"[green]✓[/green] {len(detections)} detections, "
            f"{n_ids} unique {'identity' if n_ids == 1 else 'identities'} found"
        )
        for identity in self.identity_store.identities:
            console.print(
                f"[dim]   {identity.face_id}: seen {identity.count}x[/dim]"
            )

        return detections

    # ─── Extract unique faces (for the UI gallery) ───────────────────────

    def extract_unique_faces(
        self,
        video_path: Path | str,
        output_dir: Path | str,
        max_duration_sec: int | None = None,
        expected_faces: int | None = None,
    ) -> dict[str, str]:
        """Scan video and extract thumbnails for each unique face.
        
        Scans the entire video (or up to max_duration_sec) and saves
        the best thumbnail per identity to output_dir.
        
        Args:
            video_path: Path to source video.
            output_dir: Directory to save face thumbnails.
            max_duration_sec: Max duration to scan (None = full video).
            expected_faces: Hint for expected number of faces (unused, kept for API compat).
            
        Returns:
            Dict mapping face_id → thumbnail filename, e.g. {"FACE_00": "face_00.jpg"}
        """
        self._ensure_models()

        video_path = Path(video_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if not video_path.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")

        console.print(
            f"[blue]👤[/blue] Scanning faces in {video_path.name} "
            f"at {self.sample_fps} FPS..."
        )

        # Determine scan range
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        total_duration = total_frames / fps if fps > 0 else 0
        cap.release()

        end_time = total_duration
        if max_duration_sec is not None:
            end_time = min(max_duration_sec, total_duration)

        # Use lower FPS for full-video discovery scan (efficiency)
        original_fps = self.sample_fps
        self.sample_fps = min(self.sample_fps, 1.0)

        detections = self.detect_faces(video_path, 0, end_time)

        self.sample_fps = original_fps  # restore

        if not detections:
            console.print("[yellow]⚠️ No faces found in video[/yellow]")
            return {}

        # Collect best thumbnail per identity (largest face crop)
        best_crops: dict[str, tuple[np.ndarray, int]] = {}  # face_id → (crop, area)

        cap = cv2.VideoCapture(str(video_path))

        for det in detections:
            if det.identity_id is None:
                continue

            area = det.width * det.height
            existing = best_crops.get(det.identity_id)

            if existing is None or area > existing[1]:
                # Read frame and crop
                cap.set(cv2.CAP_PROP_POS_FRAMES, det.frame_idx)
                ret, frame = cap.read()
                if not ret:
                    continue

                h, w = frame.shape[:2]
                x1 = max(0, det.x)
                y1 = max(0, det.y)
                x2 = min(w, det.x + det.width)
                y2 = min(h, det.y + det.height)
                crop = frame[y1:y2, x1:x2]

                if crop.size > 0:
                    best_crops[det.identity_id] = (crop, area)

        cap.release()

        # Save thumbnails
        result: dict[str, str] = {}
        for identity in self.identity_store.identities:
            if identity.face_id in best_crops:
                filename = f"{identity.face_id.lower()}.jpg"
                filepath = output_dir / filename
                cv2.imwrite(str(filepath), best_crops[identity.face_id][0])
                identity.thumbnail = filename
                result[identity.face_id] = filename

        console.print(
            f"[green]✓[/green] Found {len(result)} unique faces "
            f"({', '.join(f'{i.face_id} (seen {i.count}x)' for i in self.identity_store.identities)})"
        )

        return result

    # ─── Face gallery for user mapping ─────────────────────────────────────

    def save_face_gallery(
        self,
        detections: list[FaceDetection],
        output_dir: Path | str,
        video_path: Path | str | None = None,
        video_width: int = 0,
    ) -> dict[str, dict]:
        """Save labeled face thumbnails and return metadata for user mapping.
        
        Args:
            detections: List of FaceDetection from detect_faces()
            output_dir: Directory to save face_xx.jpg files
            video_path: Source video path (needed to extract crop images)
            video_width: Source video width (for position labels)
            
        Returns:
            Dict of {face_id: {"path": str, "avg_x": int, "avg_y": int, "position": str, "count": int}}
        """
        import cv2
        from collections import Counter

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        face_counts = Counter(d.identity_id for d in detections if d.identity_id)
        # Only include faces seen > 5 times (filter noise)
        top_faces = [fid for fid, cnt in face_counts.most_common() if cnt >= 5]

        # Collect best crop per identity (largest area)
        best_det: dict[str, FaceDetection] = {}
        for d in detections:
            if d.identity_id not in top_faces:
                continue
            existing = best_det.get(d.identity_id)
            if existing is None or (d.width * d.height) > (existing.width * existing.height):
                best_det[d.identity_id] = d

        # Extract crop images from video
        gallery: dict[str, dict] = {}
        
        if video_path and best_det:
            cap = cv2.VideoCapture(str(video_path))
            for fid, det in best_det.items():
                cap.set(cv2.CAP_PROP_POS_FRAMES, det.frame_idx)
                ret, frame = cap.read()
                if not ret:
                    continue
                
                h, w = frame.shape[:2]
                # Add padding around the face (30% margin)
                margin_x = int(det.width * 0.3)
                margin_y = int(det.height * 0.3)
                x1 = max(0, det.x - margin_x)
                y1 = max(0, det.y - margin_y)
                x2 = min(w, det.x + det.width + margin_x)
                y2 = min(h, det.y + det.height + margin_y)
                crop = frame[y1:y2, x1:x2]
                
                if crop.size == 0:
                    continue
                
                filepath = output_dir / f"{fid.lower()}.jpg"
                cv2.imwrite(str(filepath), crop)
                
                face_dets = [d for d in detections if d.identity_id == fid]
                avg_x = int(sum(d.center_x for d in face_dets) / len(face_dets))
                avg_y = int(sum(d.center_y for d in face_dets) / len(face_dets))
                
                if video_width > 0:
                    third = video_width / 3
                    position = "LEFT" if avg_x < third else ("CENTER" if avg_x < 2 * third else "RIGHT")
                else:
                    position = "?"
                
                gallery[fid] = {
                    "path": str(filepath),
                    "avg_x": avg_x,
                    "avg_y": avg_y,
                    "position": position,
                    "count": face_counts[fid],
                }
            cap.release()

        return gallery

    # ─── Safe zone zoom computation ──────────────────────────────────────

    @staticmethod
    def compute_safe_zoom(
        detections: list[FaceDetection],
        src_height: int,
        safe_zone_mult: float = 2.5,
    ) -> float:
        """Compute a dynamic zoom factor based on detected face sizes.
        
        Instead of a hardcoded zoom, this creates a "safe zone" where the crop
        height = largest_face_height × safe_zone_mult. This ensures consistent
        head+shoulders framing regardless of how close/far camera is.
        
        Args:
            detections: List of FaceDetection from detect_faces()
            src_height: Source video height
            safe_zone_mult: How many face-heights the crop should be (default 2.5)
                1.5 = very tight (just head)
                2.5 = head + shoulders (default)
                4.0 = head + upper body
                
        Returns:
            zoom_factor between 0.3 and 1.0
        """
        # Use top 3 most frequent faces
        from collections import Counter
        counts = Counter(d.identity_id for d in detections if d.identity_id)
        relevant_faces = {fid for fid, _ in counts.most_common(3)}
        
        # Find the average face height per identity, then take the max
        face_heights: list[float] = []
        for fid in relevant_faces:
            heights = [d.height for d in detections if d.identity_id == fid]
            if heights:
                avg_h = sum(heights) / len(heights)
                face_heights.append(avg_h)
        
        if not face_heights:
            return 0.7  # fallback
        
        # Use the LARGEST average face height (most zoomed in person)
        max_face_h = max(face_heights)
        
        # Desired crop height = face_height * multiplier
        ideal_crop_h = max_face_h * safe_zone_mult
        
        # zoom_factor = ideal_crop_h / src_height
        zoom = ideal_crop_h / src_height
        zoom = max(0.3, min(1.0, zoom))  # clamp
        
        console.print(
            f"[dim]   Safe zone: max_face={max_face_h:.0f}px × {safe_zone_mult} = "
            f"ideal_crop={ideal_crop_h:.0f}px → zoom={zoom:.2f}[/dim]"
        )
        
        return zoom

    # ─── Active Speaker Detection (Mouth Motion) ──────────────────────────────
    
    def map_speakers_via_mouth_motion(
        self,
        video_path: Path | str,
        detections: list[FaceDetection],
        speaker_segments: list[dict],
        start_time: float = 0,
        end_time: float | None = None,
    ) -> dict[str, str]:
        """Map diarization SPEAKER_XX to face identities using mouth motion variance.
        
        Args:
            video_path: Path to the source video.
            detections: List of FaceDetection from detect_faces().
            speaker_segments: Pyannote diarization segments (list of dicts with 'speaker', 'start', 'end').
            start_time: Start time in seconds.
            end_time: End time in seconds.
            
        Returns:
            Dict mapping "SPEAKER_XX" -> "FACE_YY".
        """
        from collections import defaultdict
        import cv2
        import numpy as np
        
        video_path = Path(video_path)
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0
        if end_time is None:
            end_time = duration

        # Normalize: accept both dicts and dataclass/object segments
        def _seg(s, key):
            return s[key] if isinstance(s, dict) else getattr(s, key)
        speaker_segments = [
            {"start": _seg(s, "start"), "end": _seg(s, "end"), "speaker": _seg(s, "speaker")}
            for s in speaker_segments
        ]

        # Get Pyannote speakers
        pyannote_speakers = list(set([s["speaker"] for s in speaker_segments]))
        if not pyannote_speakers:
            return {}

        # Group detections by identity and filter out hallucinations (seen < 20 times)
        faces_by_id: dict[str, list[FaceDetection]] = defaultdict(list)
        for d in detections:
            if d.identity_id:
                faces_by_id[d.identity_id].append(d)
                
        valid_identities = [iid for iid, faces in faces_by_id.items() if len(faces) >= 20]
        if not valid_identities:
            # Fallback to all if somehow none have 20+
            valid_identities = list(faces_by_id.keys())
            
        console.print(f"[dim]   Valid identities for mapping: {valid_identities}[/dim]")
        
        # We will calculate motion score ONLY when a speaker's segment is active
        motion_scores: dict[str, dict[str, list[float]]] = {
            speaker: {iid: [] for iid in valid_identities} 
            for speaker in pyannote_speakers
        }
        
        console.print("[dim]   Analyzing mouth movement for speaker mapping...[/dim]")
        
        for iid in valid_identities:
            faces = sorted(faces_by_id[iid], key=lambda x: x.timestamp)
            prev_gray_mouth = None
            
            for f in faces:
                # Find which pyannote speakers are talking right now
                active_speakers = [
                    s["speaker"] for s in speaker_segments 
                    if s["start"] <= f.timestamp <= s["end"]
                ]
                
                if not active_speakers:
                    prev_gray_mouth = None # Reset diff calculation if gap
                    continue
                
                # Extract frame
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(f.timestamp * fps))
                ret, frame = cap.read()
                if not ret: continue
                
                # Extract mouth region (bottom 40% of bounding box)
                x1 = max(0, int(f.center_x - f.width/2))
                x2 = min(frame.shape[1], int(f.center_x + f.width/2))
                y1 = int(f.center_y - f.height/2)
                y2 = int(f.center_y + f.height/2)
                
                mouth_top = y1 + int((y2 - y1) * 0.60)
                mouth_bottom = y2
                
                mouth_crop = frame[max(0, mouth_top):min(frame.shape[0], mouth_bottom), x1:x2]
                if mouth_crop.size == 0: continue
                
                mouth_crop = cv2.resize(mouth_crop, (100, 50))
                gray_mouth = cv2.cvtColor(mouth_crop, cv2.COLOR_BGR2GRAY)
                
                if prev_gray_mouth is not None:
                    diff = cv2.absdiff(gray_mouth, prev_gray_mouth)
                    motion = float(np.mean(diff))
                    
                    for speaker in active_speakers:
                        motion_scores[speaker][iid].append(motion)
                        
                prev_gray_mouth = gray_mouth
                
        cap.release()
        
        speaker_face_map = {}
        # Mapping algorithm
        for speaker in pyannote_speakers:
            best_iid = None
            best_motion = -1.0
            
            for iid in valid_identities:
                scores = motion_scores[speaker][iid]
                avg_motion = float(np.mean(scores)) if scores else 0.0
                if avg_motion > best_motion:
                    best_motion = avg_motion
                    best_iid = iid
                    
            if best_iid:
                speaker_face_map[speaker] = best_iid
                console.print(f"[green]   ✓ {speaker} mapped to {best_iid} (motion: {best_motion:.2f})[/green]")
                
        return speaker_face_map

    # ─── Trajectory generation ───────────────────────────────────────────


    def get_speaker_trajectory(
        self,
        video_path: Path | str,
        detections: list[FaceDetection],
        start_time: float,
        end_time: float,
        video_width: int,
        video_height: int,
        speaker_segments: list[dict] | None = None,
        target_aspect: float = 9 / 16,
    ) -> list[tuple[float, int, int]]:
        """Generate crop trajectory based on active speaker mapping.
        
        Args:
            video_path: Path to the source video.
            detections: List of FaceDetection from detect_faces().
            start_time: Start time in seconds.
            end_time: End time in seconds.
            video_width: Source video width.
            video_height: Source video height.
            speaker_segments: Pyannote diarization segments.
            target_aspect: Aspect ratio for crop (default 9:16).
            
        Returns:
            List of (timestamp, center_x, center_y) crop points.
        """
        if not detections:
            return [(0, video_width // 2, video_height // 2)]

        if not speaker_segments:
            console.print("[yellow]⚠ No speaker segments provided, falling back to largest face tracking[/yellow]")
            return self.get_smooth_crop_trajectory(
                detections, video_width, video_height, target_aspect
            )

        # Normalize: accept both dicts and dataclass/object segments
        def _as_dict(s):
            if isinstance(s, dict):
                return s
            return {"start": getattr(s, "start", 0), "end": getattr(s, "end", 0), "speaker": getattr(s, "speaker", "")}
        speaker_segments = [_as_dict(s) for s in speaker_segments]
        # Filter out segments with no speaker label (transcript segments)
        speaker_segments = [s for s in speaker_segments if s["speaker"]]

        # Get active speaker mapping via mouth motion
        speaker_face_map = self.map_speakers_via_mouth_motion(
            video_path, detections, speaker_segments, start_time, end_time
        )
        
        if not speaker_face_map:
            console.print("[yellow]⚠ Mouth motion mapping failed, falling back to largest face tracking[/yellow]")
            return self.get_smooth_crop_trajectory(
                detections, video_width, video_height, target_aspect
            )

        # Group detections by timestamp
        by_timestamp: dict[float, list[FaceDetection]] = {}
        for d in detections:
            by_timestamp.setdefault(d.timestamp, []).append(d)

        timestamps = sorted(by_timestamp.keys())
        if not timestamps:
            return self.get_smooth_crop_trajectory(
                detections, video_width, video_height, target_aspect
            )

        identity_ids = list(speaker_face_map.values())

        # Precompute average position per identity (to fall back on if face is temporarily lost)
        identity_positions: dict[str, tuple[int, int]] = {}
        identity_x_sums: dict[str, list[int]] = {iid: [] for iid in identity_ids}
        identity_y_sums: dict[str, list[int]] = {iid: [] for iid in identity_ids}
        for d in detections:
            if d.identity_id and d.identity_id in identity_ids:
                identity_x_sums[d.identity_id].append(d.center_x)
                identity_y_sums[d.identity_id].append(d.center_y)
                
        for iid in identity_ids:
            xs = identity_x_sums[iid]
            ys = identity_y_sums[iid]
            if xs and ys:
                identity_positions[iid] = (int(sum(xs) / len(xs)), int(sum(ys) / len(ys)))
            else:
                identity_positions[iid] = (video_width // 2, video_height // 2)

        # ── Resolve active speaker per frame based on highest Pyannote mapping ──
        
        crop_width = int(video_height * target_aspect)
        min_x = crop_width // 2
        max_x = video_width - crop_width // 2
        min_y = video_height // 2
        max_y = video_height // 2 # Clamp strictly to vertical center

        crop_points: list[tuple[float, int, int]] = []
        last_center_x = video_width // 2
        last_center_y = video_height // 2
        
        # Determine active speaker per frame
        for t in timestamps:
            active_speaker_id = None
            
            # Find the speaker active at this timestamp
            # Sort to get deterministic behavior on overlapping segments
            active_segs = [s for s in speaker_segments if s["start"] <= t <= s["end"]]
            if active_segs:
                # Pick the longest active segment to avoid brief overlaps overriding
                active_seg = max(active_segs, key=lambda s: s["end"] - s["start"])
                active_speaker_id = speaker_face_map.get(active_seg["speaker"])

            # Active face center computation
            if active_speaker_id:
                # Try to get exact position at this frame
                current_faces = by_timestamp[t]
                my_face = next((f for f in current_faces if f.identity_id == active_speaker_id), None)
                if my_face:
                    center_x, center_y = my_face.center_x, my_face.center_y
                else:
                    center_x, center_y = identity_positions.get(active_speaker_id, (last_center_x, last_center_y))
                    
                last_center_x = center_x
                last_center_y = center_y
            else:
                center_x = last_center_x
                center_y = last_center_y

            center_x = max(min_x, min(max_x, center_x))
            crop_points.append((t, center_x, center_y))

        return crop_points


    def get_smooth_crop_trajectory(
        self,
        detections: list[FaceDetection],
        video_width: int,
        video_height: int,
        target_aspect: float = 9 / 16,
    ) -> list[tuple[float, int, int]]:
        """Generate a smooth crop trajectory following the largest detected face.
        
        Fallback when speaker diarization is not available.
        
        Args:
            detections: List of FaceDetection from detect_faces().
            video_width: Source video width.
            video_height: Source video height.
            target_aspect: Aspect ratio for crop (default 9:16).
            
        Returns:
            List of (timestamp, center_x, center_y) crop points.
        """
        if not detections:
            return [(0, video_width // 2, video_height // 2)]

        crop_width = int(video_height * target_aspect)
        min_x = crop_width // 2
        max_x = video_width - crop_width // 2

        min_y = video_height // 2
        max_y = video_height // 2

        # Group by timestamp
        by_timestamp: dict[float, list[FaceDetection]] = {}
        for d in detections:
            by_timestamp.setdefault(d.timestamp, []).append(d)

        timestamps = sorted(by_timestamp.keys())
        if not timestamps:
            return [(0, video_width // 2, video_height // 2)]

        # Get initial position from largest face
        best_init = max(
            by_timestamp[timestamps[0]],
            key=lambda f: f.width * f.height,
        )
        last_x = best_init.center_x
        last_y = best_init.center_y

        trajectory: list[tuple[float, int, int]] = []
        for t in timestamps:
            faces = by_timestamp[t]
            best_face = max(faces, key=lambda f: f.width * f.height)
            target_x = best_face.center_x
            target_y = best_face.center_y

            smoothed_x = int(
                last_x * (1 - self.smoothing_factor)
                + target_x * self.smoothing_factor
            )
            smoothed_y = int(
                last_y * (1 - self.smoothing_factor)
                + target_y * self.smoothing_factor
            )
            
            clamped_x = max(min_x, min(max_x, smoothed_x))
            clamped_y = max(min_y, min(max_y, smoothed_y))

            trajectory.append((t, clamped_x, clamped_y))
            last_x = smoothed_x
            last_y = smoothed_y

        return trajectory


# ─── Compatibility wrapper ───────────────────────────────────────────────────

def track_face(
    video_path: Path | str,
    start_time: float = 0,
    end_time: float | None = None,
) -> list[tuple[float, int]]:
    """Compatibility wrapper — detects faces and returns crop trajectory.
    
    Uses the largest face in each frame as the crop target.
    """
    video_path = Path(video_path)
    cap = cv2.VideoCapture(str(video_path))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    tracker = FaceTracker(sample_fps=2.0)
    detections = tracker.detect_faces(video_path, start_time, end_time)

    return tracker.get_smooth_crop_trajectory(detections, width, height)
