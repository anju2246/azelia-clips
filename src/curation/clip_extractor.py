"""Extract video clips based on curated timestamps."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn

from src.curation.curator_v2 import CuratedClipV2

console = Console()

# Type alias for backwards compatibility
CuratedClip = CuratedClipV2


@dataclass
class ExtractedClip:
    """An extracted video clip with metadata."""
    path: Path
    curated_clip: Union[CuratedClipV2, "CuratedClip"]
    
    @property
    def filename(self) -> str:
        return self.path.name


class ClipExtractor:
    """Extracts video clips using FFmpeg."""

    def __init__(self, output_dir: Path | str = "./output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_filename(self, title: str) -> str:
        """Convert title to safe filename."""
        # Remove special characters, keep alphanumeric and spaces
        safe = "".join(c if c.isalnum() or c in " -_" else "" for c in title)
        # Replace spaces with underscores and limit length
        return safe.strip().replace(" ", "_")[:50]

    def _get_clip_path(self, clip: CuratedClip, index: int, extension: str = "mp4") -> Path:
        """Generate output path for a clip."""
        safe_title = self._sanitize_filename(clip.title)
        score = clip.virality_score.total
        filename = f"{index:02d}_{score}pts_{safe_title}.{extension}"
        return self.output_dir / filename

    def extract_clip(
        self,
        source_video: Path | str,
        clip: CuratedClip,
        index: int = 1,
        padding: float = 0.5,
    ) -> ExtractedClip:
        """
        Extract a single clip from source video.

        Args:
            source_video: Path to source video file
            clip: CuratedClip with timestamps
            index: Clip number for filename
            padding: Extra seconds to add before/after

        Returns:
            ExtractedClip with path and metadata
        """
        source_video = Path(source_video)
        if not source_video.exists():
            raise FileNotFoundError(f"Source video not found: {source_video}")

        output_path = self._get_clip_path(clip, index)
        
        # Calculate times with padding
        start = max(0, clip.start_time - padding)
        duration = clip.duration + (2 * padding)

        # FFmpeg command for precise cutting
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite
            "-ss", str(start),  # Seek before input (fast)
            "-i", str(source_video),
            "-t", str(duration),
            "-c:v", "libx264",  # Re-encode for precise cuts
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",  # Web-optimized
            str(output_path),
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            console.print(f"[red]FFmpeg error:[/red] {result.stderr[:200]}")
            raise RuntimeError(f"Failed to extract clip: {clip.title}")

        return ExtractedClip(path=output_path, curated_clip=clip)

    def extract_all(
        self,
        source_video: Path | str,
        clips: list[CuratedClip],
        padding: float = 0.5,
    ) -> list[ExtractedClip]:
        """
        Extract all curated clips from source video.

        Args:
            source_video: Path to source video file
            clips: List of CuratedClip objects
            padding: Extra seconds before/after each clip

        Returns:
            List of ExtractedClip objects
        """
        source_video = Path(source_video)
        console.print(f"[blue]✂️[/blue] Extracting {len(clips)} clips from {source_video.name}")

        extracted = []

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Extracting clips...", total=len(clips))

            for i, clip in enumerate(clips, 1):
                try:
                    result = self.extract_clip(source_video, clip, index=i, padding=padding)
                    extracted.append(result)
                    console.print(f"  [green]✓[/green] {result.filename}")
                except Exception as e:
                    console.print(f"  [red]✗[/red] Clip {i}: {e}")
                
                progress.update(task, advance=1)

        console.print(f"\n[green]✓[/green] Extracted {len(extracted)}/{len(clips)} clips to {self.output_dir}")
        return extracted


def extract_clips(
    source_video: Path | str,
    clips: list[CuratedClip],
    output_dir: Path | str = "./output",
) -> list[ExtractedClip]:
    """
    Convenience function to extract clips.

    Args:
        source_video: Path to source video
        clips: List of curated clips
        output_dir: Output directory

    Returns:
        List of extracted clips
    """
    extractor = ClipExtractor(output_dir=output_dir)
    return extractor.extract_all(source_video, clips)
