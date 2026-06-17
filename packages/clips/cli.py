"""Command-line interface for Azelia Clips."""

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

app = typer.Typer(
    name="azelia",
    help="🎬 Azelia Clips: Turn podcasts into viral short-form clips",
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
        azelia process podcast.mp4 --top 5 --output ./clips
    """
    from packages.clips.transcription.transcriber import Transcript
    from packages.clips.curation import ClipCurator, ClipExtractor

    console.print("[bold blue]🎬 Azelia Clips[/bold blue] - AI Video Repurposing\n")

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
            from packages.clips.transcription.transcriber import transcribe_file
            transcript_output = output / f"{video.stem}_transcript.json"
            transcript = transcribe_file(video, output_path=transcript_output, language=language)
        except ImportError:
            console.print("[red]Error:[/red] WhisperX not installed. Run: pip install -e '.[asr]'")
            raise typer.Exit(1)

    # Optional: upload to USER's own Supabase project (not Azelia's)
    if upload:
        from packages.core.config import settings as _s
        if not (_s.transcript_supabase_url and _s.transcript_supabase_key):
            console.print("[yellow]--upload requires TRANSCRIPT_SUPABASE_URL/KEY in your settings. Skipped.[/yellow]")
        else:
            from server.sources.supabase_transcripts import upload_transcript
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
        azelia transcribe podcast.mp4 --lang es
    """
    try:
        from packages.clips.transcription.transcriber import transcribe_file
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
        azelia curate transcript.json --top 5
    """
    import json
    from packages.clips.transcription.transcriber import Transcript
    from packages.clips.curation import ClipCurator

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
        azelia subtitles transcript.json --style hormozi
    """
    from packages.clips.subtitles.generator import generate_subtitles

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
        azelia reframe video.mp4 --mode face
        azelia reframe video.mp4 --mode center --output vertical.mp4
    """
    if not video.exists():
        console.print(f"[red]Error:[/red] Video not found: {video}")
        raise typer.Exit(1)

    if output is None:
        output = video.with_stem(f"{video.stem}_vertical")

    if mode == "face":
        from packages.clips.vision import FaceTracker
        import cv2

        console.print("[bold blue]🎬 Azelia Clips[/bold blue] - Face Tracking Reframe\n")
        # TODO (Paso 5): Wire up biometric face tracking
        console.print("[yellow]⚠ Face tracking is being migrated to biometric system.[/yellow]")
        console.print("[dim]   Using center crop as temporary fallback.[/dim]")
        mode = "center"  # Fall through to center mode below

    if mode == "center":
        from packages.clips.vision import VideoReframer
        console.print("[bold blue]🎬 Azelia Clips[/bold blue] - Center Reframe\n")
        reframer = VideoReframer()
        reframer.reframe_center(video, output, start, duration)


@app.command()
def version():
    """Show version information."""
    from packages.clips import __version__
    console.print(f"[bold]Azelia Clips[/bold] v{__version__}")


@app.command()
def episodes(
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max episodes to show")] = 20,
):
    """
    📻 List available episodes from Supabase

    Example:
        azelia episodes --limit 10
    """
    try:
        from server.sources import list_episodes
        list_episodes(limit=limit)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def start(
    port: Annotated[int, typer.Option("--port", "-p", help="Server port")] = 8000,
    host: Annotated[str, typer.Option("--host", help="Server host")] = "0.0.0.0",
    no_build: Annotated[bool, typer.Option("--no-build", help="Skip building Astro frontend before starting")] = False,
    dev: Annotated[bool, typer.Option("--dev", help="Run in dev mode (Astro dev server + FastAPI with reload)")] = False,
):
    """
    🚀 Start the Azelia Clips server

    Production:
        azelia start                # Build frontend + start server (Default)
        azelia start --no-build     # Start server only (skips build, uses existing)

    Development:
        azelia start --dev          # Start with hot-reload (Astro + FastAPI)
    """
    from rich.panel import Panel
    from rich.text import Text
    import subprocess
    import webbrowser
    import threading
    import time
    import sys
    import os

    # ── Explicitly load .env so pydantic-settings picks up all keys ───────
    project_root = Path(__file__).resolve().parent.parent.parent

    # ── Explicitly load .env so pydantic-settings picks up all keys ───────
    try:
        from dotenv import load_dotenv
        env_path = project_root / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=True)
            # Reload settings singleton with fresh env vars
            from packages.core.config import Settings
            import packages.core.config as config_module
            config_module.settings = Settings()
    except ImportError:
        pass  # dotenv not installed; pydantic-settings will handle it
    
    AZELIA_ART = """  █████╗ ███████╗███████╗██╗     ██╗ █████╗      ██████╗██╗     ██╗██████╗ ███████╗
 ██╔══██╗╚══███╔╝██╔════╝██║     ██║██╔══██╗    ██╔════╝██║     ██║██╔══██╗██╔════╝
 ███████║  ███╔╝ █████╗  ██║     ██║███████║    ██║     ██║     ██║██████╔╝███████╗
 ██╔══██║ ███╔╝  ██╔══╝  ██║     ██║██╔══██║    ██║     ██║     ██║██╔═══╝ ╚════██║
 ██║  ██║███████╗███████╗███████╗██║██║  ██║    ╚██████╗███████╗██║██║     ███████║
 ╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝╚═╝╚═╝  ╚═╝     ╚═════╝╚══════╝╚═╝╚═╝     ╚══════╝"""
    
    brand_color = "#3e8e63"
    art_text = Text(AZELIA_ART, style=brand_color, justify="center", no_wrap=True, overflow="crop")
    console.print(Panel(art_text, border_style=brand_color, expand=False))
    console.print(f"[{brand_color}]●[/] [bold white]Azelia Clips[/] | [italic]AI Video Toolkit[/]", justify="center")
    console.print("[grey50]Login successful. Starting Azelia engine...[/]\n", justify="center")


    web_dir = project_root / "web"

    if dev:
        console.print("[bold blue]🎬 Azelia Clips[/bold blue] — Development Mode\n")
        console.print("[dim]Starting Astro dev server + FastAPI with reload...[/dim]")
        console.print(f"[green]→[/green] Frontend: http://localhost:4321")
        console.print(f"[green]→[/green] API:      http://localhost:{port}")
        console.print("[dim]Press Ctrl+C to stop both.[/dim]\n")

        # Start Astro dev server in background
        astro_proc = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=str(web_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            import uvicorn
            uvicorn.run("server.app:app", host=host, port=port, reload=True)
        finally:
            astro_proc.terminate()
            astro_proc.wait()
        return

    # Production mode
    if not no_build:
        console.print("[bold blue]🎬 Azelia Clips[/bold blue] — Building frontend...\n")
        if not (web_dir / "node_modules").exists():
            console.print("[dim]Installing frontend dependencies...[/dim]")
            subprocess.run(["npm", "install"], cwd=str(web_dir), capture_output=True, text=True)

        # Astro bakes PUBLIC_* vars at build time. Auto-derive them from the root .env
        # so users only need to set SUPABASE_URL / SUPABASE_KEY in one place.
        build_env = os.environ.copy()
        if not build_env.get("PUBLIC_SUPABASE_URL") and build_env.get("SUPABASE_URL"):
            build_env["PUBLIC_SUPABASE_URL"] = build_env["SUPABASE_URL"]
        if not build_env.get("PUBLIC_SUPABASE_ANON_KEY") and build_env.get("SUPABASE_KEY"):
            build_env["PUBLIC_SUPABASE_ANON_KEY"] = build_env["SUPABASE_KEY"]

        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(web_dir),
            capture_output=True,
            text=True,
            env=build_env,
        )
        if result.returncode != 0:
            console.print(f"[red]Build failed:[/red]\n{result.stderr}")
            raise typer.Exit(1)
        console.print("[green]✓[/green] Frontend built successfully\n")

    # Check if build exists (mandatory before starting)
    dist_dir = web_dir / "dist"
    if not (dist_dir / "index.html").exists():
        console.print("[yellow]⚠[/yellow] No frontend build found. Run without --no-build flag first:")
        console.print("[dim]  azelia start[/dim]")
        raise typer.Exit(1)

    # Use localhost for clickable link instead of 0.0.0.0
    display_host = "localhost" if host == "0.0.0.0" else host
    console.print(f"[bold blue]🎬 Azelia Clips[/bold blue] — Server running at [link=http://{display_host}:{port}]http://{display_host}:{port}[/link]\n")
    console.print("[dim]Press Ctrl+C to stop.[/dim]")

    def open_browser():
        import urllib.request
        for _ in range(30):  # Up to 15 seconds
            time.sleep(0.5)
            try:
                urllib.request.urlopen(f"http://localhost:{port}/api/health", timeout=2)
                webbrowser.open(f"http://{display_host}:{port}")
                return
            except Exception:
                continue

    threading.Thread(target=open_browser, daemon=True).start()

    # Restart watcher. Triggered by:
    #   - self_update.sh touching <data_dir>/.restart after an update, and
    #   - a profile switch (POST /api/profiles/{id}/activate) doing the same.
    # The azelia wrapper bin (see install.sh) loops on exit code 42 and
    # re-launches the server with the freshly resolved active profile.
    #
    # NOTE: re-read settings.data_dir on every tick. It can change after boot
    # (first-run migration moves ~/.azelia/data → profiles/<slug>/), so a path
    # captured once would watch a directory that no longer exists.
    def restart_watcher():
        from packages.core.config import settings as _s
        while True:
            try:
                sentinel = _s.data_dir / ".restart"
                if sentinel.exists():
                    sentinel.unlink()
                    console.print("[bold yellow]🔄 Restart requested — relaunching server…[/bold yellow]")
                    os._exit(42)
            except Exception:
                pass
            time.sleep(1.5)

    threading.Thread(target=restart_watcher, daemon=True).start()

    import uvicorn
    uvicorn.run("server.app:app", host=host, port=port)


if __name__ == "__main__":
    app()

