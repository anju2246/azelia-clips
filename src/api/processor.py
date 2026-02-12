import os
from pathlib import Path
from src.batch_processor import BatchProcessor, EpisodeConfig
from rich.console import Console

console = Console()

class SingleVideoProcessor(BatchProcessor):
    """
    Adapter for processing single video files uploaded via API.
    Bypasses the strict external drive folder structure requirement.
    """
    def __init__(self, output_dir: Path, **kwargs):
        # Bypass parent __init__ checks by initializing manually or using dummy path
        # We override __init__ to avoid the external drive check
        self.base_path = output_dir
        self.clips_per_episode = kwargs.get('clips_per_episode')
        self.min_duration = kwargs.get('min_duration', 30)
        self.max_duration = kwargs.get('max_duration', 90)
        self.min_score = kwargs.get('min_score', 70)
        self.use_supabase = False # Always false for local uploads unless configured
        self.target_clip_id = None
        self.auth_token = kwargs.get('auth_token')
        
        # New: Pass transcription config to parent logic
        transcription_config = kwargs.get('transcription_config')
        super().__init__(
            external_drive_path=output_dir, # Used as dummy base path
            transcription_config=transcription_config
        )
        
        # Ensure output dir exists
        self.base_path.mkdir(parents=True, exist_ok=True)
        
    def process_single(self, video_path: Path, job_id: str) -> int:
        """Process a single video file."""
        # Create a dummy EpisodeConfig
        # We treat the job folder as the "episode folder"
        episode_folder = video_path.parent
        
        config = EpisodeConfig(
            episode_number=0, # Dummy number
            episode_folder=episode_folder,
            video_path=video_path,
            transcript_path=None
        )
        
        console.print(f"[bold green]🚀 Starting single file processing for Job {job_id}[/bold green]")
        
        # Reuse the core logic from parent
        # Note: parent process_episode writes to episode.clips_folder -> job_folder/clips
        return self.process_episode(config, job_id=job_id)
