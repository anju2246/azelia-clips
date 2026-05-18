from pathlib import Path
from typing import Dict, Any, Optional
from rich.console import Console
from .base import TranscriptionSource
from packages.clips.transcription.transcriber import Transcript, Segment, Word

console = Console()

class LocalWhisperSource(TranscriptionSource):
    """Transcribes audio using local Whisper (MLX or OpenAI)."""
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Always valid for local execution."""
        return True

    def get_transcript(self, resource_id: str, **kwargs) -> Optional[Transcript]:
        """
        Transcribe audio file locally.
        resource_id: Path to local audio/video file.
        """
        video_path = Path(resource_id)
        if not video_path.exists():
            raise FileNotFoundError(f"File not found: {video_path}")

        # Try MLX Whisper (Apple Silicon Optimized)
        try:
            import mlx_whisper
            return self._transcribe_mlx(video_path)
        except ImportError:
            console.print("[yellow]mlx-whisper not found, falling back to openai-whisper[/yellow]")
            return self._transcribe_openai(video_path)

    def _transcribe_mlx(self, video_path: Path) -> Transcript:
        import mlx_whisper
        
        console.print(f"[blue]🎤[/blue] Transcribing with MLX Whisper (Apple Silicon)...")
        result = mlx_whisper.transcribe(
            str(video_path),
            path_or_hf_repo="mlx-community/whisper-large-v3-turbo",
            word_timestamps=True,
            language="es"
        )
        transcript = self._format_result(result, str(video_path))
        
        # Optional: Run speaker diarization if HF token is available
        transcript = self._try_diarize(video_path, transcript)
        
        return transcript

    def _transcribe_openai(self, video_path: Path) -> Transcript:
        import whisper
        
        console.print(f"[blue]🎤[/blue] Transcribing with Standard Whisper (CPU/CUDA)...")
        model = whisper.load_model("medium")
        result = model.transcribe(
            str(video_path),
            language="es",
            word_timestamps=True
        )
        transcript = self._format_result(result, str(video_path))
        
        # Optional: Run speaker diarization if HF token is available
        transcript = self._try_diarize(video_path, transcript)
        
        return transcript

    def _format_result(self, result: dict, source_file: str) -> Transcript:
        segments = []
        for seg in result["segments"]:
            words = [
                Word(word=w["word"], start=w["start"], end=w["end"], score=w.get("probability", 1.0))
                for w in seg.get("words", [])
            ]
            segments.append(Segment(
                text=seg["text"].strip(),
                start=seg["start"],
                end=seg["end"],
                words=words,
            ))
            
        return Transcript(
            segments=segments,
            language="es",
            duration=result["segments"][-1]["end"] if result["segments"] else 0,
            source_file=source_file,
        )

    def _try_diarize(self, video_path: Path, transcript: Transcript) -> Transcript:
        """
        Attempt speaker diarization. Gracefully skips if:
        - No HF_TOKEN configured
        - pyannote.audio not installed
        - Any runtime error
        
        The transcript is returned with or without speaker labels.
        """
        try:
            from packages.clips.transcription.diarizer import (
                get_diarizer,
                assign_speakers_to_transcript,
            )

            # Singleton — pyannote's Pipeline is ~500 MB and ~10-20 s to
            # deserialize. Per-clip re-load was the perceived "slow face
            # tracking" symptom.
            diarizer = get_diarizer()
            if not diarizer.is_available:
                console.print(
                    "[dim]Speaker diarization skipped (no HF_TOKEN set). "
                    "Set HF_TOKEN in .env for speaker identification.[/dim]"
                )
                return transcript
            
            diarization_segments = diarizer.diarize(video_path)
            assign_speakers_to_transcript(transcript.segments, diarization_segments)
            
        except Exception as e:
            console.print(f"[yellow]⚠ Diarization failed: {e}. Continuing without speaker labels.[/yellow]")
        
        return transcript
