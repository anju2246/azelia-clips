"""Voice-based speaker identification using SpeechBrain ECAPA-TDNN.

Alternative to pyannote diarization that does NOT require an HF_TOKEN —
works offline once the model is cached. Useful as a fallback when the
user hasn't set up HuggingFace, or for hosts who don't want their voice
data going through the pyannote pipeline.

Architecture:
    1. Extract audio from video (system ffmpeg → mono 16kHz WAV)
    2. Split into 2s windows with 1s overlap (sliding window)
    3. ECAPA-TDNN generates 192-D embeddings per window
    4. K-means k=2 clusters into SPEAKER_00 / SPEAKER_01
    5. Merge consecutive same-speaker windows into segments
    6. Extract a representative 5-10s audio sample per speaker (pick a
       segment where only ONE speaker talks, longest clean run)
    7. Save samples as WAV to output_dir/speaker_00_sample.wav etc.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Model cache directory (no model files in the repo).
_MODEL_DIR = Path.home() / ".azelia" / "models" / "ecapa"


class SpeakerIdentifier:
    """Identifies and diarizes speakers in audio/video using ECAPA-TDNN.

    Usage::

        identifier = SpeakerIdentifier(num_speakers=2)
        result = identifier.run(Path("episode.mp4"), Path("output/"))
        # result["segments"]    → [{"start": 0.0, "end": 4.5, "speaker": "SPEAKER_00"}, ...]
        # result["samples"]     → {"SPEAKER_00": Path("output/speaker_00_sample.wav")}
        # result["samples_map"] → {"SPEAKER_00": "speaker_00_sample.wav"}
    """

    def __init__(self, num_speakers: int = 2) -> None:
        self.num_speakers = num_speakers
        self._encoder = None  # lazy-loaded

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _ensure_model(self) -> None:
        """Load ECAPA-TDNN from HuggingFace (cached under ~/.azelia/models/ecapa)."""
        if self._encoder is not None:
            return

        try:
            from speechbrain.inference.speaker import EncoderClassifier  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "SpeechBrain is required for voice-based speaker identification.\n"
                "Install it with: pip install speechbrain>=1.0.0\n"
                f"Original error: {exc}"
            ) from exc

        _MODEL_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("Loading ECAPA-TDNN from speechbrain/spkrec-ecapa-voxceleb …")
        self._encoder = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=str(_MODEL_DIR),
            run_opts={"device": "cpu"},
        )
        logger.info("ECAPA-TDNN loaded successfully.")

    # ------------------------------------------------------------------
    # Audio extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_audio(video_path: Path, wav_path: Path) -> None:
        """Use system ffmpeg to extract mono 16kHz WAV from a video file."""
        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(video_path),
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-f", "wav",
            str(wav_path),
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg failed (exit {result.returncode}):\n"
                + result.stderr.decode(errors="replace")
            )

    # ------------------------------------------------------------------
    # Diarization
    # ------------------------------------------------------------------

    def diarize(self, audio_path: Path) -> list[dict]:
        """Run full diarization on a WAV file.

        Returns a list of ``{start, end, speaker}`` dicts.
        """
        try:
            import torch
            import torchaudio  # type: ignore
            from sklearn.cluster import KMeans  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "torchaudio and scikit-learn are required for diarization.\n"
                "Install: pip install torchaudio scikit-learn>=1.3.0\n"
                f"Original: {exc}"
            ) from exc

        self._ensure_model()

        # Load audio
        waveform, sr = torchaudio.load(str(audio_path))
        if sr != 16000:
            resampler = torchaudio.transforms.Resample(orig_freq=sr, new_freq=16000)
            waveform = resampler(waveform)
            sr = 16000

        total_samples = waveform.shape[1]
        total_seconds = total_samples / sr

        window_sec = 2.0
        hop_sec = 1.0
        window_samples = int(window_sec * sr)
        hop_samples = int(hop_sec * sr)

        embeddings = []
        window_starts: list[float] = []

        start = 0
        while start + window_samples <= total_samples:
            chunk = waveform[:, start : start + window_samples]
            with torch.no_grad():
                emb = self._encoder.encode_batch(chunk)  # (1, 1, 192)
            embeddings.append(emb.squeeze().cpu().numpy())
            window_starts.append(start / sr)
            start += hop_samples

        if not embeddings:
            logger.warning("Audio too short for diarization (< %.1fs)", window_sec)
            return [{"start": 0.0, "end": total_seconds, "speaker": "SPEAKER_00"}]

        import numpy as np

        emb_matrix = np.stack(embeddings)  # (N, 192)

        n_clusters = min(self.num_speakers, len(embeddings))
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init="auto")
        labels = kmeans.fit_predict(emb_matrix)

        # Map cluster indices to SPEAKER_XX labels (sorted by first appearance)
        cluster_order: list[int] = []
        for lbl in labels:
            if lbl not in cluster_order:
                cluster_order.append(int(lbl))
        cluster_to_speaker = {c: f"SPEAKER_{i:02d}" for i, c in enumerate(cluster_order)}

        raw: list[dict] = []
        for start_t, lbl in zip(window_starts, labels):
            raw.append(
                {
                    "start": round(start_t, 3),
                    "end": round(start_t + window_sec, 3),
                    "speaker": cluster_to_speaker[int(lbl)],
                }
            )

        segments = _merge_segments(raw)
        if segments:
            segments[-1]["end"] = min(segments[-1]["end"], round(total_seconds, 3))

        return segments

    # ------------------------------------------------------------------
    # Sample extraction
    # ------------------------------------------------------------------

    def extract_samples(
        self,
        audio_path: Path,
        segments: list[dict],
        output_dir: Path,
        sample_duration: float = 7.0,
    ) -> dict[str, Path]:
        """Extract a clean audio sample for each speaker (longest single-speaker run)."""
        output_dir.mkdir(parents=True, exist_ok=True)

        speakers = sorted({s["speaker"] for s in segments})
        result: dict[str, Path] = {}

        for speaker in speakers:
            best_seg = _best_segment_for_speaker(segments, speaker, sample_duration)
            if best_seg is None:
                logger.warning("No clean segment found for %s", speaker)
                continue

            start_t = best_seg["start"]
            end_t = best_seg["end"]
            duration = end_t - start_t

            if duration > sample_duration:
                mid = (start_t + end_t) / 2
                start_t = max(0.0, mid - sample_duration / 2)
                end_t = start_t + sample_duration

            tag = speaker.lower()
            out_wav = output_dir / f"{tag}_sample.wav"

            cmd = [
                "ffmpeg",
                "-y",
                "-i", str(audio_path),
                "-ss", str(start_t),
                "-t", str(end_t - start_t),
                "-ac", "1",
                "-ar", "16000",
                "-f", "wav",
                str(out_wav),
            ]
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            )
            if proc.returncode != 0:
                logger.error(
                    "ffmpeg sample extraction failed for %s: %s",
                    speaker,
                    proc.stderr.decode(errors="replace"),
                )
                continue

            result[speaker] = out_wav
            logger.info("Saved sample for %s → %s", speaker, out_wav)

        return result

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------

    def run(self, video_path: Path, output_dir: Path) -> dict:
        """Full pipeline: extract audio → diarize → extract per-speaker samples.

        Returns a dict with ``segments``, ``samples`` (Path) and
        ``samples_map`` (just filenames, JSON-serializable).
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="azelia_speaker_") as tmpdir:
            wav_path = Path(tmpdir) / "audio.wav"
            logger.info("Extracting audio from %s …", video_path)
            self._extract_audio(video_path, wav_path)

            logger.info("Running diarization …")
            segments = self.diarize(wav_path)
            logger.info(
                "Found %d segments across %d speaker(s)",
                len(segments),
                len({s["speaker"] for s in segments}),
            )

            logger.info("Extracting speaker samples …")
            samples = self.extract_samples(wav_path, segments, output_dir)

        samples_map = {spk: path.name for spk, path in samples.items()}

        return {
            "segments": segments,
            "samples": samples,
            "samples_map": samples_map,
        }


# ------------------------------------------------------------------
# Helpers (module-level, not methods)
# ------------------------------------------------------------------


def _merge_segments(raw: list[dict]) -> list[dict]:
    """Merge consecutive windows with the same speaker into longer segments."""
    if not raw:
        return []

    merged: list[dict] = []
    current = dict(raw[0])

    for seg in raw[1:]:
        if seg["speaker"] == current["speaker"]:
            current["end"] = seg["end"]
        else:
            merged.append(current)
            current = dict(seg)

    merged.append(current)
    return merged


def _best_segment_for_speaker(
    segments: list[dict],
    speaker: str,
    min_duration: float,
) -> Optional[dict]:
    """Return the longest contiguous run belonging to *speaker*.

    Falls back to the longest segment if no run meets *min_duration*.
    """
    runs: list[dict] = []
    in_run: Optional[dict] = None

    for seg in segments:
        if seg["speaker"] == speaker:
            if in_run is None:
                in_run = {"start": seg["start"], "end": seg["end"]}
            else:
                in_run["end"] = seg["end"]
        else:
            if in_run is not None:
                runs.append(in_run)
                in_run = None

    if in_run is not None:
        runs.append(in_run)

    if not runs:
        return None

    runs.sort(key=lambda r: r["end"] - r["start"], reverse=True)
    return runs[0]
