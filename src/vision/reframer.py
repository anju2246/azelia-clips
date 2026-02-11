"""Video reframing from 16:9 to 9:16 with intelligent cropping."""

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


@dataclass
class ReframeResult:
    """Result of video reframing operation."""
    input_path: Path
    output_path: Path
    original_resolution: tuple[int, int]
    output_resolution: tuple[int, int]
    duration: float


class VideoReframer:
    """
    Reframe horizontal (16:9) video to vertical (9:16) format.
    
    Supports:
    - Center crop (simple)
    - Dynamic crop following detected speakers
    """

    def __init__(
        self,
        output_width: int = 1080,
        output_height: int = 1920,
    ):
        self.output_width = output_width
        self.output_height = output_height

    def _get_video_info(self, video_path: Path) -> dict:
        """Get video metadata using OpenCV."""
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {video_path}")

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps if fps > 0 else 0

        cap.release()

        return {
            "width": width,
            "height": height,
            "fps": fps,
            "duration": duration,
        }

    def reframe_center(
        self,
        input_path: Path | str,
        output_path: Path | str,
        start_time: float = 0,
        duration: float | None = None,
    ) -> ReframeResult:
        """
        Simple center crop from horizontal to vertical.

        Args:
            input_path: Source video path
            output_path: Output video path
            start_time: Start time in seconds
            duration: Duration in seconds (None = full video)

        Returns:
            ReframeResult with metadata
        """
        input_path = Path(input_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        info = self._get_video_info(input_path)
        src_width = info["width"]
        src_height = info["height"]

        # Calculate crop dimensions
        # We want to crop a vertical slice from the center
        target_aspect = self.output_width / self.output_height
        crop_width = int(src_height * target_aspect)
        crop_x = (src_width - crop_width) // 2

        console.print(f"[blue]🎬[/blue] Reframing to vertical ({self.output_width}x{self.output_height})")
        console.print(f"[dim]   Source: {src_width}x{src_height} → Crop: {crop_width}x{src_height}[/dim]")

        # Build FFmpeg command
        filter_complex = f"crop={crop_width}:{src_height}:{crop_x}:0,scale={self.output_width}:{self.output_height}"

        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(start_time),
            "-i", str(input_path),
        ]

        if duration:
            cmd.extend(["-t", str(duration)])

        cmd.extend([
            "-vf", filter_complex,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ])

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Encoding vertical video...", total=None)
            result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            console.print(f"[red]FFmpeg error:[/red] {result.stderr[:300]}")
            raise RuntimeError("Video reframing failed")

        console.print(f"[green]✓[/green] Saved to {output_path}")

        return ReframeResult(
            input_path=input_path,
            output_path=output_path,
            original_resolution=(src_width, src_height),
            output_resolution=(self.output_width, self.output_height),
            duration=duration or info["duration"],
        )

    def reframe_dynamic(
        self,
        input_path: Path | str,
        output_path: Path | str,
        crop_trajectory: list[tuple[float, int]],
        start_time: float = 0,
        duration: float | None = None,
        zoom_factor: float = 0.7,  # 0.7 = less zoom (more context), 1.0 = tight crop
    ) -> ReframeResult:
        """
        Dynamic crop following speaker positions.

        Args:
            input_path: Source video path
            output_path: Output video path
            crop_trajectory: List of (timestamp, crop_center_x) tuples
            start_time: Start time in seconds
            duration: Duration in seconds
            zoom_factor: How tight the crop is (0.5 = wide shot, 1.0 = tight close-up)

        Returns:
            ReframeResult with metadata
        """
        input_path = Path(input_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        info = self._get_video_info(input_path)
        src_width = info["width"]
        src_height = info["height"]
        fps = info["fps"]

        # Calculate crop dimensions
        target_aspect = self.output_width / self.output_height
        base_crop_width = int(src_height * target_aspect)
        # Apply zoom factor: smaller value = tighter crop (more zoom)
        crop_width = int(base_crop_width * zoom_factor)
        crop_width = min(crop_width, src_width)  # Don't exceed source width
        # Calculate crop_height to maintain aspect ratio (9:16)
        crop_height = int(crop_width / target_aspect)
        crop_height = min(crop_height, src_height)  # Don't exceed source height
        # Center the crop vertically
        crop_y = (src_height - crop_height) // 2

        console.print(f"[blue]🎬[/blue] Dynamic reframing with speaker tracking")
        console.print(f"[dim]   {len(crop_trajectory)} keyframes | {self.output_width}x{self.output_height}[/dim]")

        if len(crop_trajectory) < 2:
            # Fall back to center crop if not enough trajectory data
            console.print("[yellow]Not enough tracking data, using center crop[/yellow]")
            return self.reframe_center(input_path, output_path, start_time, duration)

        # Check if trajectory is constant (all same position) - use static crop
        x_positions = set(int(x) for _, x in crop_trajectory)
        if len(x_positions) == 1:
            # All keyframes at same position - use simple static offset crop
            center_x = list(x_positions)[0]
            crop_x = max(0, min(src_width - crop_width, center_x - crop_width // 2))
            console.print(f"[dim]   Using static crop at X={crop_x} (speaker at {center_x})[/dim]")
            
            filter_complex = f"crop={crop_width}:{crop_height}:{crop_x}:{crop_y},scale={self.output_width}:{self.output_height}"
            
            cmd = [
                "ffmpeg",
                "-y",
                "-ss", str(start_time),
                "-i", str(input_path),
            ]
            
            if duration:
                cmd.extend(["-t", str(duration)])
            
            cmd.extend([
                "-vf", filter_complex,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                str(output_path),
            ])
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task("Encoding with static crop...", total=None)
                result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                console.print(f"[red]FFmpeg error:[/red] {result.stderr[:300]}")
                raise RuntimeError("Video reframing failed")
            
            console.print(f"[green]✓[/green] Saved to {output_path}")
            
            return ReframeResult(
                input_path=input_path,
                output_path=output_path,
                original_resolution=(src_width, src_height),
                output_resolution=(self.output_width, self.output_height),
                duration=duration or info["duration"],
            )

        # Generate sendcmd script for dynamic cropping
        # FFmpeg sendcmd allows changing filter parameters over time
        sendcmd_lines = []
        
        # Detect if timestamps are absolute (>= start_time) or relative (starting near 0)
        # TalkNet returns relative timestamps when it processes extracted segments
        first_ts = float(crop_trajectory[0][0]) if crop_trajectory else 0
        timestamps_are_absolute = first_ts >= start_time - 1  # 1s tolerance
        
        for timestamp, center_x in crop_trajectory:
            # Calculate crop X position from center (ensure int for FFmpeg)
            crop_x = int(max(0, min(src_width - crop_width, int(center_x) - crop_width // 2)))
            
            # Convert to relative time for sendcmd
            ts = float(timestamp)
            rel_time = ts - start_time if timestamps_are_absolute else ts
            
            if rel_time >= 0:
                sendcmd_lines.append(f"{rel_time:.3f} crop x {crop_x};")

        # Write sendcmd file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("\n".join(sendcmd_lines))
            sendcmd_path = f.name

        try:
            # Build FFmpeg command with sendcmd
            # Use crop_height and crop_y to maintain aspect ratio
            # Calculate initial X with bounds checking
            initial_center = int(crop_trajectory[0][1])
            initial_x = int(max(0, min(src_width - crop_width, initial_center - crop_width // 2)))
            
            filter_complex = (
                f"sendcmd=f='{sendcmd_path}',"
                f"crop=w={crop_width}:h={crop_height}:x={initial_x}:y={crop_y},"
                f"scale={self.output_width}:{self.output_height}"
            )

            cmd = [
                "ffmpeg",
                "-y",
                "-ss", str(start_time),
                "-i", str(input_path),
            ]

            if duration:
                cmd.extend(["-t", str(duration)])

            cmd.extend([
                "-vf", filter_complex,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                str(output_path),
            ])

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task("Encoding with dynamic crop...", total=None)
                result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                console.print(f"[yellow]Dynamic crop failed, falling back to center crop[/yellow]")
                console.print(f"[dim]Error: {result.stderr[-1000:]}[/dim]")
                return self.reframe_center(input_path, output_path, start_time, duration)

        finally:
            # Clean up temp file
            Path(sendcmd_path).unlink(missing_ok=True)

        console.print(f"[green]✓[/green] Saved to {output_path}")

        return ReframeResult(
            input_path=input_path,
            output_path=output_path,
            original_resolution=(src_width, src_height),
            output_resolution=(self.output_width, self.output_height),
            duration=duration or info["duration"],
        )


def reframe_video(
    input_path: Path | str,
    output_path: Path | str,
    mode: Literal["center", "dynamic"] = "center",
    start_time: float = 0,
    duration: float | None = None,
    crop_trajectory: list[tuple[float, int]] | None = None,
) -> ReframeResult:
    """
    Convenience function to reframe a video.

    Args:
        input_path: Source video path
        output_path: Output video path
        mode: "center" for simple center crop, "dynamic" for speaker tracking
        start_time: Start time in seconds
        duration: Duration in seconds
        crop_trajectory: Required for dynamic mode - list of (timestamp, x) tuples

    Returns:
        ReframeResult with metadata
    """
    reframer = VideoReframer()

    if mode == "dynamic" and crop_trajectory:
        return reframer.reframe_dynamic(
            input_path, output_path, crop_trajectory, start_time, duration
        )
    else:
        return reframer.reframe_center(input_path, output_path, start_time, duration)
