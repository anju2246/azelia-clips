"""
Vision module for speaker tracking and intelligent video reframing.

Components:
- face_tracker: Face detection with MediaPipe + DeepSORT persistent tracking
- hybrid_speaker_detector: Diarization + lip sync for speaker-aware tracking
- reframer: Convert 16:9 video to 9:16 with smart cropping
- split_screen: Create split-screen layouts with dynamic tracking
"""

from src.vision.face_tracker import FaceTracker, FaceDetection, track_face
from src.vision.reframer import VideoReframer, reframe_video
from src.vision.hybrid_speaker_detector import HybridSpeakerDetector, detect_and_track_hybrid
from src.vision.split_screen import create_split_screen_tracked

__all__ = [
    "FaceTracker", "FaceDetection", "track_face",
    "HybridSpeakerDetector", "detect_and_track_hybrid",
    "VideoReframer", "reframe_video",
    "create_split_screen_tracked",
]

