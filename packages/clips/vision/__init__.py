"""
Vision module for speaker tracking and intelligent video reframing.

Components:
- face_tracker: Face detection with MediaPipe + DeepSORT persistent tracking
- hybrid_speaker_detector: Diarization + lip sync for speaker-aware tracking
- reframer: Convert 16:9 video to 9:16 with smart cropping
- reframer: Dynamic video reframing and layout construction
"""

from packages.clips.vision.face_tracker import FaceTracker, FaceDetection, track_face
from packages.clips.vision.reframer import VideoReframer, reframe_video
from packages.clips.vision.hybrid_speaker_detector import HybridSpeakerDetector, detect_and_track_hybrid
from packages.clips.vision.reframer import reframe_video

__all__ = [
    "FaceTracker", "FaceDetection", "track_face",
    "HybridSpeakerDetector", "detect_and_track_hybrid",
    "VideoReframer", "reframe_video",
    "reframe_video",
]

