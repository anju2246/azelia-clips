"""WhisperX transcription wrapper with word-level timestamps."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


@dataclass
class Word:
    """A single word with timing information."""
    word: str
    start: float
    end: float
    score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {"word": self.word, "start": self.start, "end": self.end, "score": self.score}


@dataclass
class Segment:
    """A transcript segment (sentence/phrase)."""
    text: str
    start: float
    end: float
    words: list[Word] = field(default_factory=list)
    speaker: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "words": [w.to_dict() for w in self.words],
            "speaker": self.speaker,
        }


@dataclass
class Transcript:
    """Complete transcript with segments and metadata."""
    segments: list[Segment]
    language: str
    duration: float
    source_file: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "duration": self.duration,
            "source_file": self.source_file,
            "segments": [s.to_dict() for s in self.segments],
        }

    def save(self, path: Path) -> None:
        """Save transcript to JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        console.print(f"[green]✓[/green] Transcript saved to {path}")

    @classmethod
    def load(cls, path: Path) -> "Transcript":
        """Load transcript from JSON file."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        segments = []
        for seg in data["segments"]:
            words = [Word(**w) for w in seg.get("words", [])]
            segments.append(Segment(
                text=seg["text"],
                start=seg["start"],
                end=seg["end"],
                words=words,
                speaker=seg.get("speaker"),
            ))

        return cls(
            segments=segments,
            language=data["language"],
            duration=data["duration"],
            source_file=data["source_file"],
        )

    def get_text_in_range(self, start: float, end: float) -> str:
        """Get concatenated text for a time range."""
        words = []
        for seg in self.segments:
            for word in seg.words:
                if start <= word.start <= end:
                    words.append(word.word)
        return " ".join(words)
    
    def slice(self, start: float, end: float) -> "Transcript":
        """Extract a portion of the transcript as a new Transcript object.
        
        This avoids redundant transcription when processing clips from a 
        full episode that was already transcribed.
        
        Args:
            start: Start time in seconds (relative to original)
            end: End time in seconds (relative to original)
            
        Returns:
            New Transcript with segments in range, timestamps adjusted to start from 0
        """
        sliced_segments = []
        
        for seg in self.segments:
            # Check if segment overlaps with range
            if seg.end < start or seg.start > end:
                continue  # Segment outside range
            
            # Clip segment times to range
            seg_start = max(seg.start, start)
            seg_end = min(seg.end, end)
            
            # Filter and adjust words
            sliced_words = []
            for word in seg.words:
                if word.start >= start and word.end <= end:
                    # Adjust word timing relative to clip start
                    sliced_words.append(Word(
                        word=word.word,
                        start=word.start - start,
                        end=word.end - start,
                        score=word.score,
                    ))
            
            # Only include if we have words
            if sliced_words:
                sliced_segments.append(Segment(
                    text=" ".join(w.word for w in sliced_words),
                    start=seg_start - start,  # Adjust to clip-relative time
                    end=seg_end - start,
                    words=sliced_words,
                    speaker=seg.speaker,
                ))
        
        return Transcript(
            segments=sliced_segments,
            language=self.language,
            duration=end - start,
            source_file=self.source_file,
        )


class Transcriber:
    """WhisperX-based transcriber with word-level alignment."""

    def __init__(
        self,
        model_name: str = "large-v3",
        device: str = "mps",
        compute_type: str = "float16",
        batch_size: int = 8,
    ):
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.batch_size = batch_size
        self._model = None
        self._align_model = None

    def _load_model(self):
        """Lazy load WhisperX model."""
        if self._model is not None:
            return

        try:
            import whisperx
        except ImportError:
            raise ImportError(
                "WhisperX not installed. Run: pip install -e '.[asr]'"
            )

        console.print(f"[blue]📥[/blue] Loading Whisper model: [bold]{self.model_name}[/bold]")
        console.print(f"[dim]   Device: {self.device} | This may take 1-2 minutes on first run...[/dim]")

        self._model = whisperx.load_model(
            self.model_name,
            self.device,
            compute_type=self.compute_type,
            vad_method="silero",  # Use silero VAD to avoid Pyannote/PyTorch 2.6 issues
        )
        console.print(f"[green]✓[/green] Model loaded successfully")

    def transcribe(self, audio_path: Path | str, language: str = "es") -> Transcript:
        """
        Transcribe audio file with word-level timestamps.

        Args:
            audio_path: Path to audio/video file
            language: Language code (es, en, etc.)

        Returns:
            Transcript object with segments and word timings
        """
        import whisperx

        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        self._load_model()

        console.print(f"[blue]🎤[/blue] Transcribing: {audio_path.name}")

        # Load audio
        audio = whisperx.load_audio(str(audio_path))
        duration = len(audio) / 16000  # Whisper uses 16kHz

        # Transcribe
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Transcribing audio...", total=None)
            result = self._model.transcribe(
                audio,
                batch_size=self.batch_size,
                language=language,
            )

        # Align for word-level timestamps
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Aligning words...", total=None)
            model_a, metadata = whisperx.load_align_model(
                language_code=language,
                device=self.device,
            )
            result = whisperx.align(
                result["segments"],
                model_a,
                metadata,
                audio,
                self.device,
                return_char_alignments=False,
            )

        # Convert to our format
        segments = []
        for seg in result["segments"]:
            words = []
            for w in seg.get("words", []):
                if "start" in w and "end" in w:
                    words.append(Word(
                        word=w["word"],
                        start=w["start"],
                        end=w["end"],
                        score=w.get("score", 1.0),
                    ))

            segments.append(Segment(
                text=seg["text"].strip(),
                start=seg["start"],
                end=seg["end"],
                words=words,
            ))

        transcript = Transcript(
            segments=segments,
            language=language,
            duration=duration,
            source_file=str(audio_path),
        )

        console.print(
            f"[green]✓[/green] Transcribed {len(segments)} segments, "
            f"{sum(len(s.words) for s in segments)} words"
        )

        return transcript


class MLXTranscriber:
    """MLX-Whisper based transcriber optimized for Apple Silicon.
    
    This is ~5-10x faster than WhisperX on M1/M2/M3 Macs.
    """

    def __init__(
        self,
        model_name: str = "mlx-community/whisper-large-v3-mlx",
        language: str = "es",
    ):
        """Initialize MLX transcriber.
        
        Args:
            model_name: HuggingFace model path for MLX Whisper
            language: Default language for transcription
        """
        self.model_name = model_name
        self.language = language
        # Map simple names to full model paths
        self._model_map = {
            "tiny": "mlx-community/whisper-tiny-mlx",
            "base": "mlx-community/whisper-base-mlx",
            "small": "mlx-community/whisper-small-mlx",
            "medium": "mlx-community/whisper-medium-mlx",
            "large": "mlx-community/whisper-large-v3-mlx",
            "large-v3": "mlx-community/whisper-large-v3-mlx",
            "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
        }
        # Resolve model name
        if model_name in self._model_map:
            self.model_name = self._model_map[model_name]

    def transcribe(self, audio_path: Path | str, language: str | None = None) -> Transcript:
        """
        Transcribe audio file with word-level timestamps using MLX-Whisper.

        Args:
            audio_path: Path to audio/video file
            language: Language code (es, en, etc.) - overrides default

        Returns:
            Transcript object with segments and word timings
        """
        try:
            import mlx_whisper
        except ImportError:
            raise ImportError(
                "MLX-Whisper not installed. Run: pip install mlx-whisper"
            )

        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        lang = language or self.language
        
        console.print(f"[blue]🍎[/blue] MLX-Whisper transcribing: [bold]{audio_path.name}[/bold]")
        console.print(f"[dim]   Model: {self.model_name} | Language: {lang}[/dim]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Transcribing with MLX (Apple Silicon optimized)...", total=None)
            
            # MLX-Whisper transcription with word timestamps
            result = mlx_whisper.transcribe(
                str(audio_path),
                path_or_hf_repo=self.model_name,
                language=lang,
                word_timestamps=True,  # Enable word-level timestamps
                verbose=False,
            )

        # Extract duration from segments
        duration = 0.0
        if result.get("segments"):
            duration = result["segments"][-1].get("end", 0.0)

        # Convert to our format
        segments = []
        for seg in result.get("segments", []):
            words = []
            for w in seg.get("words", []):
                if "start" in w and "end" in w:
                    words.append(Word(
                        word=w.get("word", "").strip(),
                        start=w["start"],
                        end=w["end"],
                        score=w.get("probability", 1.0),
                    ))

            segments.append(Segment(
                text=seg.get("text", "").strip(),
                start=seg.get("start", 0.0),
                end=seg.get("end", 0.0),
                words=words,
            ))

        transcript = Transcript(
            segments=segments,
            language=lang,
            duration=duration,
            source_file=str(audio_path),
        )

        console.print(
            f"[green]✓[/green] Transcribed {len(segments)} segments, "
            f"{sum(len(s.words) for s in segments)} words"
        )

        return transcript


def transcribe_file(
    audio_path: Path | str,
    output_path: Path | str | None = None,
    language: str = "es",
    use_mlx: bool | None = None,
) -> Transcript:
    """
    Convenience function to transcribe a file and optionally save.

    Args:
        audio_path: Path to audio/video file
        output_path: Optional path to save JSON transcript
        language: Language code
        use_mlx: Force MLX (True) or WhisperX (False). If None, auto-detect (MLX on Mac).

    Returns:
        Transcript object
    """
    import platform
    from src.config import settings

    # Auto-detect: use MLX on Mac (Apple Silicon), WhisperX elsewhere
    if use_mlx is None:
        use_mlx = platform.system() == "Darwin"  # macOS

    if use_mlx:
        try:
            transcriber = MLXTranscriber(
                model_name=settings.whisper_model,
                language=language,
            )
            transcript = transcriber.transcribe(audio_path, language=language)
        except ImportError:
            console.print("[yellow]⚠️ MLX-Whisper not available, falling back to WhisperX[/yellow]")
            transcriber = Transcriber(
                model_name=settings.whisper_model,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
                batch_size=settings.whisper_batch_size,
            )
            transcript = transcriber.transcribe(audio_path, language=language)
    else:
        transcriber = Transcriber(
            model_name=settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
            batch_size=settings.whisper_batch_size,
        )
        transcript = transcriber.transcribe(audio_path, language=language)

    if output_path:
        transcript.save(Path(output_path))

    return transcript
