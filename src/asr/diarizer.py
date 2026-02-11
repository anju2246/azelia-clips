"""Speaker diarization using pyannote.audio for identifying who is speaking."""

from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.config import settings

console = Console()


@dataclass
class SpeakerSegment:
    """A segment where a specific speaker is talking."""
    speaker: str      # e.g., "SPEAKER_00", "SPEAKER_01"
    start: float      # Start time in seconds
    end: float        # End time in seconds


class SpeakerDiarizer:
    """
    Speaker diarization using pyannote.audio.
    
    Identifies which speaker is talking at each moment in an audio/video file.
    Requires HuggingFace token with access to pyannote models.
    """
    
    def __init__(self, hf_token: str | None = None):
        self.hf_token = hf_token or settings.hf_token
        if not self.hf_token:
            raise ValueError(
                "HuggingFace token required. Set HF_TOKEN in .env or pass to constructor."
            )
        self._pipeline = None
    
    def _load_pipeline(self):
        """Lazy load the diarization pipeline from cache."""
        if self._pipeline is not None:
            return
        
        try:
            # Use cached model from model_manager
            from src.model_manager import get_diarization_pipeline
            self._pipeline = get_diarization_pipeline()
        except Exception as e:
            # Fallback to direct loading if model_manager fails
            console.print(f"[yellow]Cache failed, loading directly: {e}[/yellow]")
            console.print(f"[blue]🎙️[/blue] Loading speaker diarization model...")
            
            from pyannote.audio import Pipeline
            import torch
            
            original_load = torch.load
            def patched_load(*args, **kwargs):
                kwargs['weights_only'] = False
                return original_load(*args, **kwargs)
            torch.load = patched_load
            
            # Force CPU to avoid MPS OOM
            device = torch.device("cpu")
            console.print(f"[yellow]⚠️ Using CPU for diarization (evita OOM)[/yellow]")
            
            try:
                self._pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    use_auth_token=self.hf_token,
                ).to(device)
            finally:
                torch.load = original_load
            
            console.print(f"[green]✓[/green] Diarization model loaded")
    
    def diarize(
        self,
        audio_path: Path | str,
        num_speakers: int | None = None,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
    ) -> list[SpeakerSegment]:
        """
        Perform speaker diarization on an audio/video file.
        
        Args:
            audio_path: Path to audio or video file
            num_speakers: Exact number of speakers (if known)
            min_speakers: Minimum number of speakers
            max_speakers: Maximum number of speakers
        
        Returns:
            List of SpeakerSegment objects with speaker labels and timestamps
        """
        self._load_pipeline()
        
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        
        # If input is video, extract audio first
        temp_audio = None
        if audio_path.suffix.lower() in ['.mp4', '.mkv', '.mov', '.avi', '.webm']:
            import tempfile
            import subprocess
            
            console.print(f"[blue]🎵[/blue] Extracting audio from video...")
            temp_audio = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            temp_audio.close()
            
            cmd = [
                '/usr/local/bin/ffmpeg', '-y',
                '-i', str(audio_path),
                '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1',
                temp_audio.name
            ]
            subprocess.run(cmd, capture_output=True)
            audio_path = Path(temp_audio.name)
        
        console.print(f"[blue]🎙️[/blue] Performing speaker diarization...")
        console.print(f"[dim]   File: {audio_path.name}[/dim]")
        
        # Run diarization
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Analyzing speakers...", total=None)
            
            # Configure speaker count if specified
            kwargs = {}
            if num_speakers is not None:
                kwargs["num_speakers"] = num_speakers
            if min_speakers is not None:
                kwargs["min_speakers"] = min_speakers
            if max_speakers is not None:
                kwargs["max_speakers"] = max_speakers
            
            diarization = self._pipeline(str(audio_path), **kwargs)
        
        # Convert to our format
        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append(SpeakerSegment(
                speaker=speaker,
                start=turn.start,
                end=turn.end,
            ))
        
        # Sort by start time
        segments.sort(key=lambda s: s.start)
        
        # FIX: Filter out very short segments (likely noise, not real speech)
        # Segments < 0.5s are probably false positives from diarization
        min_segment_duration = 0.5
        filtered_segments = [s for s in segments if (s.end - s.start) >= min_segment_duration]
        
        if len(filtered_segments) < len(segments):
            removed = len(segments) - len(filtered_segments)
            console.print(f"[dim]   Filtered out {removed} short segments (< {min_segment_duration}s)[/dim]")
            segments = filtered_segments
        
        # Get unique speakers
        speakers = set(s.speaker for s in segments)
        console.print(f"[green]✓[/green] Found {len(speakers)} speakers, {len(segments)} segments")
        
        # Cleanup temp audio file
        if temp_audio is not None:
            Path(temp_audio.name).unlink(missing_ok=True)
        
        return segments
    
    def get_speaker_at_time(
        self,
        segments: list[SpeakerSegment],
        timestamp: float,
    ) -> str | None:
        """
        Get the speaker who is talking at a specific timestamp.
        
        Args:
            segments: List of diarization segments
            timestamp: Time in seconds
        
        Returns:
            Speaker label (e.g., "SPEAKER_00") or None if no one is speaking
        """
        for seg in segments:
            if seg.start <= timestamp <= seg.end:
                return seg.speaker
        return None


def get_speaking_timeline(
    audio_path: Path | str,
    num_speakers: int = 2,
) -> list[SpeakerSegment]:
    """
    Convenience function to get speaker timeline.
    
    Args:
        audio_path: Path to audio/video file
        num_speakers: Expected number of speakers (default 2 for podcast)
    
    Returns:
        List of SpeakerSegment with speaker labels and timestamps
    """
    diarizer = SpeakerDiarizer()
    return diarizer.diarize(audio_path, num_speakers=num_speakers)
