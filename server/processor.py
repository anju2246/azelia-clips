import os
from pathlib import Path

from rich.console import Console

from packages.clips.pipeline import BatchProcessor, EpisodeConfig

console = Console()

class SingleVideoProcessor(BatchProcessor):
    """
    Adapter for processing single video files uploaded via API.
    Bypasses the strict external drive folder structure requirement.
    """
    def __init__(self, output_dir: Path, **kwargs):
        self.base_path = output_dir
        self.clips_per_episode = kwargs.get('clips_per_episode')
        self.min_duration = kwargs.get('min_duration', 30)
        self.max_duration = kwargs.get('max_duration', 90)
        self.min_score = kwargs.get('min_score', 70)
        self.use_supabase = False  # local-first MVP
        self.target_clip_id = None
        self.auth_token = kwargs.get('auth_token')

        transcription_config = kwargs.get('transcription_config')
        super().__init__(
            external_drive_path=output_dir,  # dummy base path for the parent's check
            transcription_config=transcription_config,
            use_supabase=False,
            template_id=kwargs.get('template_id'),
        )
        self.base_path.mkdir(parents=True, exist_ok=True)

    def process_single(
        self,
        video_path: Path,
        job_id: str,
        start_from_clip: int = 0,
    ) -> int:
        """Process a single video file (upload-flow entry-point).

        Mirrors the library-flow capabilities so pause/resume work identically:
        - extracts episode_number from the folder name (regex EP\\d+) instead of
          hard-coding 0, so Supabase lookups (`get_transcript_from_supabase("EP097")`)
          succeed when the video lives in a real EP-numbered folder.
        - accepts start_from_clip so resume can skip already-rendered clips.
        """
        # If video_path is a symlink (typical for /api/process-local), resolve
        # to the real folder so clips render alongside the source video.
        try:
            original_path = Path(os.path.realpath(video_path))
            original_dir = original_path.parent
            if os.access(original_dir, os.W_OK):
                episode_folder = original_dir
                console.print(
                    f"[green]✓ Local write access confirmed -> Exporting clips to {episode_folder}/clips[/green]"
                )
            else:
                episode_folder = video_path.parent
                console.print(
                    f"[yellow]⚠️ No write access to {original_dir} -> Using job folder {episode_folder}[/yellow]"
                )
        except Exception:
            episode_folder = video_path.parent
            console.print(
                f"[yellow]⚠️ Could not resolve original path -> Using job folder {episode_folder}[/yellow]"
            )

        # Auto-detect existing transcript next to the video.
        transcript_path = video_path.parent / "transcript.json"

        # Extract real episode number from the folder so the same EP id used by
        # the library flow reaches BatchProcessor (Supabase lookups, naming, etc).
        import re
        ep_match = re.search(r"EP(\d+)", episode_folder.name, re.IGNORECASE)
        episode_number = int(ep_match.group(1)) if ep_match else 0

        config = EpisodeConfig(
            episode_number=episode_number,
            episode_folder=episode_folder,
            video_path=video_path,
            transcript_path=transcript_path if transcript_path.exists() else None,
        )

        console.print(
            f"[bold green]🚀 Starting single file processing for Job {job_id}[/bold green]"
        )
        return self.process_episode(
            config, job_id=job_id, start_from_clip=start_from_clip
        )
