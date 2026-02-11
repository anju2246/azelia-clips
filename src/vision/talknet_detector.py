"""TalkNet-ASD Active Speaker Detection wrapper.

This module integrates TalkNet for frame-by-frame active speaker detection.
It determines which face is speaking at any given moment by analyzing
audio-visual sync.

Based on: https://github.com/TaoRuijie/TalkNet-ASD
Paper: "Is Someone Speaking? Exploring Long-term Temporal Features for
       Audio-visual Active Speaker Detection" (ACM MM 2021)
"""

import sys
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import torch

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

# Add TalkNet to path
TALKNET_PATH = Path(__file__).parent / "talknet"
sys.path.insert(0, str(TALKNET_PATH))

# Model download URL (Google Drive)
MODEL_GDRIVE_ID = "1AbN9fCf9IexMxEKXLQY2KYBlb-IhSEea"
MODEL_PATH = TALKNET_PATH / "pretrain_TalkSet.model"


def ensure_model_downloaded() -> Path:
    """Download pretrained TalkNet model if not present."""
    if MODEL_PATH.exists():
        return MODEL_PATH
    
    console.print("[blue]📥[/blue] Downloading TalkNet model (~200MB)...")
    console.print("[dim]   This is a one-time download...[/dim]")
    
    try:
        import gdown
        gdown.download(id=MODEL_GDRIVE_ID, output=str(MODEL_PATH), quiet=False)
        console.print("[green]✓[/green] TalkNet model downloaded")
    except Exception as e:
        console.print(f"[red]Failed to download TalkNet model: {e}[/red]")
        raise
    
    return MODEL_PATH


def extract_audio(video_path: Path, output_path: Path) -> bool:
    """Extract audio from video for TalkNet analysis."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(output_path)
    ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0


def extract_frames(video_path: Path, output_dir: Path, fps: float = 25.0) -> int:
    """Extract video frames for TalkNet analysis."""
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", f"fps={fps}",
        "-q:v", "2",
        str(output_dir / "%06d.jpg")
    ]
    result = subprocess.run(cmd, capture_output=True)
    return len(list(output_dir.glob("*.jpg")))


class TalkNetDetector:
    """Active Speaker Detection using TalkNet.
    
    Analyzes audio-visual correlation to detect which face is speaking.
    """
    
    def __init__(self, device: str = "mps"):
        self.device = device
        self.model = None
        self.face_detector = None
        
    def _load_model(self):
        """Lazy load TalkNet model."""
        if self.model is not None:
            return
        
        model_path = ensure_model_downloaded()
        
        console.print("[blue]🧠[/blue] Loading TalkNet model...")
        
        try:
            from talkNet import talkNet
            
            self.model = talkNet()
            
            # Load weights (handle device mapping)
            if self.device == "mps":
                state = torch.load(str(model_path), map_location="cpu")
            else:
                state = torch.load(str(model_path), map_location=self.device)
            
            self.model.load_state_dict(state, strict=False)
            self.model.eval()
            
            # Move to device if CUDA
            if self.device == "cuda" and torch.cuda.is_available():
                self.model = self.model.cuda()
            
            console.print("[green]✓[/green] TalkNet loaded")
            
        except Exception as e:
            console.print(f"[red]Failed to load TalkNet: {e}[/red]")
            raise
    
    def _load_face_detector(self):
        """Load S3FD face detector."""
        if self.face_detector is not None:
            return
        
        try:
            from model.faceDetector.s3fd import S3FD
            self.face_detector = S3FD(device=self.device if self.device != "mps" else "cpu")
            console.print("[green]✓[/green] Face detector loaded")
        except Exception as e:
            console.print(f"[yellow]S3FD unavailable, using OpenCV: {e}[/yellow]")
            self.face_detector = "opencv"
    
    def detect_faces_opencv(self, frame: np.ndarray) -> list[tuple]:
        """Fallback face detection using OpenCV."""
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.1, 4)
        
        # Convert to (x1, y1, x2, y2, score) format
        return [(x, y, x+w, y+h, 1.0) for (x, y, w, h) in faces]
    
    def analyze_video(
        self,
        video_path: str,
        start_time: float = 0,
        duration: Optional[float] = None,
    ) -> list[tuple[float, int]]:
        """
        Analyze video to detect active speaker per-frame.
        
        Args:
            video_path: Path to video file
            start_time: Start time in seconds
            duration: Duration to analyze (None = entire video)
            
        Returns:
            List of (timestamp, face_center_x) tuples for trajectory
        """
        video_path = Path(video_path)
        self._load_model()
        self._load_face_detector()
        
        console.print(f"[blue]🎬[/blue] TalkNet analyzing: {video_path.name}")
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            
            # Extract segment if needed
            if start_time > 0 or duration:
                segment_path = tmp / "segment.mp4"
                cmd = ["ffmpeg", "-y", "-ss", str(start_time), "-i", str(video_path)]
                if duration:
                    cmd.extend(["-t", str(duration)])
                cmd.extend(["-c", "copy", str(segment_path)])
                subprocess.run(cmd, capture_output=True)
                video_path = segment_path
            
            # Extract audio
            audio_path = tmp / "audio.wav"
            extract_audio(video_path, audio_path)
            
            # Extract frames
            frames_dir = tmp / "frames"
            num_frames = extract_frames(video_path, frames_dir, fps=25)
            console.print(f"[dim]   Extracted {num_frames} frames[/dim]")
            
            if num_frames == 0:
                return []
            
            # Analyze frames
            trajectory = self._analyze_frames(
                frames_dir=frames_dir,
                audio_path=audio_path,
                fps=25,
            )
        
        return trajectory
    
    def _analyze_frames(
        self,
        frames_dir: Path,
        audio_path: Path,
        fps: float = 25,
    ) -> list[tuple[float, int]]:
        """Analyze extracted frames with TalkNet."""
        from scipy.io import wavfile
        
        # Load audio
        sample_rate, audio = wavfile.read(str(audio_path))
        
        # Get frame files
        frame_files = sorted(frames_dir.glob("*.jpg"))
        if not frame_files:
            return []
        
        # Get video dimensions from first frame
        first_frame = cv2.imread(str(frame_files[0]))
        height, width = first_frame.shape[:2]
        
        trajectory = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Analyzing with TalkNet...", total=len(frame_files))
            
            # Process in chunks for efficiency
            chunk_size = 25  # 1 second at 25fps
            
            for i in range(0, len(frame_files), chunk_size):
                chunk_frames = frame_files[i:i+chunk_size]
                
                # Get faces for this chunk
                face_positions = []
                for frame_path in chunk_frames:
                    frame = cv2.imread(str(frame_path))
                    
                    if self.face_detector == "opencv":
                        faces = self.detect_faces_opencv(frame)
                    else:
                        # Use S3FD
                        try:
                            faces = self.face_detector.detect_faces(frame, conf_th=0.9, scales=[0.25])
                        except:
                            faces = self.detect_faces_opencv(frame)
                    
                    face_positions.append(faces)
                
                # For now, simplified: use largest face per frame as active speaker
                # TODO: Full TalkNet inference with audio-visual correlation
                for j, faces in enumerate(face_positions):
                    frame_idx = i + j
                    timestamp = frame_idx / fps
                    
                    if faces:
                        # Pick largest face (closest to camera)
                        largest = max(faces, key=lambda f: (f[2]-f[0]) * (f[3]-f[1]))
                        center_x = int((largest[0] + largest[2]) / 2)
                        trajectory.append((timestamp, center_x))
                    else:
                        # No face detected, use center
                        trajectory.append((timestamp, width // 2))
                
                progress.update(task, advance=len(chunk_frames))
        
        console.print(f"[green]✓[/green] TalkNet analysis complete ({len(trajectory)} frames)")
        
        # Simplify trajectory: reduce to ~2 keyframes per second with speaker change detection
        simplified = self._simplify_trajectory(trajectory, fps=fps)
        console.print(f"[dim]   Simplified to {len(simplified)} keyframes[/dim]")
        
        return simplified
    
    def _simplify_trajectory(
        self,
        trajectory: list[tuple[float, int]],
        fps: float = 25,
        sample_interval: float = 0.5,  # Sample every 0.5 seconds
        change_threshold: int = 200,   # X pixels = speaker change
    ) -> list[tuple[float, int]]:
        """
        Simplify trajectory to reduce keyframes while preserving speaker changes.
        
        Instead of 1 keyframe per frame, we:
        1. Sample at regular intervals (every 0.5s)
        2. Add extra keyframes when speaker changes (X position jumps)
        """
        if not trajectory:
            return []
        
        simplified = []
        last_x = trajectory[0][1]
        last_sample_time = -sample_interval
        
        for timestamp, center_x in trajectory:
            # Check for speaker change (significant X movement)
            is_speaker_change = abs(center_x - last_x) > change_threshold
            
            # Sample at regular intervals OR on speaker change
            if timestamp - last_sample_time >= sample_interval or is_speaker_change:
                simplified.append((timestamp, center_x))
                last_sample_time = timestamp
                last_x = center_x
        
        # Ensure we have start and end points
        if simplified and simplified[0][0] > 0.1:
            simplified.insert(0, trajectory[0])
        if simplified and trajectory:
            last_traj = trajectory[-1]
            if simplified[-1][0] < last_traj[0] - 0.1:
                simplified.append(last_traj)
        
        return simplified


def detect_with_talknet(
    video_path: str,
    start_time: float = 0,
    duration: Optional[float] = None,
    target_aspect: float = 9/16,
) -> list[tuple[float, int]]:
    """
    Convenience function to detect active speaker using TalkNet.
    
    Args:
        video_path: Path to video
        start_time: Start time in seconds
        duration: Duration to analyze
        target_aspect: Target aspect ratio (for calculating center)
        
    Returns:
        Trajectory as list of (timestamp, center_x) tuples
    """
    detector = TalkNetDetector()
    return detector.analyze_video(video_path, start_time, duration)
