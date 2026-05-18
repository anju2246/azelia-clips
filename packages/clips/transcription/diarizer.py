"""
Speaker Diarization using Pyannote Audio (MIT License).

Identifies WHO speaks WHEN in an audio file. Each speech segment is labeled
with a speaker ID (SPEAKER_00, SPEAKER_01, etc.).

Requires: User must provide a HuggingFace token (free) in their .env file
as HF_TOKEN to download the Pyannote pretrained models on first run.
"""
import os
import subprocess
import tempfile
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
        # Fix torchcodec AudioDecoder not defined when FFmpeg .dylibs missing
        # (broken @rpath on macOS venvs is common — without this patch the
        # very first diarize() call raises NameError mid-pipeline).
        self._patch_torchcodec()

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

    @staticmethod
    def _patch_torchcodec():
        """Monkey-patch pyannote.audio.core.io.AudioDecoder when torchcodec fails
        to load its FFmpeg shared libs (broken @rpath on macOS venvs).

        pyannote 4.x imports AudioDecoder from torchcodec for audio I/O. If
        torchcodec can't dlopen libavutil, AudioDecoder is never defined in
        io.py's module scope — the pipeline then raises NameError mid-call,
        which has been the silent killer of diarization on a lot of installs.

        Fix: inject a torchaudio-backed AudioDecoder shim into the io module
        so pyannote can read duration/metadata without torchcodec.
        """
        try:
            import pyannote.audio.core.io as _pa_io
            if hasattr(_pa_io, "AudioDecoder") and _pa_io.AudioDecoder is not None:
                return  # torchcodec loaded fine, nothing to do
        except Exception:
            return

        import pathlib as _pathlib
        import tempfile as _tempfile
        import subprocess as _subprocess
        import os as _os
        from dataclasses import dataclass as _dc

        try:
            import torchaudio as _ta
        except Exception:
            return  # torchaudio also missing → no shim possible

        @_dc
        class _AudioMetadata:
            duration: float
            sample_rate: int
            num_channels: int
            num_samples: int

        _VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}

        class _TorchaudioDecoder:
            """Minimal AudioDecoder shim backed by torchaudio + ffmpeg.

            For video files, torchaudio has no backend in most venvs, so we
            extract to a temp WAV with the system ffmpeg first.
            """

            def __init__(self, path):
                self._path = str(path)
                self._tmp_dir = None
                self._wav_path = None
                if _pathlib.Path(self._path).suffix.lower() in _VIDEO_EXTS:
                    self._tmp_dir = _tempfile.mkdtemp(prefix="azelia_dec_")
                    out = _os.path.join(self._tmp_dir, "audio.wav")
                    _subprocess.run(
                        [_os.environ.get("FFMPEG_PATH", "ffmpeg"), "-y",
                         "-i", self._path, "-ac", "1", "-ar", "16000",
                         "-vn", out],
                        capture_output=True, check=True,
                    )
                    self._wav_path = out

            def _effective_path(self):
                return self._wav_path if self._wav_path else self._path

            @property
            def metadata(self):
                info = _ta.info(self._effective_path())
                dur = info.num_frames / info.sample_rate if info.sample_rate else 0.0
                return _AudioMetadata(
                    duration=dur,
                    sample_rate=info.sample_rate,
                    num_channels=info.num_channels,
                    num_samples=info.num_frames,
                )

            def __iter__(self):
                waveform, sr = _ta.load(self._effective_path())
                yield {"waveform": waveform, "sample_rate": sr}

            def __del__(self):
                if self._tmp_dir:
                    import shutil as _shutil
                    try:
                        _shutil.rmtree(self._tmp_dir, ignore_errors=True)
                    except Exception:
                        pass

        _pa_io.AudioDecoder = _TorchaudioDecoder
        console.print("[dim]   Applied torchcodec→torchaudio fallback for pyannote[/dim]")

    @staticmethod
    def _extract_audio_to_wav(audio_path: Path, tmp_dir: str) -> str:
        """Extract any audio/video file to mono 16 kHz WAV via system ffmpeg.

        torchaudio in most venvs lacks ffmpeg/soundfile backends for mp4/mkv,
        so we can't pass video files directly to pyannote. The system ffmpeg
        binary handles everything reliably.
        """
        ffmpeg_bin = os.environ.get("FFMPEG_PATH", "ffmpeg")
        out_wav = os.path.join(tmp_dir, "diarizer_audio.wav")
        cmd = [
            ffmpeg_bin, "-y",
            "-i", str(audio_path),
            "-ac", "1",        # mono
            "-ar", "16000",    # 16 kHz (pyannote requirement)
            "-vn",             # no video
            out_wav,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg audio extraction failed for {audio_path}:\n{result.stderr}"
            )
        return out_wav
    
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
        
        # Pre-extract audio to a temp WAV via system ffmpeg. torchaudio in
        # most venvs has no mp4/mkv backend (the .dylibs ship broken via
        # @rpath on macOS), so feeding a video path directly fails silently.
        # Going through ffmpeg + torchaudio.load() works everywhere.
        with tempfile.TemporaryDirectory(prefix="azelia_diarizer_") as tmp_dir:
            wav_path = self._extract_audio_to_wav(audio_path, tmp_dir)

            import torchaudio
            waveform, sample_rate = torchaudio.load(wav_path)
            audio_input = {"waveform": waveform, "sample_rate": sample_rate}

            diarization = self._pipeline(audio_input, **pipeline_kwargs)

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


# ─── Module-level singleton ──────────────────────────────────────────────────
# Keeps the pyannote Pipeline in memory across all clips in a processing run.
# Loading it per-clip wastes ~10-20 s per clip on model deserialization, and
# also risks double-allocating ~500 MB of model weights into RAM.
_diarizer_instance: Optional["SpeakerDiarizer"] = None


def get_diarizer(hf_token: Optional[str] = None) -> "SpeakerDiarizer":
    """Return the shared SpeakerDiarizer singleton, creating it if needed."""
    global _diarizer_instance
    if _diarizer_instance is None:
        _diarizer_instance = SpeakerDiarizer(hf_token=hf_token)
    elif hf_token and not _diarizer_instance.hf_token:
        _diarizer_instance.hf_token = hf_token
    return _diarizer_instance


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
