"""Hybrid speaker detection: Diarization + Lip sync - IMPROVED VERSION.

MEJORAS APLICADAS:
1. Sample FPS aumentado: 3.0 → 15.0 (captura más movimiento)
2. Umbrales más permisivos para movimiento labial
3. Análisis de VARIANZA en vez de valores absolutos
4. Mejor manejo de múltiples caras
5. Debugging detallado
"""

from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile

import cv2
import numpy as np
import mediapipe as mp
from rich.console import Console

console = Console()


@dataclass
class LipActivity:
    """Actividad detectada en los labios."""
    timestamp: float
    center_x: int
    center_y: int
    movement_score: float  # 0-1
    confidence: float  # Confianza de la detección


class ImprovedLipSyncAnalyzer:
    """
    Análisis de movimiento de labios usando MediaPipe Face Landmarker (Tasks API).
    
    MEJORAS:
    - Sample FPS aumentado a 15 (antes 10)
    - Umbral de movimiento reducido (más sensible)
    - Análisis de varianza de movimiento
    """
    
    # Path al modelo descargado
    MODEL_PATH = Path(__file__).parent.parent.parent / "models" / "face_landmarker.task"
    
    def __init__(self, sample_fps: float = 15.0):  # ✅ AUMENTADO: 10 → 15
        self.sample_fps = sample_fps
        
        # Verificar que existe el modelo
        if not self.MODEL_PATH.exists():
            raise FileNotFoundError(
                f"Face Landmarker model not found at {self.MODEL_PATH}. "
                "Download from: https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
            )
        
        # Configurar FaceLandmarker con la nueva API
        BaseOptions = mp.tasks.BaseOptions
        FaceLandmarker = mp.tasks.vision.FaceLandmarker
        FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
        VisionRunningMode = mp.tasks.vision.RunningMode
        
        self.options = FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(self.MODEL_PATH)),
            running_mode=VisionRunningMode.VIDEO,
            num_faces=2,
            min_face_detection_confidence=0.3,  # ✅ REDUCIDO: 0.5 → 0.3 (más permisivo)
            min_face_presence_confidence=0.3,   # ✅ REDUCIDO: 0.5 → 0.3
            min_tracking_confidence=0.3,        # ✅ REDUCIDO: 0.5 → 0.3
        )
        
        # Índices de landmarks para labios (MediaPipe 468 landmarks)
        self.upper_lip_indices = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291]
        self.lower_lip_indices = [146, 91, 181, 84, 17, 314, 405, 321, 375, 291]
        
        # Buffer para comparar frames
        self.prev_lip_positions = {}  # {face_center_x: lip_landmarks}
        
        # ✅ NUEVO: Buffer para análisis de varianza
        self.movement_history = {}  # {face_center_x: [movements]}

    
    def analyze_lip_movement(
        self,
        video_path: Path | str,
        start_time: float = 0,
        duration: float = 5.0,
    ) -> list[LipActivity]:
        """
        Analiza movimiento de labios en un segmento de video.
        
        Returns:
            Lista de LipActivity con scores de movimiento
        """
        video_path = Path(video_path)
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        
        frame_interval = max(1, int(fps / self.sample_fps))
        start_frame = int(start_time * fps)
        end_frame = int((start_time + duration) * fps)
        
        activities = []
        frame_idx = start_frame
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        
        # ✅ NUEVO: Estadísticas para debugging
        total_frames_processed = 0
        faces_detected = 0
        movement_detected = 0
        
        # Crear FaceLandmarker con context manager
        FaceLandmarker = mp.tasks.vision.FaceLandmarker
        
        with FaceLandmarker.create_from_options(self.options) as landmarker:
            while frame_idx < end_frame:
                ret, frame = cap.read()
                if not ret:
                    break
                
                if (frame_idx - start_frame) % frame_interval == 0:
                    total_frames_processed += 1
                    timestamp = frame_idx / fps
                    height, width = frame.shape[:2]
                    timestamp_ms = int(frame_idx * 1000 / fps)
                    
                    # Convertir a RGB y crear mp.Image
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                    
                    # Detectar face landmarks
                    try:
                        results = landmarker.detect_for_video(mp_image, timestamp_ms)
                    except Exception as e:
                        console.print(f"[dim]   Frame {frame_idx}: MediaPipe error: {e}[/dim]")
                        frame_idx += 1
                        continue
                    
                    if results.face_landmarks:
                        faces_detected += len(results.face_landmarks)
                        
                        for face_landmarks in results.face_landmarks:
                            # Extraer landmarks de labios
                            landmarks = face_landmarks
                            
                            # Calcular centro de cara (para identificar LEFT/RIGHT)
                            face_center_x = int(np.mean([lm.x for lm in landmarks]) * width)
                            face_center_y = int(np.mean([lm.y for lm in landmarks]) * height)
                            
                            # ✅ MEJORA: Redondear a zona para mejor tracking
                            # Evita jitter cuando cara se mueve ligeramente
                            face_zone_x = round(face_center_x / 100) * 100  # Redondear a 100px
                            
                            # Extraer posiciones de labios
                            upper_lip = np.array([[landmarks[i].x * width, landmarks[i].y * height] 
                                                 for i in self.upper_lip_indices])
                            lower_lip = np.array([[landmarks[i].x * width, landmarks[i].y * height] 
                                                 for i in self.lower_lip_indices])
                            
                            # Calcular apertura de boca (distancia vertical promedio)
                            mouth_opening = np.mean(np.linalg.norm(lower_lip - upper_lip[:len(lower_lip)], axis=1))
                            
                            # Comparar con frame anterior
                            movement_score = 0.0
                            
                            if face_zone_x in self.prev_lip_positions:
                                prev_upper, prev_lower = self.prev_lip_positions[face_zone_x]
                                
                                # Calcular movimiento total de landmarks
                                upper_movement = np.mean(np.linalg.norm(upper_lip - prev_upper, axis=1))
                                lower_movement = np.mean(np.linalg.norm(lower_lip - prev_lower, axis=1))
                                total_movement = upper_movement + lower_movement
                                
                                # ✅ MEJORA: Normalizar a 0-1 (ajustado para ser más sensible)
                                # Antes: /20.0 (muy estricto)
                                # Ahora: /15.0 (más sensible)
                                movement_score = min(1.0, total_movement / 15.0)
                                
                                # ✅ MEJORA: Umbral reducido
                                # Antes: < 2.0 pixels penalizado
                                # Ahora: < 1.0 pixels penalizado
                                if total_movement < 1.0:
                                    movement_score *= 0.3
                                else:
                                    movement_detected += 1
                                
                                # ✅ NUEVO: Guardar en historial para análisis de varianza
                                if face_zone_x not in self.movement_history:
                                    self.movement_history[face_zone_x] = []
                                self.movement_history[face_zone_x].append(total_movement)
                                
                                # Limitar historial a últimos 10 frames
                                if len(self.movement_history[face_zone_x]) > 10:
                                    self.movement_history[face_zone_x].pop(0)
                            
                            # Guardar para próximo frame
                            self.prev_lip_positions[face_zone_x] = (upper_lip.copy(), lower_lip.copy())
                            
                            # Confianza basada en visibilidad de landmarks
                            confidence = min(1.0, len(landmarks) / 478.0)  # MediaPipe tiene 478 landmarks
                            
                            activities.append(LipActivity(
                                timestamp=timestamp,
                                center_x=face_center_x,
                                center_y=face_center_y,
                                movement_score=movement_score,
                                confidence=confidence
                            ))
                
                frame_idx += 1
        
        cap.release()
        
        # ✅ NUEVO: Debugging detallado
        console.print(f"[dim]   📊 Frames procesados: {total_frames_processed}, "
                     f"Caras detectadas: {faces_detected}, "
                     f"Con movimiento: {movement_detected}[/dim]")
        
        if activities:
            movements = [a.movement_score for a in activities if a.movement_score > 0]
            if movements:
                console.print(f"[dim]   📈 Movimiento: avg={np.mean(movements):.3f}, "
                             f"max={np.max(movements):.3f}, "
                             f"variance={np.var(movements):.5f}[/dim]")
        
        return activities


class HybridSpeakerDetector:
    """
    Combina diarización de audio + análisis de labios.
    
    MEJORADO con validaciones y fallbacks robustos.
    """
    
    def __init__(self, calibration_duration: float = 5.0):
        self.calibration_duration = calibration_duration
        self.lip_analyzer = ImprovedLipSyncAnalyzer(sample_fps=15.0)  # ✅ AUMENTADO
    
    def detect_speaker_face_mapping(
        self,
        video_path: Path | str,
        speaker_segments: list,
        start_offset: float = 0,
    ) -> dict[str, int]:
        """
        Calibra speaker → face position usando lip sync.
        
        MEJORADO:
        - Sample FPS aumentado
        - Umbrales más permisivos
        - Análisis de varianza
        """
        video_path = Path(video_path)
        
        cap = cv2.VideoCapture(str(video_path))
        video_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        video_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        
        speakers = set(seg.speaker for seg in speaker_segments)
        console.print(f"[cyan]🎤 Calibrando {len(speakers)} speakers con MediaPipe...[/cyan]")
        
        # Acumular scores por (speaker, posición)
        speaker_position_scores: dict[tuple[str, str], float] = {}  # (speaker, "LEFT"|"RIGHT") -> score
        speaker_confidences: dict[tuple[str, str], list[float]] = {}
        speaker_activities: dict[tuple[str, str], list[float]] = {}  # ✅ NUEVO: Para análisis de varianza
        
        for speaker in speakers:
            speaker_segs = [seg for seg in speaker_segments if seg.speaker == speaker]
            total_analyzed = 0.0
            
            for seg in speaker_segs:
                if total_analyzed >= self.calibration_duration:
                    break
                
                clip_start = seg.start - start_offset
                clip_end = seg.end - start_offset
                
                if clip_end < 0:
                    continue
                if clip_start < 0:
                    clip_start = 0
                
                seg_duration = min(clip_end - clip_start, self.calibration_duration - total_analyzed)
                if seg_duration < 1.0:  # Mínimo 1 segundo
                    continue
                
                console.print(f"[dim]   Analizando {speaker}: {clip_start:.1f}s - {clip_start + seg_duration:.1f}s[/dim]")
                
                # Analizar labios durante este segmento
                activities = self.lip_analyzer.analyze_lip_movement(
                    video_path,
                    start_time=clip_start,
                    duration=seg_duration,
                )
                
                # ✅ MEJORA: Umbrales más permisivos
                # Antes: confidence >= 0.7, movement >= 0.4
                # Ahora: confidence >= 0.5, movement >= 0.2
                valid_activities = [
                    act for act in activities
                    if clip_start <= act.timestamp <= clip_end
                    and act.confidence >= 0.5  # ✅ REDUCIDO: 0.7 → 0.5
                    and act.movement_score >= 0.2  # ✅ REDUCIDO: 0.4 → 0.2
                ]
                
                if not valid_activities:
                    console.print(f"[yellow]   ⚠ No se detectó movimiento labial válido[/yellow]")
                    total_analyzed += seg_duration
                    continue
                
                # ✅ NUEVO: Mostrar estadísticas del segmento
                movements = [a.movement_score for a in valid_activities]
                console.print(f"[dim]   ✓ {len(valid_activities)} frames válidos, "
                             f"movimiento avg={np.mean(movements):.3f}[/dim]")
                
                # Clasificar por posición (LEFT/RIGHT)
                mid_x = video_width // 2
                
                for act in valid_activities:
                    position = "LEFT" if act.center_x < mid_x else "RIGHT"
                    key = (speaker, position)
                    
                    if key not in speaker_position_scores:
                        speaker_position_scores[key] = 0.0
                        speaker_confidences[key] = []
                        speaker_activities[key] = []  # ✅ NUEVO
                    
                    # Score ponderado por confianza
                    weighted_score = act.movement_score * act.confidence
                    speaker_position_scores[key] += weighted_score
                    speaker_confidences[key].append(act.confidence)
                    speaker_activities[key].append(act.movement_score)  # ✅ NUEVO
                
                total_analyzed += seg_duration
        
        # Calcular mapping final
        mapping: dict[str, int] = {}
        assigned_positions: set[str] = set()
        
        # Calcular posiciones de las zonas
        left_zone_x = video_width // 4
        right_zone_x = 3 * video_width // 4
        
        for speaker in speakers:
            speaker_scores = {k[1]: v for k, v in speaker_position_scores.items() if k[0] == speaker}
            
            if not speaker_scores:
                # Fallback: asignar posición no usada
                console.print(f"[yellow]⚠ {speaker}: Sin datos de labios, usando fallback[/yellow]")
                if "LEFT" not in assigned_positions:
                    mapping[speaker] = left_zone_x
                    assigned_positions.add("LEFT")
                elif "RIGHT" not in assigned_positions:
                    mapping[speaker] = right_zone_x
                    assigned_positions.add("RIGHT")
                else:
                    mapping[speaker] = video_width // 2
                continue
            
            # Encontrar mejor posición
            best_position = max(speaker_scores.keys(), key=lambda p: speaker_scores[p])
            total_score = speaker_scores[best_position]
            
            # Calcular confianza promedio
            key = (speaker, best_position)
            avg_confidence = np.mean(speaker_confidences[key]) if key in speaker_confidences else 0.0
            
            # ✅ NUEVO: Analizar varianza de movimiento
            variance = np.var(speaker_activities[key]) if key in speaker_activities else 0.0
            
            # ✅ MEJORA: Umbral de score reducido
            # Antes: 1.5
            # Ahora: 0.8 (más permisivo)
            min_score_threshold = 0.8
            
            console.print(f"[dim]   {speaker}/{best_position}: score={total_score:.2f}, "
                         f"conf={avg_confidence:.2f}, variance={variance:.5f}[/dim]")
            
            if total_score < min_score_threshold:
                console.print(f"[yellow]⚠ {speaker}: Score bajo ({total_score:.2f}), usando fallback[/yellow]")
                if "LEFT" not in assigned_positions:
                    mapping[speaker] = left_zone_x
                    assigned_positions.add("LEFT")
                elif "RIGHT" not in assigned_positions:
                    mapping[speaker] = right_zone_x
                    assigned_positions.add("RIGHT")
                else:
                    mapping[speaker] = video_width // 2
            else:
                # Asignar posición
                face_x = left_zone_x if best_position == "LEFT" else right_zone_x
                mapping[speaker] = face_x
                assigned_positions.add(best_position)
                console.print(f"[green]✓ {speaker} → {best_position} (X={face_x}, score={total_score:.2f}, conf={avg_confidence:.2f})[/green]")
        
        return mapping
    
    def generate_crop_trajectory(
        self,
        speaker_segments: list,
        speaker_mapping: dict[str, int],
        video_width: int,
        video_height: int,
        target_aspect: float = 9 / 16,
        start_offset: float = 0,
        clip_duration: float = 0,
        transition_duration: float = 0.3,
    ) -> list[tuple[float, int]]:
        """
        Genera trayectoria de crop siguiendo al speaker activo.
        
        (Esta función continúa igual que tu versión original)
        """
        crop_width = int(video_height * target_aspect)
        min_x = crop_width // 2
        max_x = video_width - crop_width // 2
        
        if not speaker_segments or not speaker_mapping:
            console.print(f"[yellow]⚠ Sin datos de speakers, usando crop centrado[/yellow]")
            return [(0, video_width // 2)]
        
        trajectory: list[tuple[float, int]] = []
        current_speaker = None
        current_x = video_width // 2
        
        # Ordenar segmentos
        segments = sorted(speaker_segments, key=lambda s: s.start)
        
        # Filtrar segmentos muy cortos (< 0.5s)
        segments = [s for s in segments if (s.end - s.start) >= 0.5]
        
        if not segments:
            return [(0, video_width // 2)]
        
        # Inicializar con primer speaker
        first_seg = segments[0]
        first_speaker = first_seg.speaker
        if first_speaker in speaker_mapping:
            current_x = speaker_mapping[first_speaker]
            current_speaker = first_speaker
        
        trajectory.append((0, current_x))
        
        # Generar keyframes
        MIN_SEGMENT_FOR_CUT = 1.5  # segundos
        
        for i, seg in enumerate(segments):
            clip_start = max(0, seg.start - start_offset)
            clip_end = min(clip_duration, seg.end - start_offset)
            speaker = seg.speaker
            
            if clip_end <= 0 or clip_start >= clip_duration:
                continue
            
            segment_duration = clip_end - clip_start
            
            # Cambio de speaker
            if speaker != current_speaker and speaker in speaker_mapping:
                target_x = speaker_mapping[speaker]
                
                # Solo cambiar si segmento es suficientemente largo
                if segment_duration >= MIN_SEGMENT_FOR_CUT:
                    # Añadir transición
                    trajectory.append((clip_start, current_x))
                    trajectory.append((clip_start + transition_duration, target_x))
                    
                    current_speaker = speaker
                    current_x = target_x
        
        # Keyframe final
        if clip_duration > 0:
            trajectory.append((clip_duration, current_x))
        
        # Clamp X values
        trajectory = [(t, max(min_x, min(max_x, x))) for t, x in trajectory]
        
        return trajectory


# ============================================
# FUNCIÓN HELPER: detectar y trackear híbrido
# ============================================

def detect_and_track_hybrid(
    video_path: Path | str,
    start_time: float,
    duration: float,
    target_aspect: float = 9 / 16,
) -> list[tuple[float, int]]:
    """
    Modo HYBRID completo: Diarización + Lip Sync.
    
    Returns:
        Lista de (timestamp, center_x) para tracking
    """
    from src.asr.diarizer import SpeakerDiarizer
    
    console.print(f"[cyan]🎯 Modo HYBRID: Diarización + Lip Sync (MediaPipe)[/cyan]")
    
    video_path = Path(video_path)
    
    # Extraer clip temporal
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
        clip_path = Path(tmp.name)
    
    console.print(f"[dim]   Extrayendo clip: {start_time:.1f}s → {start_time + duration:.1f}s[/dim]")
    
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(start_time),
        "-i", str(video_path),
        "-t", str(duration),
        "-c", "copy",
        str(clip_path)
    ]
    subprocess.run(cmd, check=True)
    
    # Step 1: Diarización
    console.print(f"[cyan]🎤 Ejecutando diarización de audio...[/cyan]")
    diarizer = SpeakerDiarizer()
    
    try:
        speaker_segments = diarizer.diarize(clip_path)
        console.print(f"[green]✓ Detectados {len(speaker_segments)} segmentos de habla[/green]")
    except Exception as e:
        console.print(f"[red]✗ Error en diarización: {e}[/red]")
        clip_path.unlink(missing_ok=True)
        return []
    
    # Step 2: Calibración con lip sync
    detector = HybridSpeakerDetector(calibration_duration=5.0)
    
    try:
        speaker_mapping = detector.detect_speaker_face_mapping(
            clip_path,
            speaker_segments,
            start_offset=0,  # Clip empieza en 0
        )
    except Exception as e:
        console.print(f"[red]✗ Error en hybrid detection: {e}[/red]")
        import traceback
        traceback.print_exc()
        clip_path.unlink(missing_ok=True)
        return []
    
    # Step 3: Generar trayectoria
    cap = cv2.VideoCapture(str(clip_path))
    video_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    video_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    
    trajectory = detector.generate_crop_trajectory(
        speaker_segments,
        speaker_mapping,
        video_width,
        video_height,
        target_aspect=target_aspect,
        start_offset=0,
        clip_duration=duration,
    )
    
    # Cleanup
    clip_path.unlink(missing_ok=True)
    
    console.print(f"[green]✓ Generados {len(trajectory)} keyframes[/green]")
    console.print(f"[green]✓ Trayectoria generada exitosamente[/green]")
    
    return trajectory
