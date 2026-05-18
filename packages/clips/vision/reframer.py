"""Split screen layout with dynamic face tracking - predefined layout approach."""

from pathlib import Path
import shutil
import subprocess

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from packages.core.utils import TempFileManager
from packages.core.video_utils import VideoCaptureContext

console = Console()


class VideoReframer:
    """
    Applies dynamic crop trajectories to video using FFmpeg.
    
    Takes a trajectory of (timestamp, center_x, center_y) keyframes and produces
    a cropped video that follows the trajectory smoothly via time-based expressions.
    """
    
    TRANSITION_SECS = 0  # Instant cut between speaker positions
    
    def __init__(self, output_width: int = 1080, output_height: int = 1920):
        self.output_width = output_width
        self.output_height = output_height
    
    @staticmethod
    def _simplify_trajectory(
        trajectory: list[tuple[float, int, int]],
        min_move_px: int = 40,
    ) -> list[tuple[float, int, int]]:
        """Reduce trajectory to key transition points.
        
        Collapses consecutive keyframes with similar positions into single
        points, keeping only moments where the crop actually needs to move.
        """
        if not trajectory:
            return []
        
        simplified = [trajectory[0]]
        for pt in trajectory[1:]:
            last = simplified[-1]
            dx = abs(pt[1] - last[1])
            dy = abs(pt[2] - last[2])
            if dx > min_move_px or dy > min_move_px:
                simplified.append(pt)
        
        # Always include the last point for proper duration coverage
        if len(trajectory) > 1 and simplified[-1] != trajectory[-1]:
            simplified.append(trajectory[-1])
        
        return simplified
    
    @staticmethod
    def _build_crop_expr(
        keypoints: list[tuple[float, int]],
        half_crop: int,
        src_dim: int,
        transition_secs: float = 0,
    ) -> str:
        """Build an FFmpeg time-based expression for crop X or Y.
        
        Generates nested if(lt(t,...), ...) expressions that instantly
        cut between keypoint positions, clamped to valid bounds.
        
        Args:
            keypoints: List of (timestamp, pixel_position) for one axis.
            half_crop: Half of crop width/height (for centering offset).
            src_dim: Source dimension (width or height) for clamping.
            transition_secs: Unused (kept for API compat). Always instant.
        """
        max_pos = src_dim - 2 * half_crop  # Maximum valid crop origin
        
        def clamp_pos(center: int) -> int:
            origin = center - half_crop
            return max(0, min(origin, max_pos))
        
        if len(keypoints) <= 1:
            pos = clamp_pos(keypoints[0][1]) if keypoints else 0
            return str(pos)
        
        # Build piecewise expression from right to left (innermost = last segment)
        # Instant cuts: if time < t_next, use pos_curr, else next segment
        
        expr = str(clamp_pos(keypoints[-1][1]))  # Fallback = last position
        
        for i in range(len(keypoints) - 2, -1, -1):
            t_next = keypoints[i + 1][0]
            pos_curr = clamp_pos(keypoints[i][1])
            expr = f"if(lt(t\\,{t_next:.2f})\\,{pos_curr}\\,{expr})"
        
        return expr
    
    def reframe_dynamic(
        self,
        video_path: Path | str,
        output_path: Path | str,
        trajectory: list[tuple[float, int]] | list[tuple[float, int, int]],
        start_time: float = 0,
        duration: float | None = None,
        zoom_factor: float = 1.0,
    ):
        """
        Crop video dynamically following face positions over time.
        
        Uses FFmpeg crop filter with TIME-BASED EXPRESSIONS that interpolate
        the crop position between trajectory keyframes, creating a smooth
        pan that follows the active speaker.
        """
        import cv2
        
        video_path = Path(video_path)
        output_path = Path(output_path)
        
        # Get source dimensions
        with VideoCaptureContext(str(video_path)) as cap:
            src_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            src_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        # Normalize trajectory to 3-tuples (timestamp, x, y)
        norm_traj: list[tuple[float, int, int]] = []
        for pt in trajectory:
            if len(pt) >= 3:
                norm_traj.append((pt[0], pt[1], pt[2]))
            else:
                norm_traj.append((pt[0], pt[1], src_height // 2))
        
        # Calculate crop dimensions preserving output aspect ratio
        target_aspect = self.output_width / self.output_height
        crop_height = src_height
        crop_width = int(crop_height * target_aspect)
        
        if crop_width > src_width:
            crop_width = src_width
            crop_height = int(crop_width / target_aspect)
        
        # Apply zoom factor (e.g. 0.85 = 85% of max = zooming IN)
        crop_width = int(crop_width * zoom_factor)
        crop_height = int(crop_height * zoom_factor)
        crop_width = min(crop_width, src_width)
        crop_height = min(crop_height, src_height)
        
        # Ensure even dimensions for libx264
        crop_width -= crop_width % 2
        crop_height -= crop_height % 2
        
        half_w = crop_width // 2
        half_h = crop_height // 2
        
        # Simplify trajectory to key transitions
        simplified = self._simplify_trajectory(norm_traj)
        
        console.print(
            f"[dim]   Dynamic crop: {crop_width}x{crop_height} from {src_width}x{src_height} "
            f"({len(simplified)} transition points from {len(trajectory)} keyframes)[/dim]"
        )
        
        # Debug: show crop positions per transition
        max_x_origin = src_width - crop_width
        max_y_origin = src_height - crop_height
        for pt in simplified:
            cx, cy = pt[1], pt[2]
            ox = max(0, min(cx - half_w, max_x_origin))
            oy = max(0, min(cy - half_h, max_y_origin))
            console.print(
                f"[dim]     t={pt[0]:.1f}s → face@({cx},{cy}) → crop_origin({ox},{oy})[/dim]"
            )
        
        # Build time-based FFmpeg expressions for X and Y
        x_keypoints = [(t, x) for t, x, y in simplified]
        y_keypoints = [(t, y) for t, x, y in simplified]
        
        x_expr = self._build_crop_expr(x_keypoints, half_w, src_width, self.TRANSITION_SECS)
        y_expr = self._build_crop_expr(y_keypoints, half_h, src_height, self.TRANSITION_SECS)
        
        vf = f"crop={crop_width}:{crop_height}:{x_expr}:{y_expr},scale={self.output_width}:{self.output_height}"
        
        cmd = [
            shutil.which("ffmpeg") or "ffmpeg", "-y",
            "-ss", str(start_time),
            "-i", str(video_path),
            "-t", str(duration) if duration else "",
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-an",
            str(output_path),
        ]
        # Remove empty args
        cmd = [c for c in cmd if c]
        
        from packages.core.process_registry import run_tracked
        result = run_tracked(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg crop failed: {result.stderr[-500:]}")
    
    def reframe_center(
        self,
        video_path: Path | str,
        output_path: Path | str,
        start_time: float = 0,
        duration: float | None = None,
    ):
        """Simple center crop to output dimensions."""
        # Use center trajectory
        trajectory = [(0, 0)]  # Will use source center by default
        self.reframe_dynamic(video_path, output_path, trajectory, start_time, duration)


def reframe_video(
    video_path: Path | str,
    output_path: Path | str,
    wide_height_ratio: float = 0.32,  # Wide shot takes ~32% of bottom (608/1920)
    start_time: float = 0,
    duration: float | None = None,
    pre_cut: bool = False,  # If True, video is already a cut clip - skip -ss/-t
    speaker_segments: list[dict] | None = None,
) -> Path:
    """
    Create split screen with:
    - TOP: Close-up with face tracking (adapts to fit available space)
    - BOTTOM: Wide shot 16:9 at the bottom edge
    
    The close-up fills the space above the wide shot exactly.
    
    Args:
        video_path: Path to source video (or pre-cut clip if pre_cut=True)
        output_path: Path for output video
        wide_height_ratio: Ratio of screen for wide shot
        start_time: Start time in seconds (ignored if pre_cut=True)
        duration: Duration in seconds (ignored if pre_cut=True)
        pre_cut: If True, video is already a cut clip - process from start without seeking
    """
    import cv2
    
    video_path = Path(video_path)
    output_path = Path(output_path)
    
    # Get source video info
    with VideoCaptureContext(str(video_path)) as cap:
        src_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        src_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_duration = total_frames / fps if fps > 0 else 0
    
    # FIX: If video is pre-cut, process from start (0) for the full duration
    if pre_cut:
        start_time = 0
        duration = total_duration
    elif duration is None:
        duration = total_duration - start_time
    
    # Target dimensions (9:16 vertical)
    target_width = 1080
    target_height = 1920
    
    # Wide shot: 16:9 at bottom
    wide_actual_height = int(target_width * 9 / 16)  # 607.5 -> 608
    if wide_actual_height % 2 != 0:
        wide_actual_height += 1  # Ensure even for libx264
    
    # Close-up: fills the space above the wide shot
    closeup_height = target_height - wide_actual_height  # 1920 - 608 = 1312
    
    console.print(f"[blue]📐[/blue] Creating split screen (predefined layout)")
    console.print(f"[dim]   Close-up: 1080x{closeup_height} (fits above wide)[/dim]")
    console.print(f"[dim]   Wide: 1080x{wide_actual_height} (16:9 at bottom)[/dim]")
    
    # -----------------------------------------------------------
    # STEP 1: Create close-up following the active speaker
    # Uses diarization (who speaks when) + face tracking (where they are)
    # -----------------------------------------------------------
    console.print(f"\n[blue]Step 1:[/blue] Creating close-up with speaker tracking...")
    
    from packages.clips.vision.face_tracker import FaceTracker
    
    trajectory = []
    detections = []
    
    try:
        tracker = FaceTracker(sample_fps=2.0)
        scan_start = 0 if pre_cut else start_time
        scan_end = duration if pre_cut else (start_time + duration)
        detections = tracker.detect_faces(video_path, scan_start, scan_end)
        
        # Fully automated active speaker trajectory via mouth motion mapping
        trajectory = tracker.get_speaker_trajectory(
            video_path=video_path,
            detections=detections,
            start_time=scan_start,
            end_time=scan_end,
            video_width=src_width,
            video_height=src_height,
            speaker_segments=speaker_segments,
        )
        console.print(f"[dim]   {len(trajectory)} keyframes (speaker tracking)[/dim]")
        
    except Exception as e:
        console.print(f"[yellow]⚠ Face tracking failed: {e}. Using center crop.[/yellow]")
    
    # Fallback: center crop if no trajectory generated
    if not trajectory:
        num_keyframes = max(1, int(duration))
        center_x = src_width // 2
        trajectory = [(i, center_x) for i in range(num_keyframes)]
        console.print(f"[dim]   {len(trajectory)} keyframes (center crop fallback)[/dim]")
    
    # Use TempFileManager for guaranteed cleanup (fixes orphaned temp files bug)
    with TempFileManager(prefix="split_") as tmp:
        # Create temporary close-up video with exact dimensions
        closeup_path = tmp.create('.mp4')
        
        # Compute dynamic zoom from detected face sizes (safe zone)
        zoom_factor = 0.7  # default fallback
        try:
            zoom_factor = FaceTracker.compute_safe_zoom(
                detections, src_height,
            )
        except Exception:
            pass  # use default
        
        # Close-up sized to fit exactly above wide shot
        reframer = VideoReframer(output_width=target_width, output_height=closeup_height)
        reframer.reframe_dynamic(video_path, closeup_path, trajectory, start_time, duration, zoom_factor=zoom_factor)
        
        # -----------------------------------------------------------
        # STEP 2: Create wide shot (16:9)
        # -----------------------------------------------------------
        console.print(f"\n[blue]Step 2:[/blue] Creating wide shot...")
        
        wide_path = tmp.create('.mp4')
        
        cmd_wide = [
            shutil.which("ffmpeg") or "ffmpeg", "-y",
            "-ss", str(start_time),
            "-i", str(video_path),
            "-t", str(duration),
            "-vf", f"scale={target_width}:{wide_actual_height}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-movflags", "+faststart",
            "-an",
            str(wide_path)
        ]
        
        from packages.core.process_registry import run_tracked
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as p:
            p.add_task("Encoding wide shot...", total=None)
            wide_result = run_tracked(cmd_wide, capture_output=True, text=True)
        
        if wide_result.returncode != 0:
            console.print(f"[red]Wide shot encoding failed[/red]")
            raise RuntimeError("Wide shot encoding failed")
        
        # -----------------------------------------------------------
        # STEP 3: Stack close-up + wide vertically
        # -----------------------------------------------------------
        console.print(f"\n[blue]Step 3:[/blue] Stacking videos...")
        
        cmd_stack = [
            shutil.which("ffmpeg") or "ffmpeg", "-y",
            "-i", str(closeup_path),
            "-i", str(wide_path),
        ]
        
        # FIX: Define offsets for the final stacking command
        # If pre_cut=True, the input video IS the clip, so offset is 0
        stack_start = 0 if pre_cut else start_time
        
        cmd_stack.extend([
            "-ss", str(stack_start),
            "-i", str(video_path),
            "-t", str(duration),
            # Stack videos and compress + normalize audio
            # compand: compressor to reduce dynamic range (makes quiet parts louder, loud parts quieter)
            # loudnorm: then normalize to EBU R128 standard
            "-filter_complex", 
            "[0:v][1:v]vstack=inputs=2[v];"
            "[2:a]compand=attacks=0.05:decays=0.3:points=-80/-80|-45/-25|-20/-15|-5/-5|0/-3:gain=3,loudnorm=I=-16:TP=-1.5:LRA=7[a]",
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            str(output_path)
        ])
        
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as p:
            p.add_task("Stacking videos...", total=None)
            result = run_tracked(cmd_stack, capture_output=True, text=True)
        
        # TempFileManager handles cleanup automatically - no need for manual unlink
        
        if result.returncode != 0:
            console.print(f"[red]Error:[/red] {result.stderr[-500:]}")
            raise RuntimeError("FFmpeg stacking failed")
        
        console.print(f"\n[green]✓[/green] Saved to {output_path}")
        return output_path

