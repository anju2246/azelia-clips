import os
from pathlib import Path
from typing import Dict, Any, Optional
from rich.console import Console
from .base import TranscriptionSource
from src.asr.transcriber import Transcript, Segment, Word

console = Console()

class AssemblyAISource(TranscriptionSource):
    """Transcribes audio using AssemblyAI API."""
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Check for API Key."""
        return bool(config.get("assemblyai_api_key"))

    def get_transcript(self, resource_id: str, **kwargs) -> Optional[Transcript]:
        """
        Transcribe audio file.
        resource_id: Path to local audio/video file.
        kwargs: Must contain 'assemblyai_api_key'.
        """
        api_key = kwargs.get("assemblyai_api_key")
        language = kwargs.get("language", "es")
        
        if not api_key:
            raise ValueError("AssemblyAI API Key required")

        try:
            import assemblyai as aai
        except ImportError:
            console.print("[red]AssemblyAI SDK not installed. Run: pip install assemblyai[/red]")
            return None

        aai.settings.api_key = api_key
        
        audio_path = Path(resource_id)
        if not audio_path.exists():
            raise FileNotFoundError(f"File not found: {audio_path}")

        console.print(f"[blue]☁️[/blue] Uploading to AssemblyAI ({audio_path.name})...")

        transcriber = aai.Transcriber()
        config = aai.TranscriptionConfig(
            language_code=language,
            speaker_labels=True,
            punctuate=True,
            format_text=True,
            word_timestamps=True # Critical for clips
        )

        transcript = transcriber.transcribe(str(audio_path), config=config)
        
        if transcript.status == aai.TranscriptStatus.error:
            raise RuntimeError(f"Transcription failed: {transcript.error}")
            
        console.print(f"[green]✓[/green] Analysis Complete. Mapping to internal format...")
        
        return self._to_transcript(transcript, str(audio_path))

    def _to_transcript(self, aai_transcript: Any, source_file: str) -> Transcript:
        """Convert AssemblyAI result to internal Transcript format."""
        
        # Map speakers
        # AssemblyAI uses "A", "B", etc. We map to SPEAKER_00, SPEAKER_01
        speaker_map = {}
        def get_speaker_label(label):
            if label not in speaker_map:
                idx = len(speaker_map)
                speaker_map[label] = f"SPEAKER_{idx:02d}"
            return speaker_map[label]

        segments = []
        # Group words into segments if utterances are provided
        if aai_transcript.utterances:
            for utt in aai_transcript.utterances:
                words = []
                for w in utt.words:
                    words.append(Word(
                        word=w.text,
                        start=w.start / 1000.0,
                        end=w.end / 1000.0,
                        score=w.confidence
                    ))
                
                segments.append(Segment(
                    text=utt.text,
                    start=utt.start / 1000.0,
                    end=utt.end / 1000.0,
                    words=words,
                    speaker=get_speaker_label(utt.speaker)
                ))
        else:
            # Fallback if no utterances (shouldn't happen with speaker_labels=True)
            segments.append(Segment(
                text=aai_transcript.text,
                start=0,
                end=aai_transcript.audio_duration,
                words=[],
                speaker="SPEAKER_00"
            ))

        return Transcript(
            segments=segments,
            language=aai_transcript.language_code,
            duration=aai_transcript.audio_duration,
            source_file=source_file
        )
