"""
Vision module for biometric face tracking and intelligent video reframing.

Components:
- face_tracker: Face detection (MTCNN) + identity (FaceNet/InceptionResnetV1)
- reframer: Dynamic video reframing and layout construction
"""

from packages.clips.vision.face_tracker import (
    FaceDetection,
    FaceIdentity,
    FaceTracker,
    IdentityStore,
    track_face,
)
from packages.clips.vision.reframer import VideoReframer, reframe_video

__all__ = [
    "FaceTracker", "FaceDetection", "FaceIdentity", "IdentityStore",
    "track_face",
    "VideoReframer", "reframe_video",
]
