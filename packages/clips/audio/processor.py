"""Audio processing and normalization utilities."""

import subprocess
from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()

def process_video_with_audio_normalization(
    input_video: Path | str,
    output_video: Optional[Path | str] = None,
) -> Path:
    """
    Process video with basic audio normalization using FFmpeg.

    Args:
        input_video: Path to input video
        output_video: Path to output video (optional, creates temp if not provided)

    Returns:
        Path to processed video
    """
    input_video = Path(input_video)

    if output_video is None:
        output_video = input_video.parent / f"{input_video.stem}_normalized{input_video.suffix}"
    output_video = Path(output_video)

    console.print("[blue]🔊 Applying basic audio normalization...[/blue]")
    # Simple normalization with compression and loudnorm to -16 LUFS
    cmd = [
        "ffmpeg", "-y", "-i", str(input_video),
        "-af", "compand=attacks=0.05:decays=0.3:points=-80/-80|-45/-25|-20/-15|-5/-5|0/-3:gain=3,loudnorm=I=-16:TP=-1.5:LRA=7",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        str(output_video)
    ]

    from packages.core.process_registry import run_tracked
    try:
        run_tracked(cmd, capture_output=True, check=True)
        console.print("[green]✓[/green] Audio normalized")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error normalizing audio: {e.stderr.decode() if e.stderr else str(e)}[/red]")
        # Fallback to direct copy if normalization fails
        cmd_fallback = [
            "ffmpeg", "-y", "-i", str(input_video),
            "-c:v", "copy", "-c:a", "copy",
            str(output_video)
        ]
        run_tracked(cmd_fallback, capture_output=True, check=True)
        console.print("[yellow]⚠[/yellow] Fallback to original audio due to error")

    return output_video
