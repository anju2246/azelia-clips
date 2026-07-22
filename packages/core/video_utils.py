"""
Video utility decorators and context managers to ensure safe resource handling.
"""
from typing import Any

import cv2


class VideoCaptureContext:
    """
    Context manager for cv2.VideoCapture to ensure the capture is properly released
    even if an exception occurs during frame extraction.

    Usage:
        with VideoCaptureContext("video.mp4") as cap:
            fps = cap.get(cv2.CAP_PROP_FPS)
            ret, frame = cap.read()
    """

    def __init__(self, *args: Any, **kwargs: Any):
        self._cap = cv2.VideoCapture(*args, **kwargs)
        if not self._cap.isOpened():
            raise ValueError(f"Failed to open video capture with args: {args}, kwargs: {kwargs}")

    def __enter__(self) -> cv2.VideoCapture:
        return self._cap

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._cap:
            self._cap.release()
