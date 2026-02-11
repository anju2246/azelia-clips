"""Command-line interface for Celia Clips."""

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

app = typer.Typer(
    name="celia",
    help="🎬 Celia Clips: Turn podcasts into viral short-form clips",
    add_completion=False,
)
console = Console()


@app.command()
def process(
    video: Annotated[Path, typer.Argument(help="Path to source video file")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Output directory")] = Path("./output"),
    top_n: Annotated[int, typer.Option("--top", "-n", help="Number of clips to extract")] = 5,
    min_duration: Annotated[int, typer.Option("--min", help="Minimum clip duration (seconds)")] = 15,
    max_duration: Annotated[int, typer.Option("--max", help="Maximum clip duration (seconds)")] = 90,
    language: Annotated[str, typer.Option("--lang", "-l", help="Audio language code")] = "es",
    skip_transcribe: Annotated[bool, typer.Option("--skip-transcribe", help="Use existing transcript")] = False,
    transcript_path: Annotated[Optional[Path], typer.Option("--transcript", "-t", help="Path to existing transcript JSON")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Curate only, don't extract clips")] = False,
):
    """
    🚀 Full pipeline: Transcribe → Curate → Extract clips

    Example:
        celia process podcast.mp4 --top 5 --output ./clips
    """
    from src.asr.transcriber import Transcript
    from src.curation import ClipCurator, ClipExtractor

    console.print("[bold blue]🎬 Celia Clips[/bold blue] - AI Video Repurposing\n")

    # Step 1: Get transcript
    if transcript_path and transcript_path.exists():
        console.print(f"[blue]📄[/blue] Loading existing transcript: {transcript_path}")
        transcript = Transcript.load(transcript_path)
    elif skip_transcribe:
        # Look for transcript in output dir
        default_transcript = output / f"{video.stem}_transcript.json"
        if default_transcript.exists():
            transcript = Transcript.load(default_transcript)
        else:
            console.print("[red]Error:[/red] No transcript found. Run without --skip-transcribe first.")
            raise typer.Exit(1)
    else:
        # Transcribe
        try:
            from src.asr.transcriber import transcribe_file
            transcript_output = output / f"{video.stem}_transcript.json"
            transcript = transcribe_file(video, output_path=transcript_output, language=language)
        except ImportError:
            console.print("[red]Error:[/red] WhisperX not installed. Run: pip install -e '.[asr]'")
            raise typer.Exit(1)

    # Step 2: Curate clips
    curator = ClipCurator()
    clips = curator.curate(
        transcript,
        top_n=top_n,
        min_duration=min_duration,
        max_duration=max_duration,
    )

    if not clips:
        console.print("[yellow]No clips found. Try adjusting duration parameters.[/yellow]")
        raise typer.Exit(0)

    # Save curation results
    import json
    curation_path = output / f"{video.stem}_curation.json"
    with open(curation_path, "w") as f:
        json.dump([c.to_dict() for c in clips], f, indent=2, ensure_ascii=False)
    console.print(f"[green]✓[/green] Curation saved to {curation_path}")

    if dry_run:
        console.print("\n[dim]--dry-run specified, skipping clip extraction[/dim]")
        raise typer.Exit(0)

    # Step 3: Extract clips
    extractor = ClipExtractor(output_dir=output / "clips")
    extracted = extractor.extract_all(video, clips)

    console.print(f"\n[bold green]✅ Done![/bold green] Extracted {len(extracted)} clips to {output / 'clips'}")


@app.command()
def transcribe(
    video: Annotated[Path, typer.Argument(help="Path to video/audio file")],
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Output JSON path")] = None,
    language: Annotated[str, typer.Option("--lang", "-l", help="Language code")] = "es",
):
    """
    🎤 Transcribe audio with word-level timestamps

    Example:
        celia transcribe podcast.mp4 --lang es
    """
    try:
        from src.asr.transcriber import transcribe_file
    except ImportError:
        console.print("[red]Error:[/red] WhisperX not installed. Run: pip install -e '.[asr]'")
        raise typer.Exit(1)

    if output is None:
        output = video.with_suffix(".json")

    transcribe_file(video, output_path=output, language=language)
    console.print(f"[green]✓[/green] Transcript saved to {output}")


@app.command()
def curate(
    transcript: Annotated[Path, typer.Argument(help="Path to transcript JSON")],
    top_n: Annotated[int, typer.Option("--top", "-n", help="Number of clips")] = 10,
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Output JSON path")] = None,
):
    """
    🧠 Curate viral clips from existing transcript

    Example:
        celia curate transcript.json --top 5
    """
    import json
    from src.asr.transcriber import Transcript
    from src.curation import ClipCurator

    if not transcript.exists():
        console.print(f"[red]Error:[/red] Transcript not found: {transcript}")
        raise typer.Exit(1)

    trans = Transcript.load(transcript)
    curator = ClipCurator()
    clips = curator.curate(trans, top_n=top_n)

    if output:
        with open(output, "w") as f:
            json.dump([c.to_dict() for c in clips], f, indent=2, ensure_ascii=False)
        console.print(f"[green]✓[/green] Curation saved to {output}")


@app.command()
def subtitles(
    transcript: Annotated[Path, typer.Argument(help="Path to transcript JSON")],
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Output .ass path")] = None,
    style: Annotated[str, typer.Option("--style", "-s", help="Style preset")] = "podcast",
):
    """
    📝 Generate styled subtitles from transcript

    Styles: hormozi, mrbeast, minimal, podcast

    Example:
        celia subtitles transcript.json --style hormozi
    """
    from src.subtitles.generator import generate_subtitles

    if not transcript.exists():
        console.print(f"[red]Error:[/red] Transcript not found: {transcript}")
        raise typer.Exit(1)

    if output is None:
        output = transcript.with_suffix(".ass")

    generate_subtitles(transcript, output, style=style)
    console.print(f"[green]✓[/green] Subtitles saved to {output}")


@app.command()
def reframe(
    video: Annotated[Path, typer.Argument(help="Path to video file")],
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Output path")] = None,
    mode: Annotated[str, typer.Option("--mode", "-m", help="Mode: center or face")] = "face",
    start: Annotated[float, typer.Option("--start", "-s", help="Start time in seconds")] = 0,
    duration: Annotated[Optional[float], typer.Option("--duration", "-d", help="Duration in seconds")] = None,
):
    """
    📐 Reframe horizontal video to vertical (9:16)

    Modes:
    - face: Face detection with smooth tracking (recommended)
    - center: Simple center crop (fastest)

    Example:
        celia reframe video.mp4 --mode face
        celia reframe video.mp4 --mode center --output vertical.mp4
    """
    if not video.exists():
        console.print(f"[red]Error:[/red] Video not found: {video}")
        raise typer.Exit(1)

    if output is None:
        output = video.with_stem(f"{video.stem}_vertical")

    if mode == "face":
        from src.vision import FaceTracker, VideoReframer
        import cv2

        console.print("[bold blue]🎬 Celia Clips[/bold blue] - Face Tracking Reframe\n")

        # Get video dimensions
        cap = cv2.VideoCapture(str(video))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        # Track faces with smooth trajectory
        tracker = FaceTracker()
        detections = tracker.detect_faces(video, start_time=start, end_time=start + duration if duration else None)
        trajectory = tracker.get_smooth_crop_trajectory(detections, width, height)

        # Reframe with face tracking
        reframer = VideoReframer()
        reframer.reframe_dynamic(video, output, trajectory, start, duration)

    else:
        from src.vision import VideoReframer
        console.print("[bold blue]🎬 Celia Clips[/bold blue] - Center Reframe\n")
        reframer = VideoReframer()
        reframer.reframe_center(video, output, start, duration)


@app.command()
def version():
    """Show version information."""
    from src import __version__
    console.print(f"[bold]Celia Clips[/bold] v{__version__}")


@app.command()
def episodes(
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max episodes to show")] = 20,
):
    """

    Example:
        celia episodes --limit 10
    """
    try:
        list_episodes(limit=limit)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()

