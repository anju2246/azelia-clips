from pathlib import Path
from typing import Dict, Any, Optional
from rich.console import Console
from .base import TranscriptionSource
from src.asr.transcriber import Transcript, Segment, Word

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
        return self._format_result(result, str(video_path))

    def _transcribe_openai(self, video_path: Path) -> Transcript:
        import whisper
        
        console.print(f"[blue]🎤[/blue] Transcribing with Standard Whisper (CPU/CUDA)...")
        model = whisper.load_model("medium")
        result = model.transcribe(
            str(video_path),
            language="es",
            word_timestamps=True
        )
        return self._format_result(result, str(video_path))

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
