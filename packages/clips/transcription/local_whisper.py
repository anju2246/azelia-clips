from pathlib import Path
from typing import Any, Dict, Optional

from rich.console import Console

from packages.clips.transcription.transcriber import Segment, Transcript, Word

from .base import TranscriptionSource

console = Console()

class LocalWhisperSource(TranscriptionSource):
    """Transcribes audio using local Whisper (MLX or OpenAI)."""

    def __init__(
        self,
        num_speakers_hint: Optional[int] = None,
        voice_centroids: Optional[dict] = None,
    ):
        """
        Args:
            num_speakers_hint: If set, force the ECAPA diarizer to use
                this exact number of speakers instead of silhouette-based
                auto-detect. For PER-CLIP diarization (short 30-90s audio
                slices) auto-detect is too aggressive — silhouette score
                often picks k=3 on a 1-on-1 interview because of acoustic
                drift across the clip, producing a phantom SPEAKER_NN
                that gets mapped to the wrong face. The pipeline pins
                this to 2 when slicing per-clip. Episode-level transcription
                leaves it None so auto-detect handles panels of 3+.
            voice_centroids: When set, the per-clip diarization skips
                KMeans entirely and assigns each window to the closest
                centroid by cosine similarity. The output segments are
                labeled with the centroid KEYS (the stable episode-level
                SPEAKER_NN that the user labeled in the modal) instead
                of fresh per-clip IDs. Without this, the per-clip
                speaker IDs collide with the labels file 50% of the
                time and the camera follows the wrong person.
        """
        self.num_speakers_hint = num_speakers_hint
        self.voice_centroids = voice_centroids

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
            import mlx_whisper  # noqa: F401 — availability probe
            return self._transcribe_mlx(video_path)
        except ImportError:
            console.print("[yellow]mlx-whisper not found, falling back to openai-whisper[/yellow]")
            return self._transcribe_openai(video_path)

    def _transcribe_mlx(self, video_path: Path) -> Transcript:
        import mlx_whisper

        console.print("[blue]🎤[/blue] Transcribing with MLX Whisper (Apple Silicon)...")
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

        console.print("[blue]🎤[/blue] Transcribing with Standard Whisper (CPU/CUDA)...")
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
        """Run speaker diarization. Raises if both backends fail.

        Order of preference:
        1. **pyannote** — if HF_TOKEN is set AND pyannote.audio is importable.
           Best quality (detects overlap, fine-grained turns).
        2. **ECAPA-TDNN** (SpeechBrain) — default. 100 % offline, no token,
           Apache 2.0. Auto-detects 2-4 speakers via silhouette score.

        There is NO third option: by design, the pipeline never runs the
        face tracker with empty speaker_segments (which would force it to
        fall back to largest-face and produce visibly worse results). If
        neither backend can run, transcription fails fast with a clear
        install message so the user knows what to fix.
        """
        last_error: Exception | None = None

        # ── 1. Try pyannote first if the user opted in via HF_TOKEN ──
        try:
            from packages.clips.transcription.diarizer import (
                assign_speakers_to_transcript,
                get_diarizer,
            )

            diarizer = get_diarizer()
            if diarizer.is_available:
                console.print("[dim]Diarizing with pyannote (HF_TOKEN detected)…[/dim]")
                diarization_segments = diarizer.diarize(video_path)
                assign_speakers_to_transcript(transcript.segments, diarization_segments)
                return transcript
        except Exception as e:
            last_error = e
            console.print(
                f"[yellow]⚠ pyannote failed ({type(e).__name__}: {str(e)[:80]}). "
                "Falling back to ECAPA-TDNN.[/yellow]"
            )

        # ── 2. Fall back to ECAPA-TDNN (no HF_TOKEN needed) ──
        try:
            from packages.clips.audio.speaker_id import SpeakerIdentifier
            from packages.clips.transcription.diarizer import (
                DiarizationSegment,
                assign_speakers_to_transcript,
            )

            if self.voice_centroids:
                console.print(
                    f"[dim]Diarizing with ECAPA-TDNN against {len(self.voice_centroids)} "
                    f"saved voice fingerprint(s) — labels are stable per episode.[/dim]"
                )
                identifier = SpeakerIdentifier()
            elif self.num_speakers_hint is not None:
                console.print(
                    f"[dim]Diarizing with ECAPA-TDNN (forced k={self.num_speakers_hint})…[/dim]"
                )
                identifier = SpeakerIdentifier(num_speakers=self.num_speakers_hint)
            else:
                console.print(
                    "[dim]Diarizing with ECAPA-TDNN (offline, auto-detect 2-4 speakers)…[/dim]"
                )
                # num_speakers=None → silhouette-based auto-detect across 2..max.
                identifier = SpeakerIdentifier(
                    num_speakers=None, min_speakers=2, max_speakers=4
                )
            # ECAPA's run() also extracts per-speaker audio samples to disk —
            # we only need the segment list here, so call diarize() directly
            # via the same audio extraction path used by run().
            import tempfile
            with tempfile.TemporaryDirectory(prefix="azelia_diarize_") as tmpdir:
                wav_path = Path(tmpdir) / "audio.wav"
                SpeakerIdentifier._extract_audio(video_path, wav_path)
                if self.voice_centroids:
                    # Hydrate the dict into numpy arrays for cosine math.
                    import numpy as np
                    centroids_arr = {
                        k: np.asarray(v, dtype=float)
                        for k, v in self.voice_centroids.items()
                    }
                    ecapa_segments = identifier.diarize_against_centroids(
                        wav_path, centroids_arr
                    )
                else:
                    ecapa_segments = identifier.diarize(wav_path)

            # ECAPA returns plain dicts; assign_speakers_to_transcript()
            # expects objects with .start / .end / .speaker attributes
            # (matching the DiarizationSegment dataclass shape).
            diarization_segments = [
                DiarizationSegment(
                    start=s["start"], end=s["end"], speaker=s["speaker"]
                )
                for s in ecapa_segments
            ]
            assign_speakers_to_transcript(transcript.segments, diarization_segments)
            unique = {s.speaker for s in diarization_segments}
            console.print(
                f"[green]✓[/green] ECAPA diarization: {len(unique)} speakers, "
                f"{len(diarization_segments)} segments"
            )
            return transcript

        except ImportError as e:
            # Fresh-install bug — speechbrain/sklearn missing. Surface it
            # so the user runs `pip install -r requirements.txt` instead
            # of silently shipping bad face tracking.
            raise RuntimeError(
                "Speaker diarization is unavailable: ECAPA-TDNN dependencies "
                "are not installed. Run `pip install -r requirements.txt` to "
                f"install speechbrain + scikit-learn. (Original error: {e})"
            ) from e
        except Exception as e:
            # Both backends failed at runtime — bubble up so face tracking
            # never silently degrades to the largest-face heuristic.
            raise RuntimeError(
                f"Speaker diarization failed with both pyannote and ECAPA. "
                f"pyannote error: {last_error}. "
                f"ECAPA error: {type(e).__name__}: {e}"
            ) from e
