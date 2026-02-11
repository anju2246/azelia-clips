"""Face detection and tracking with MediaPipe + DeepSort - FIXED VERSION."""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import mediapipe as mp
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn

console = Console()


@dataclass
class FaceDetection:
    """A detected face in a video frame."""
    frame_idx: int
    timestamp: float
    x: int  # Top-left X
    y: int  # Top-left Y
    width: int
    height: int
    track_id: int | None = None
    confidence: float = 1.0

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2


class FaceTracker:
    """
    Face detection using MediaPipe + DeepSORT tracking.
    
    Migrated to MediaPipe Tasks API (0.10.31+).
    """
    
    # Path al modelo descargado
    MODEL_PATH = Path(__file__).parent.parent.parent / "models" / "face_detector.task"

    def __init__(
        self,
        sample_fps: float = 10.0,
        min_detection_confidence: float = 0.5,  # Models API usa 0.5 default
        smoothing_factor: float = 0.15,
    ):
        self.sample_fps = sample_fps
        self.min_detection_confidence = min_detection_confidence
        self.smoothing_factor = smoothing_factor

        # Verificar modelo
        if not self.MODEL_PATH.exists():
            raise FileNotFoundError(
                f"Face Detector model not found at {self.MODEL_PATH}. "
                "Download from: https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.task"
            )

        # Configurar FaceDetector Tasks API
        BaseOptions = mp.tasks.BaseOptions
        FaceDetector = mp.tasks.vision.FaceDetector
        FaceDetectorOptions = mp.tasks.vision.FaceDetectorOptions
        VisionRunningMode = mp.tasks.vision.RunningMode

        self.options = FaceDetectorOptions(
            base_options=BaseOptions(model_asset_path=str(self.MODEL_PATH)),
            running_mode=VisionRunningMode.VIDEO,
            min_detection_confidence=min_detection_confidence
        )

        # DeepSORT tracker
        from deep_sort_realtime.deepsort_tracker import DeepSort
        self.tracker = DeepSort(
            max_age=30,
            n_init=3,
            nms_max_overlap=0.3,
            max_cosine_distance=0.2,
        )

    def detect_faces(
        self,
        video_path: Path | str,
        start_time: float = 0,
        end_time: float | None = None,
    ) -> list[FaceDetection]:
        """Detect faces using MediaPipe Tasks API."""
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

        detections = []

        console.print(f"[blue]👤 MediaPipe Face Detection (Tasks API)[/blue]")
        console.print(f"[dim]   Sampling at {self.sample_fps} FPS | {start_time:.1f}s - {end_time:.1f}s[/dim]")

        # Crear FaceDetector con context manager
        FaceDetector = mp.tasks.vision.FaceDetector
        
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            console=console,
        ) as progress, FaceDetector.create_from_options(self.options) as detector:
            
            frames_to_process = (end_frame - start_frame) // frame_interval
            task = progress.add_task("Detecting faces...", total=frames_to_process)

            frame_idx = start_frame
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

            while frame_idx < end_frame:
                ret, frame = cap.read()
                if not ret:
                    break

                if (frame_idx - start_frame) % frame_interval == 0:
                    timestamp = frame_idx / fps
                    timestamp_ms = int(frame_idx * 1000 / fps)
                    height, width = frame.shape[:2]

                    # Convert BGR to RGB + mp.Image
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

                    # Detect faces with Tasks API
                    try:
                        results = detector.detect_for_video(mp_image, timestamp_ms)
                    except Exception:
                        frame_idx += 1
                        continue

                    # Prepare detections for DeepSORT
                    raw_detections = []
                    if results.detections:
                        for detection in results.detections:
                            bbox = detection.bounding_box
                            
                            # Tasks API devuelve bbox absoluta (origin_x, origin_y, width, height)
                            x = bbox.origin_x
                            y = bbox.origin_y
                            w = bbox.width
                            h = bbox.height
                            
                            # Ensure valid bounds
                            x = max(0, x)
                            y = max(0, y)
                            w = min(w, width - x)
                            h = min(h, height - y)
                            
                            # Confianza
                            confidence = detection.categories[0].score if detection.categories else 0.5
                            
                            # DeepSORT format: ([x, y, w, h], confidence, feature)
                            raw_detections.append(([x, y, w, h], confidence, None))

                    # Update tracker
                    tracks = self.tracker.update_tracks(raw_detections, frame=frame)

                    for track in tracks:
                        if not track.is_confirmed():
                            continue
                        
                        track_id = track.track_id
                        ltrb = track.to_ltrb()
                        x1, y1, x2, y2 = map(int, ltrb)
                        
                        detections.append(FaceDetection(
                            frame_idx=frame_idx,
                            timestamp=timestamp,
                            x=x1,
                            y=y1,
                            width=x2 - x1,
                            height=y2 - y1,
                            track_id=track_id,
                            confidence=track.get_det_conf() or 1.0
                        ))

                    progress.advance(task)

                frame_idx += 1

        cap.release()


        # Analizar calidad del tracking
        unique_tracks = len(set(d.track_id for d in detections if d.track_id))
        console.print(f"[green]✓[/green] Detected {len(detections)} faces | {unique_tracks} unique people")
        
        # Warning si detecta más de 3 personas (probable error)
        if unique_tracks > 3:
            console.print(f"[yellow]⚠[/yellow] Detected {unique_tracks} people (expected 2). Check video quality.")

        return detections

    def get_speaker_aware_trajectory(
        self,
        detections: list[FaceDetection],
        speaker_segments: list,
        video_width: int,
        video_height: int,
        target_aspect: float = 9 / 16,
    ) -> list[tuple[float, int]]:
        """
        Calculate crop trajectory following the ACTIVE SPEAKER.
        
        MEJORADO: Usa confianza de detección y consistencia temporal.
        """
        if not detections:
            return [(0, video_width // 2)]

        # Filtrar segmentos cortos (ruido)
        filtered_segments = [s for s in speaker_segments if (s.end - s.start) >= 1.0]
        
        # Agrupar por track_id y timestamp
        by_track_id: dict[int, list[FaceDetection]] = {}
        by_timestamp: dict[float, list[FaceDetection]] = {}
        
        for d in detections:
            if d.timestamp not in by_timestamp:
                by_timestamp[d.timestamp] = []
            by_timestamp[d.timestamp].append(d)
            
            if d.track_id is not None:
                if d.track_id not in by_track_id:
                    by_track_id[d.track_id] = []
                by_track_id[d.track_id].append(d)

        # Encontrar los 2 tracks principales (más detecciones)
        main_tracks = sorted(by_track_id.items(), key=lambda x: len(x[1]), reverse=True)[:2]
        
        if len(main_tracks) < 2:
            console.print(f"[yellow]⚠[/yellow] Solo 1 persona detectada, usando crop fijo")
            return self._fixed_crop(detections, video_width, video_height, target_aspect)

        track_a_id, track_a_dets = main_tracks[0]
        track_b_id, track_b_dets = main_tracks[1]

        # Calcular posiciones promedio (LEFT/RIGHT)
        avg_x_a = sum(d.center_x for d in track_a_dets) / len(track_a_dets)
        avg_x_b = sum(d.center_x for d in track_b_dets) / len(track_b_dets)

        track_map = {track_a_id: int(avg_x_a), track_b_id: int(avg_x_b)}
        
        console.print(f"[dim]   Track {track_a_id} @ X={int(avg_x_a)} | Track {track_b_id} @ X={int(avg_x_b)}[/dim]")

        # Mapear speakers a tracks (basado en co-ocurrencia)
        speakers = list(set(seg.speaker for seg in filtered_segments))
        speaker_track_counts: dict[str, dict[int, int]] = {s: {track_a_id: 0, track_b_id: 0} for s in speakers}

        for speaker in speakers:
            my_segments = [s for s in filtered_segments if s.speaker == speaker]
            
            for seg in my_segments:
                for timestamp, faces in by_timestamp.items():
                    if seg.start <= timestamp <= seg.end:
                        for face in faces:
                            if face.track_id == track_a_id:
                                speaker_track_counts[speaker][track_a_id] += 1
                            elif face.track_id == track_b_id:
                                speaker_track_counts[speaker][track_b_id] += 1

        # Asignar speakers a posiciones
        speaker_positions = {}
        if len(speakers) == 2:
            s1, s2 = speakers
            s1_counts = speaker_track_counts[s1]
            s2_counts = speaker_track_counts[s2]
            
            # Asignación óptima
            if (s1_counts[track_a_id] + s2_counts[track_b_id]) >= (s1_counts[track_b_id] + s2_counts[track_a_id]):
                speaker_positions[s1] = track_map[track_a_id]
                speaker_positions[s2] = track_map[track_b_id]
            else:
                speaker_positions[s1] = track_map[track_b_id]
                speaker_positions[s2] = track_map[track_a_id]
        
        console.print(f"[dim]   Speaker mapping: {speaker_positions}[/dim]")

        # Generar trayectoria
        crop_width = int(video_height * target_aspect)
        min_x = crop_width // 2
        max_x = video_width - crop_width // 2

        crop_points = []
        last_center_x = video_width // 2

        # Inicializar con el primer speaker activo
        first_timestamp = min(by_timestamp.keys())
        for seg in filtered_segments:
            if seg.start <= first_timestamp <= seg.end:
                if seg.speaker in speaker_positions:
                    last_center_x = speaker_positions[seg.speaker]
                break

        for timestamp in sorted(by_timestamp.keys()):
            active_speaker = None
            for seg in filtered_segments:
                if seg.start <= timestamp <= seg.end:
                    active_speaker = seg.speaker
                    break

            if active_speaker and active_speaker in speaker_positions:
                center_x = speaker_positions[active_speaker]
                last_center_x = center_x
            else:
                center_x = last_center_x

            center_x = max(min_x, min(max_x, center_x))
            crop_points.append((timestamp, center_x))

        # Suavizado adaptativo
        if len(crop_points) > 1:
            smoothed = [crop_points[0]]
            
            for i in range(1, len(crop_points)):
                timestamp, target_x = crop_points[i]
                _, prev_x = smoothed[-1]
                
                dist = abs(target_x - prev_x)
                
                # Cambio de speaker = corte rápido
                # Mismo speaker = suavizado
                if dist > 200:
                    smoothing = 0.7  # Transición rápida pero no abrupta
                else:
                    smoothing = self.smoothing_factor
                
                smoothed_x = int((1 - smoothing) * prev_x + smoothing * target_x)
                smoothed.append((timestamp, smoothed_x))
            
            return smoothed

        return crop_points

    def _fixed_crop(
        self,
        detections: list[FaceDetection],
        video_width: int,
        video_height: int,
        target_aspect: float
    ) -> list[tuple[float, int]]:
        """Crop fijo cuando solo hay 1 persona."""
        if not detections:
            return [(0, video_width // 2)]
        
        avg_x = sum(d.center_x for d in detections) / len(detections)
        crop_width = int(video_height * target_aspect)
        min_x = crop_width // 2
        max_x = video_width - crop_width // 2
        fixed_x = max(min_x, min(max_x, int(avg_x)))
        
        timestamps = sorted(set(d.timestamp for d in detections))
        return [(t, fixed_x) for t in timestamps]

    def get_smooth_crop_trajectory(
        self,
        detections: list[FaceDetection],
        video_width: int,
        video_height: int,
        target_aspect: float = 9 / 16,
    ) -> list[tuple[float, int]]:
        """
        Generate a smooth crop trajectory based on the largest detected face.
        Used as fallback when speaker detection fails.
        """
        if not detections:
            return [(0, video_width // 2)]
            
        crop_width = int(video_height * target_aspect)
        min_x = crop_width // 2
        max_x = video_width - crop_width // 2
        
        # Group by timestamp
        by_timestamp = {}
        for d in detections:
            if d.timestamp not in by_timestamp:
                by_timestamp[d.timestamp] = []
            by_timestamp[d.timestamp].append(d)
            
        trajectory = []
        timestamps = sorted(by_timestamp.keys())
        
        if not timestamps:
             return [(0, video_width // 2)]
             
        # Initial position
        best_face_init = max(by_timestamp[timestamps[0]], key=lambda f: f.width * f.height)
        last_x = best_face_init.center_x
        
        for t in timestamps:
            faces = by_timestamp[t]
            # Pick largest face
            best_face = max(faces, key=lambda f: f.width * f.height)
            target_x = best_face.center_x
            
            # Simple smoothing
            smoothed_x = int(last_x * (1 - self.smoothing_factor) + target_x * self.smoothing_factor)
            clamped_x = max(min_x, min(max_x, smoothed_x))
            
            trajectory.append((t, clamped_x))
            last_x = smoothed_x
            
        return trajectory


# Función de compatibilidad con código existente
def track_face(
    video_path: Path | str,
    start_time: float = 0,
    end_time: float | None = None,
) -> list[tuple[float, int]]:
    """Compatibility wrapper."""
    video_path = Path(video_path)
    cap = cv2.VideoCapture(str(video_path))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    tracker = FaceTracker()
    detections = tracker.detect_faces(video_path, start_time, end_time)
    
    # Fallback simple si no hay speaker segments
    by_timestamp = {}
    for d in detections:
        if d.timestamp not in by_timestamp:
            by_timestamp[d.timestamp] = []
        by_timestamp[d.timestamp].append(d)
    
    trajectory = []
    for timestamp in sorted(by_timestamp.keys()):
        faces = by_timestamp[timestamp]
        largest = max(faces, key=lambda f: f.width * f.height)
        trajectory.append((timestamp, largest.center_x))
    
    return trajectory
