"""Audio signal extraction for clip curation."""

import numpy as np
from dataclasses import dataclass
from pathlib import Path

from src.asr.transcriber import Transcript


@dataclass
class AudioSignals:
    """Extracted audio signals for a segment."""
    # Energy metrics
    mean_energy: float = 0.0
    peak_energy: float = 0.0
    energy_variance: float = 0.0
    
    # Pacing metrics (from transcript)
    words_per_second: float = 0.0
    has_dramatic_pause: bool = False
    pause_count: int = 0
    
    # Scores (0-10)
    energy_score: int = 0
    pacing_score: int = 0
    emotional_arc_score: int = 0


class AudioAnalyzer:
    """
    Analyze audio characteristics from transcript timing data.
    Uses transcript timestamps to derive pacing and pause information.
    Optional: Can analyze audio file directly if librosa is available.
    """
    
    # Thresholds
    DRAMATIC_PAUSE_THRESHOLD = 1.5  # seconds
    OPTIMAL_WPS_MIN = 2.0  # words per second
    OPTIMAL_WPS_MAX = 4.0  # words per second
    
    def __init__(self, use_audio_file: bool = False):
        """
        Initialize audio analyzer.
        
        Args:
            use_audio_file: If True, attempt to load librosa for audio analysis
        """
        self.use_audio_file = use_audio_file
        self.librosa = None
        
        if use_audio_file:
            try:
                import librosa
                self.librosa = librosa
            except ImportError:
                print("[AudioAnalyzer] librosa not available, using transcript-only analysis")
                self.use_audio_file = False
    
    def analyze_from_transcript(
        self,
        transcript: Transcript,
        start_time: float,
        end_time: float,
    ) -> AudioSignals:
        """
        Analyze audio characteristics from transcript timing.
        Derives pacing and pause information from word timestamps.
        
        Args:
            transcript: Transcript with word-level timestamps
            start_time: Start of segment to analyze
            end_time: End of segment to analyze
            
        Returns:
            AudioSignals with pacing metrics
        """
        signals = AudioSignals()
        
        # Collect words in time range
        words_in_range = []
        for seg in transcript.segments:
            if seg.end < start_time or seg.start > end_time:
                continue
            for word in seg.words:
                if start_time <= word.start <= end_time:
                    words_in_range.append(word)
        
        if not words_in_range:
            return signals
        
        # Calculate words per second
        duration = end_time - start_time
        if duration > 0:
            signals.words_per_second = len(words_in_range) / duration
        
        # Detect pauses between words
        pauses = []
        for i in range(1, len(words_in_range)):
            gap = words_in_range[i].start - words_in_range[i-1].end
            if gap > 0.3:  # Minimum pause threshold
                pauses.append(gap)
                if gap >= self.DRAMATIC_PAUSE_THRESHOLD:
                    signals.has_dramatic_pause = True
        
        signals.pause_count = len(pauses)
        
        # Calculate scores
        signals.pacing_score = self._calculate_pacing_score(signals)
        signals.energy_score = self._estimate_energy_from_pacing(signals)
        signals.emotional_arc_score = self._calculate_emotional_arc(signals, pauses)
        
        return signals
    
    def analyze_from_audio_file(
        self,
        audio_path: Path,
        start_time: float,
        end_time: float,
    ) -> AudioSignals:
        """
        Analyze audio directly from file using librosa.
        
        Args:
            audio_path: Path to audio file
            start_time: Start of segment
            end_time: End of segment
            
        Returns:
            AudioSignals with energy metrics
        """
        if not self.librosa:
            return AudioSignals()
        
        signals = AudioSignals()
        
        try:
            # Load audio segment
            duration = end_time - start_time
            y, sr = self.librosa.load(
                str(audio_path),
                offset=start_time,
                duration=duration,
                sr=22050
            )
            
            # Calculate RMS energy
            rms = self.librosa.feature.rms(y=y)[0]
            signals.mean_energy = float(np.mean(rms))
            signals.peak_energy = float(np.max(rms))
            signals.energy_variance = float(np.var(rms))
            
            # Calculate energy score based on variance and peaks
            signals.energy_score = self._calculate_energy_score(rms)
            signals.emotional_arc_score = self._calculate_arc_from_rms(rms)
            
        except Exception as e:
            print(f"[AudioAnalyzer] Error analyzing audio: {e}")
        
        return signals
    
    def _calculate_pacing_score(self, signals: AudioSignals) -> int:
        """Calculate pacing score (0-10)."""
        wps = signals.words_per_second
        
        # Optimal pacing is 2-4 WPS
        if self.OPTIMAL_WPS_MIN <= wps <= self.OPTIMAL_WPS_MAX:
            score = 8
        elif wps < self.OPTIMAL_WPS_MIN:
            # Too slow
            score = max(0, int(5 * wps / self.OPTIMAL_WPS_MIN))
        else:
            # Too fast
            score = max(0, int(8 - (wps - self.OPTIMAL_WPS_MAX) * 2))
        
        # Bonus for dramatic pauses (indicates intentional emphasis)
        if signals.has_dramatic_pause:
            score += 2
        
        return min(10, score)
    
    def _estimate_energy_from_pacing(self, signals: AudioSignals) -> int:
        """Estimate energy when no audio analysis available."""
        # Higher WPS often correlates with higher energy
        wps = signals.words_per_second
        
        if wps >= 3.5:
            score = 8
        elif wps >= 2.5:
            score = 6
        elif wps >= 1.5:
            score = 4
        else:
            score = 2
        
        # Pauses can indicate emotional emphasis
        if signals.has_dramatic_pause:
            score += 1
        
        return min(10, score)
    
    def _calculate_emotional_arc(self, signals: AudioSignals, pauses: list[float]) -> int:
        """Calculate emotional arc score from pacing variation."""
        score = 5  # Baseline
        
        # Dramatic pauses indicate emotional moments
        if signals.has_dramatic_pause:
            score += 3
        
        # Multiple pauses indicate varied delivery
        if len(pauses) >= 3:
            score += 2
        
        return min(10, score)
    
    def _calculate_energy_score(self, rms: np.ndarray) -> int:
        """Calculate energy score from RMS array."""
        mean_rms = np.mean(rms)
        
        # Normalize to 0-10 scale (assuming typical podcast RMS range)
        # These thresholds may need calibration
        if mean_rms > 0.1:
            return 10
        elif mean_rms > 0.05:
            return 8
        elif mean_rms > 0.02:
            return 6
        elif mean_rms > 0.01:
            return 4
        else:
            return 2
    
    def _calculate_arc_from_rms(self, rms: np.ndarray) -> int:
        """Calculate emotional arc from energy variation."""
        if len(rms) < 10:
            return 5
        
        # Split into thirds
        third = len(rms) // 3
        start = np.mean(rms[:third])
        middle = np.mean(rms[third:2*third])
        end = np.mean(rms[2*third:])
        
        # Check for arc patterns
        # Rise: start < middle > end (classic story arc)
        # Build: start < middle < end (building tension)
        # Peak: middle is highest
        
        score = 5
        
        # Variance indicates dynamic delivery
        variance = np.var([start, middle, end])
        if variance > 0.001:
            score += 3
        
        # Peak in middle is engaging
        if middle > start and middle > end:
            score += 2
        
        return min(10, score)
    
    def analyze_transcript_segments(
        self,
        transcript: Transcript,
        window_seconds: float = 45.0,
    ) -> list[tuple[float, float, AudioSignals]]:
        """
        Analyze all segments in sliding windows.
        
        Args:
            transcript: Transcript to analyze
            window_seconds: Length of analysis window
            
        Returns:
            List of (start, end, signals) tuples
        """
        results = []
        
        if not transcript.segments:
            return results
        
        # Slide through transcript
        start = transcript.segments[0].start
        end_transcript = transcript.segments[-1].end
        
        step = window_seconds / 2  # 50% overlap
        
        while start < end_transcript:
            end = min(start + window_seconds, end_transcript)
            signals = self.analyze_from_transcript(transcript, start, end)
            results.append((start, end, signals))
            start += step
        
        return results
