"""Split screen layout with dynamic face tracking - predefined layout approach."""

from pathlib import Path
import subprocess

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.utils import TempFileManager

console = Console()


def create_split_screen_tracked(
    video_path: Path | str,
    output_path: Path | str,
    wide_height_ratio: float = 0.32,  # Wide shot takes ~32% of bottom (608/1920)
    start_time: float = 0,
    duration: float | None = None,
    use_lip_sync: bool = False,  # Use lip movement detection (more accurate, slower)
    use_hybrid: bool = True,  # Use hybrid: diarization timing + lip sync calibration (recommended)
    use_talknet: bool = False,  # Use TalkNet audio-visual active speaker detection
    use_ai_audio: bool = False,  # Use Demucs AI for audio (disabled by default for podcasts)
    pre_cut: bool = False,  # NEW: If True, video is already a cut clip - skip -ss/-t
) -> Path:
    """
    Create split screen with:
    - TOP: Close-up with face tracking (adapts to fit available space)
    - BOTTOM: Wide shot 16:9 at the bottom edge
    
    The close-up fills the space above the wide shot exactly.
    
    Speaker Detection Modes (priority order):
    - use_talknet: TalkNet audio-visual detection (best accuracy, slowest)
    - use_hybrid: Diarization + lip sync calibration (good accuracy, faster)
    - face-only: Basic face tracking (fallback)
    
    Args:
        video_path: Path to source video (or pre-cut clip if pre_cut=True)
        output_path: Path for output video
        wide_height_ratio: Ratio of screen for wide shot
        start_time: Start time in seconds (ignored if pre_cut=True)
        duration: Duration in seconds (ignored if pre_cut=True)
        use_lip_sync: If True, use pure lip movement detection (jittery)
        use_hybrid: If True, use hybrid diarization + lip sync (recommended)
        use_talknet: If True, use TalkNet audio-visual detection (most accurate)
        pre_cut: If True, video is already a cut clip - process from start without seeking
    """
    from src.vision.reframer import VideoReframer
    from src.vision.face_tracker import FaceTracker
    import cv2
    
    video_path = Path(video_path)
    output_path = Path(output_path)
    
    # Get source video info
    cap = cv2.VideoCapture(str(video_path))
    src_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_duration = total_frames / fps if fps > 0 else 0
    cap.release()
    
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
    # STEP 1: Create close-up with speaker tracking
    # -----------------------------------------------------------
    console.print(f"\n[blue]Step 1:[/blue] Creating speaker-aware close-up...")
    
    end_time = start_time + duration if duration else None
    trajectory = None
    
    # Priority: TalkNet > Hybrid > Face-only
    if use_talknet:
        # TalkNet: Audio-visual active speaker detection (best accuracy)
        console.print(f"[cyan]   Using TALKNET detection (audio-visual sync)[/cyan]")
        try:
            from src.vision.talknet_detector import detect_with_talknet
            
            trajectory = detect_with_talknet(
                str(video_path), start_time, duration,
                target_aspect=target_width / closeup_height
            )
            console.print(f"[dim]   {len(trajectory)} keyframes (talknet)[/dim]")
        except Exception as e:
            console.print(f"[yellow]   TalkNet failed: {e}, falling back to hybrid[/yellow]")
            trajectory = None
    
    if trajectory is None and use_hybrid:
        # HYBRID: Diarization timing + lip sync calibration (good accuracy)
        console.print(f"[cyan]   Using HYBRID detection (diarization + lip sync calibration)[/cyan]")
        from src.vision.hybrid_speaker_detector import detect_and_track_hybrid
        
        trajectory = detect_and_track_hybrid(
            video_path, start_time, duration,
            target_aspect=target_width / closeup_height
        )
        console.print(f"[dim]   {len(trajectory)} keyframes (hybrid)[/dim]")
    
    if trajectory is None or len(trajectory) == 0:
        # Fallback: face detection only (no speaker awareness)
        console.print(f"[dim]   Using face-only tracking (no speaker detection)[/dim]")
        tracker = FaceTracker(sample_fps=3.0)
        detections = tracker.detect_faces(video_path, start_time=start_time, end_time=end_time)
        
        trajectory = tracker.get_smooth_crop_trajectory(
            detections, src_width, src_height, 
            target_aspect=target_width / closeup_height
        )
        console.print(f"[dim]   {len(trajectory)} keyframes (face tracking)[/dim]")
    
    # Use TempFileManager for guaranteed cleanup (fixes orphaned temp files bug)
    with TempFileManager(prefix="split_") as tmp:
        # Create temporary close-up video with exact dimensions
        closeup_path = tmp.create('.mp4')
        
        # Close-up sized to fit exactly above wide shot
        # zoom_factor=0.85 gives medium shot framing (head + shoulders)
        reframer = VideoReframer(output_width=target_width, output_height=closeup_height)
        reframer.reframe_dynamic(video_path, closeup_path, trajectory, start_time, duration, zoom_factor=0.85)
        
        # -----------------------------------------------------------
        # STEP 2: Create wide shot (16:9)
        # -----------------------------------------------------------
        console.print(f"\n[blue]Step 2:[/blue] Creating wide shot...")
        
        wide_path = tmp.create('.mp4')
        
        cmd_wide = [
            "/usr/local/bin/ffmpeg", "-y",
            "-ss", str(start_time),
            "-i", str(video_path),
            "-t", str(duration),
            "-vf", f"scale={target_width}:{wide_actual_height}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-movflags", "+faststart",
            "-an",
            str(wide_path)
        ]
        
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as p:
            p.add_task("Encoding wide shot...", total=None)
            wide_result = subprocess.run(cmd_wide, capture_output=True, text=True)
        
        if wide_result.returncode != 0:
            console.print(f"[red]Wide shot encoding failed[/red]")
            raise RuntimeError("Wide shot encoding failed")
        
        # -----------------------------------------------------------
        # STEP 3: Stack close-up + wide vertically
        # -----------------------------------------------------------
        console.print(f"\n[blue]Step 3:[/blue] Stacking videos...")
        
        cmd_stack = [
            "/usr/local/bin/ffmpeg", "-y",
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
            result = subprocess.run(cmd_stack, capture_output=True, text=True)
        
        # TempFileManager handles cleanup automatically - no need for manual unlink
        
        if result.returncode != 0:
            console.print(f"[red]Error:[/red] {result.stderr[-500:]}")
            raise RuntimeError("FFmpeg stacking failed")
        
        # Step 4: Apply Demucs AI audio normalization (optional but recommended)
        if use_ai_audio:
            console.print(f"\n[blue]Step 4:[/blue] Applying Demucs AI audio processing...")
            try:
                from src.audio.processor import process_video_with_audio_normalization
                
                # Create temp path for pre-AI video
                temp_video = output_path.parent / f"{output_path.stem}_temp{output_path.suffix}"
                output_path.rename(temp_video)
                
                # Apply Demucs + Voice EQ
                process_video_with_audio_normalization(
                    input_video=temp_video,
                    output_video=output_path,
                    use_ai=True,
                )
                
                # Cleanup temp
                temp_video.unlink(missing_ok=True)
                
            except Exception as e:
                console.print(f"[yellow]Warning: AI audio failed ({e}), using basic normalization[/yellow]")
                # Already has basic normalization from FFmpeg filter
        
        console.print(f"\n[green]✓[/green] Saved to {output_path}")
        return output_path

