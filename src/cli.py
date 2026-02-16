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
    upload: Annotated[bool, typer.Option("--upload", help="Upload transcript to Supabase after generation")] = False,
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

    # Optional: Upload to Supabase
    if upload:
        from src.sources.supabase_transcripts import upload_transcript
        # Infer ID from filename (e.g. EP001_...)
        ep_id = video.stem.split(" ")[0] if video.name.startswith("EP") else video.stem
        upload_transcript(transcript, ep_id)

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
    📻 List available episodes from Supabase

    Example:
        celia episodes --limit 10
    """
    try:
        from src.sources import list_episodes
        list_episodes(limit=limit)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command(name="from-supabase")
def from_supabase(
    episode_id: Annotated[str, typer.Argument(help="Episode ID or number")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Output directory")] = Path("./output"),
    top_n: Annotated[int, typer.Option("--top", "-n", help="Number of clips")] = 5,
    video: Annotated[Optional[Path], typer.Option("--video", "-v", help="Video file for clip extraction")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Curate only, don't extract")] = False,
    teasers: Annotated[bool, typer.Option("--teasers", help="Generate adelantos (teaser clips)")] = False,
    intro: Annotated[bool, typer.Option("--intro", help="Generate intro script (guión)")] = False,
    all_content: Annotated[bool, typer.Option("--all", help="Generate clips + teasers + intro")] = False,
    guest_name: Annotated[str, typer.Option("--guest", "-g", help="Guest name for intro script")] = "",
):
    """
    🚀 Curate clips from Celia Podcast episode in Supabase

    Example:
        celia from-supabase EP001 --top 5
        celia from-supabase EP001 --all --guest "Juan Pérez"
        celia from-supabase EP001 --video ep108.mp4 --output ./clips
    """
    import json
    from src.sources import get_transcript
    from src.curation import ClipCurator, ClipExtractor

    console.print("[bold blue]🎬 Celia Clips[/bold blue] - Supabase Mode\n")

    # Get transcript from Supabase
    console.print(f"[blue]📡[/blue] Fetching transcript for: {episode_id}")
    transcript = get_transcript(episode_id)

    if not transcript:
        console.print(f"[red]Error:[/red] Could not find transcript for {episode_id}")
        raise typer.Exit(1)

    console.print(f"[green]✓[/green] Loaded transcript: {len(transcript.segments)} segments")

    # Save transcript locally
    output.mkdir(parents=True, exist_ok=True)
    transcript_path = output / f"{episode_id}_transcript.json"
    transcript.save(transcript_path)

    # Enable all content if --all flag
    if all_content:
        teasers = True
        intro = True

    # ============================================
    # STANDARD CLIPS (existing workflow)
    # ============================================
    curator = ClipCurator()
    clips = curator.curate(transcript, top_n=top_n)

    if not clips:
        console.print("[yellow]No clips found.[/yellow]")
    else:
        # Save curation
        curation_path = output / f"{episode_id}_curation.json"
        with open(curation_path, "w") as f:
            json.dump([c.to_dict() for c in clips], f, indent=2, ensure_ascii=False)
        console.print(f"[green]✓[/green] Curation saved to {curation_path}")

    # ============================================
    # TEASERS + INTRO (new features)
    # ============================================
    if teasers or intro:
        from src.curation.teaser_generator import TeaserIntroGenerator
        
        generator = TeaserIntroGenerator()
        extras = generator.generate(
            transcript=transcript,
            episode_id=episode_id,
            guest_name=guest_name,
            generate_teasers=teasers,
            generate_intro=intro,
        )
        
        # Save teasers
        if teasers and extras.get("teasers"):
            teaser_path = output / f"{episode_id}_teasers.json"
            with open(teaser_path, "w") as f:
                json.dump(extras["teasers"], f, indent=2, ensure_ascii=False)
            console.print(f"[green]✓[/green] Teasers saved to {teaser_path}")
        
        # Save intro script
        if intro and extras.get("intro_script"):
            intro_path = output / f"{episode_id}_intro_script.json"
            with open(intro_path, "w") as f:
                json.dump(extras["intro_script"], f, indent=2, ensure_ascii=False)
            console.print(f"[green]✓[/green] Intro script saved to {intro_path}")
            
            # Also save as readable text
            intro_text_path = output / f"{episode_id}_intro_guion.txt"
            intro_text_path.write_text(extras["intro_script"]["text"])
            console.print(f"[green]✓[/green] Guión readable: {intro_text_path}")

    # ============================================
    # EXTRACT CLIPS (if video provided)
    # ============================================
    if video and not dry_run and clips:
        if not video.exists():
            console.print(f"[red]Error:[/red] Video not found: {video}")
            raise typer.Exit(1)

        extractor = ClipExtractor(output_dir=output / "clips")
        extracted = extractor.extract_all(video, clips)
        console.print(f"\n[bold green]✅ Done![/bold green] Extracted {len(extracted)} clips")
    elif dry_run:
        console.print("\n[dim]--dry-run specified, skipping extraction[/dim]")
    elif not video:
        console.print("\n[dim]No video provided. Use --video to extract clips.[/dim]")


if __name__ == "__main__":
    app()


@app.command(name="upload-transcript")
def upload_transcript_cmd(
    target: Annotated[Path, typer.Argument(help="Transcript JSON file or Episode Folder")],
    episode_id: Annotated[Optional[str], typer.Option("--id", help="Override Episode ID")] = None,
    title: Annotated[Optional[str], typer.Option("--title", help="Episode Title")] = None,
    guest: Annotated[Optional[str], typer.Option("--guest", help="Guest Name")] = None,
):
    """
    📤 Upload a local transcript to Supabase.
    
    Target can be:
    1. A transcript.json file
    2. An episode folder (containing transcript.json)
    
    Example:
        celia upload-transcript ./episodes/EP001
        celia upload-transcript transcript.json --id EP001
    """
    from src.asr.transcriber import Transcript
    from src.sources.supabase_transcripts import upload_transcript
    
    # Resolve target
    transcript_path = target
    if target.is_dir():
        # Try metadata first to find actual transcript
        transcript_path = target / "transcript.json"
        
        # Try to guess episode ID from folder if not provided
        if not episode_id and target.name.startswith("EP"):
            episode_id = target.name.split(" ")[0] # "EP001 - Title" -> "EP001"
            
    if not transcript_path.exists():
        console.print(f"[red]Error:[/red] Transcript not found at {transcript_path}")
        raise typer.Exit(1)
        
    # Load transcript
    try:
        transcript = Transcript.load(transcript_path)
    except Exception as e:
        console.print(f"[red]Error:[/red] Invalid transcript JSON: {e}")
        raise typer.Exit(1)
        
    # Determine Episode ID
    if not episode_id:
        # Try to infer from filename if it looks like EP###_transcript.json
        if transcript_path.name.startswith("EP") and "_" in transcript_path.name:
            episode_id = transcript_path.name.split("_")[0]
        else:
            console.print("[red]Error:[/red] Could not infer Episode ID. Please use --id EP###")
            raise typer.Exit(1)
            
    # Perform upload
    success = upload_transcript(
        transcript=transcript,
        episode_id=episode_id,
        episode_title=title,
        guest_name=guest
    )
    
    if not success:
        raise typer.Exit(1)

