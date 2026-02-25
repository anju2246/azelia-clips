"""
Speaker Diarization using Pyannote Audio (MIT License).

Identifies WHO speaks WHEN in an audio file. Each speech segment is labeled
with a speaker ID (SPEAKER_00, SPEAKER_01, etc.).

Requires: User must provide a HuggingFace token (free) in their .env file
as HF_TOKEN to download the Pyannote pretrained models on first run.
"""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()


@dataclass
class DiarizationSegment:
    """A segment of speech attributed to a specific speaker."""
    start: float
    end: float
    speaker: str  # e.g. "SPEAKER_00", "SPEAKER_01"


class SpeakerDiarizer:
    """
    Speaker diarization using Pyannote Audio (MIT license).
    
    Usage:
        diarizer = SpeakerDiarizer()
        segments = diarizer.diarize("podcast.wav")
        # [DiarizationSegment(start=0.5, end=5.2, speaker="SPEAKER_00"), ...]
    """
    
    def __init__(self, hf_token: Optional[str] = None):
        """
        Initialize the diarization pipeline.
        
        Args:
            hf_token: HuggingFace token. If not provided, reads from HF_TOKEN env var.
        """
        self.hf_token = hf_token or os.getenv("HF_TOKEN")
        self._pipeline = None  # Lazy-loaded
    
    @property
    def is_available(self) -> bool:
        """Check if diarization can run (token + library available)."""
        if not self.hf_token:
            return False
        try:
            import pyannote.audio
            return True
        except ImportError:
            return False
    
    def _load_pipeline(self):
        """Lazy-load the Pyannote pipeline (heavy, ~500MB on first download)."""
        if self._pipeline is not None:
            return
        
        if not self.hf_token:
            raise RuntimeError(
                "HuggingFace token required for speaker diarization. "
                "Set HF_TOKEN in your .env file. "
                "Get a free token at: https://huggingface.co/settings/tokens"
            )
        
        # Fix SpeechBrain checking deprecated torchaudio functions
        self._patch_speechbrain_torchaudio()
        
        try:
            from pyannote.audio import Pipeline
            
            console.print("[blue]🔊[/blue] Loading speaker diarization model (first run downloads ~500MB)...")
            self._pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                token=self.hf_token,
            )
            console.print("[green]✓[/green] Diarization model loaded")
        except ImportError:
            raise RuntimeError(
                "pyannote.audio not installed. Run: pip install pyannote.audio>=3.1.0"
            )

    @staticmethod
    def _patch_speechbrain_torchaudio():
        """
        Monkey-patch torchaudio to bypass SpeechBrain's check for a deprecated
        function (list_audio_backends), which was removed in torchaudio 2.1.0+.
        """
        import torchaudio
        if not hasattr(torchaudio, "list_audio_backends"):
            torchaudio.list_audio_backends = lambda: ["ffmpeg", "sox"]
            console.print("[dim]   Applied SpeechBrain torchaudio fallback[/dim]")
    
    def diarize(
        self,
        audio_path: Path | str,
        num_speakers: int | None = None,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
    ) -> list[DiarizationSegment]:
        """
        Run speaker diarization on an audio/video file.
        
        Args:
            audio_path: Path to audio or video file.
            num_speakers: Exact number of speakers (if known). Overrides auto-detection.
            min_speakers: Minimum expected speakers (hint for auto-detection).
            max_speakers: Maximum expected speakers (hint for auto-detection).
            
        Returns:
            List of DiarizationSegment with start, end, and speaker label.
        """
        self._load_pipeline()
        
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        
        console.print(f"[blue]🔊[/blue] Diarizing speakers in {audio_path.name}...")
        
        # Build pipeline kwargs
        pipeline_kwargs: dict = {}
        if num_speakers is not None:
            pipeline_kwargs["num_speakers"] = num_speakers
        if min_speakers is not None:
            pipeline_kwargs["min_speakers"] = min_speakers
        if max_speakers is not None:
            pipeline_kwargs["max_speakers"] = max_speakers
        
        # Run the pipeline
        diarization = self._pipeline(str(audio_path), **pipeline_kwargs)
        
        # Handle Pyannote 4.x API where output is wrapped
        output_annotation = diarization.speaker_diarization if hasattr(diarization, 'speaker_diarization') else diarization
        
        # Convert to our dataclass format
        segments = []
        for turn, _, speaker in output_annotation.itertracks(yield_label=True):
            segments.append(DiarizationSegment(
                start=turn.start,
                end=turn.end,
                speaker=speaker,
            ))
        
        # Log summary
        unique_speakers = set(seg.speaker for seg in segments)
        console.print(
            f"[green]✓[/green] Found {len(unique_speakers)} speakers, "
            f"{len(segments)} speech segments"
        )
        
        return segments


def assign_speakers_to_transcript(transcript_segments, diarization_segments):
    """
    Cross-reference transcript segments with diarization to assign speaker labels.
    
    For each transcript segment, finds the diarization segment with the most overlap
    and assigns its speaker label.
    
    Args:
        transcript_segments: List of Segment (from transcriber.py) with start/end times.
        diarization_segments: List of DiarizationSegment from diarize().
        
    Returns:
        The same transcript_segments list, with speaker fields populated.
    """
    if not diarization_segments:
        return transcript_segments
    
    for seg in transcript_segments:
        best_speaker = None
        best_overlap = 0.0
        
        for dseg in diarization_segments:
            # Calculate overlap between transcript segment and diarization segment
            overlap_start = max(seg.start, dseg.start)
            overlap_end = min(seg.end, dseg.end)
            overlap = max(0.0, overlap_end - overlap_start)
            
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = dseg.speaker
        
        if best_speaker:
            seg.speaker = best_speaker
    
    return transcript_segments
