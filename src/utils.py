"""Utility classes for resource management and cleanup."""

import json
from pathlib import Path
import subprocess
import tempfile

from rich.console import Console

console = Console()


class TempFileManager:
    """Context manager for guaranteed cleanup of temporary files.
    
    Solves the problem of orphaned temp files when exceptions occur.
    
    Usage:
        with TempFileManager() as tmp:
            video1 = tmp.create('.mp4')
            video2 = tmp.create('.mp4')
            # ... process videos ...
        # All temp files automatically deleted, even if exception occurred
    """
    
    def __init__(self, prefix: str = "sfc_"):
        self.prefix = prefix
        self.files: list[Path] = []
    
    def create(self, suffix: str) -> Path:
        """Create a new temporary file and track it for cleanup.
        
        Args:
            suffix: File extension (e.g., '.mp4', '.wav')
            
        Returns:
            Path to the temporary file
        """
        tmp = tempfile.NamedTemporaryFile(
            suffix=suffix,
            prefix=self.prefix,
            delete=False
        )
        tmp.close()  # Close immediately so FFmpeg can use it
        path = Path(tmp.name)
        self.files.append(path)
        return path
    
    def cleanup(self):
        """Delete all tracked temporary files."""
        for f in self.files:
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass  # Best effort cleanup
        self.files.clear()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False  # Don't suppress exceptions


# Default FFmpeg timeout (5 minutes per clip, adjust as needed)
FFMPEG_TIMEOUT = 300  # seconds


def run_ffmpeg(
    cmd: list[str],
    timeout: int = FFMPEG_TIMEOUT,
    check: bool = True,
    capture_output: bool = True,
) -> subprocess.CompletedProcess:
    """Run FFmpeg command with timeout protection.
    
    Prevents infinite hangs that can occur with FFmpeg on corrupt files
    or when encoding gets stuck.
    
    Args:
        cmd: FFmpeg command as list of strings
        timeout: Maximum seconds to wait (default: 300s = 5 min)
        check: Raise CalledProcessError on non-zero exit (default: True)
        capture_output: Capture stdout/stderr (default: True)
        
    Returns:
        CompletedProcess with stdout/stderr
        
    Raises:
        subprocess.TimeoutExpired: If command exceeds timeout
        subprocess.CalledProcessError: If check=True and command fails
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True,
            timeout=timeout,
        )
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )
        return result
    except subprocess.TimeoutExpired:
        console.print(f"[red]⚠️ FFmpeg timeout after {timeout}s[/red]")
        raise


def validate_video(video_path: Path | str) -> dict:
    """Validate that a video file is usable for processing.
    
    Checks:
    - File exists
    - Has video stream
    - Has audio stream
    - Has valid duration
    - Has minimum resolution
    
    Args:
        video_path: Path to video file
        
    Returns:
        Dict with video metadata:
        {
            'valid': bool,
            'errors': list[str],
            'width': int,
            'height': int,
            'duration': float,
            'has_audio': bool,
            'fps': float
        }
    """
    video_path = Path(video_path)
    result = {
        'valid': False,
        'errors': [],
        'width': 0,
        'height': 0,
        'duration': 0.0,
        'has_audio': False,
        'fps': 0.0
    }
    
    if not video_path.exists():
        result['errors'].append(f"File not found: {video_path}")
        return result
    
    # Use ffprobe to get video info
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(video_path)
    ]
    
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            # Try fallback to ffmpeg -i
            return _validate_video_ffmpeg_fallback(video_path, result)
        
        data = json.loads(proc.stdout)
        
        # Check for video stream
        video_stream = None
        audio_stream = None
        for stream in data.get('streams', []):
            if stream.get('codec_type') == 'video' and video_stream is None:
                video_stream = stream
            elif stream.get('codec_type') == 'audio' and audio_stream is None:
                audio_stream = stream
        
        if video_stream is None:
            # Final attempt with ffmpeg fallback
            return _validate_video_ffmpeg_fallback(video_path, result)
        
        # Extract video info
        result['width'] = int(video_stream.get('width', 0))
        result['height'] = int(video_stream.get('height', 0))
        
        # Parse FPS (can be "30/1" or "29.97")
        fps_str = video_stream.get('r_frame_rate', '0/1')
        if '/' in fps_str:
            num, den = map(float, fps_str.split('/'))
            result['fps'] = num / den if den > 0 else 0
        else:
            result['fps'] = float(fps_str)
        
        # Duration from format or stream
        duration = float(data.get('format', {}).get('duration', 0))
        if duration == 0:
            duration = float(video_stream.get('duration', 0))
        result['duration'] = duration
        
        result['has_audio'] = audio_stream is not None
        result['valid'] = result['width'] > 0 and result['duration'] > 0
        
    except (FileNotFoundError, Exception):
        # If ffprobe not found or other bug, try ffmpeg
        return _validate_video_ffmpeg_fallback(video_path, result)
        
    return result


def _validate_video_ffmpeg_fallback(video_path: Path, result: dict) -> dict:
    """Fallback to ffmpeg -i when ffprobe is missing."""
    import re
    
    cmd = ["ffmpeg", "-i", str(video_path)]
    try:
        # ffmpeg outputs info to stderr
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = proc.stderr
        
        # Extract Resolution: e.g. "1920x1080"
        res_match = re.search(r"Video:.* (\d{3,5})x(\d{3,5})", output)
        if res_match:
            result['width'] = int(res_match.group(1))
            result['height'] = int(res_match.group(2))
            
        # Extract Duration: e.g. "Duration: 01:02:43.12"
        dur_match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2})\.(\d{2})", output)
        if dur_match:
            h, m, s, ms = map(int, dur_match.groups())
            result['duration'] = h * 3600 + m * 60 + s + ms / 100.0
            
        # Extract FPS: e.g. "30 fps"
        fps_match = re.search(r"(\d+(\.\d+)?) fps", output)
        if fps_match:
            result['fps'] = float(fps_match.group(1))
            
        # Check for Audio
        result['has_audio'] = "Audio:" in output
        
        # Final validation
        if result['width'] > 0 and result['duration'] > 0:
            result['valid'] = True
        else:
            result['errors'].append("ffmpeg fallback failed to extract metadata")
            result['valid'] = False
            
    except Exception as e:
        result['errors'].append(f"Video validation failed totally: {e}")
        result['valid'] = False
        
    return result
