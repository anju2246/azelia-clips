"""Structural signal extraction for clip curation."""

from dataclasses import dataclass

from src.asr.transcriber import Transcript


@dataclass
class StructuralSignals:
    """Extracted structural signals for a segment."""
    # Completeness
    has_clear_start: bool = False
    has_clear_end: bool = False
    segment_completeness: float = 0.0
    
    # Context
    requires_prior_context: bool = True
    is_self_contained: bool = False
    
    # Duration
    duration_seconds: float = 0.0
    is_optimal_duration: bool = False
    
    # Speaker
    single_speaker: bool = True
    speaker_changes: int = 0
    
    # Scores (0-10)
    completeness_score: int = 0
    standalone_score: int = 0
    duration_score: int = 0


class StructuralAnalyzer:
    """
    Analyze structural characteristics of transcript segments.
    Evaluates completeness, context independence, and duration.
    """
    
    # Duration thresholds (seconds)
    MIN_OPTIMAL_DURATION = 25
    MAX_OPTIMAL_DURATION = 90
    IDEAL_DURATION = 45
    
    # Sentence starters that indicate beginning of thought
    START_INDICATORS = [
        'entonces', 'so', 'bueno', 'well', 'mira', 'look',
        'yo creo', 'i think', 'la cosa es', 'the thing is',
        'déjame', 'let me', 'hay algo', 'there\'s something',
        'para mí', 'for me', 'lo que pasa', 'what happens',
    ]
    
    # Sentence endings that indicate conclusion
    END_INDICATORS = [
        'eso es', 'that\'s it', 'punto', 'period',
        'y ya', 'and that\'s it', 'así de simple', 'simple as that',
        'definitivamente', 'definitely', 'sin duda', 'no doubt',
        'al final', 'in the end', 'la conclusión', 'the conclusion',
    ]
    
    # Context-dependent words (require prior context)
    CONTEXT_DEPENDENT = [
        'esto', 'this', 'eso', 'that', 'él', 'he', 'ella', 'she',
        'como decía', 'as i was saying', 'lo que mencioné', 'what i mentioned',
        'anteriormente', 'previously', 'antes', 'before',
    ]
    
    def __init__(
        self,
        min_duration: int = 25,
        max_duration: int = 90,
    ):
        self.min_duration = min_duration
        self.max_duration = max_duration
    
    def analyze_segment(
        self,
        transcript: Transcript,
        start_time: float,
        end_time: float,
    ) -> StructuralSignals:
        """
        Analyze structural characteristics of a segment.
        
        Args:
            transcript: Full transcript
            start_time: Segment start
            end_time: Segment end
            
        Returns:
            StructuralSignals with completeness and context metrics
        """
        signals = StructuralSignals()
        signals.duration_seconds = end_time - start_time
        
        # Get segments in range
        segments_in_range = [
            seg for seg in transcript.segments
            if seg.end > start_time and seg.start < end_time
        ]
        
        if not segments_in_range:
            return signals
        
        # Combine text
        full_text = ' '.join(seg.text for seg in segments_in_range).lower()
        first_text = segments_in_range[0].text.lower()
        last_text = segments_in_range[-1].text.lower()
        
        # 1. Check for clear start
        for indicator in self.START_INDICATORS:
            if first_text.startswith(indicator) or f' {indicator}' in first_text[:50]:
                signals.has_clear_start = True
                break
        
        # Sentence starting with capital (proper beginning) after punctuation gap
        if segments_in_range[0].text[0].isupper():
            signals.has_clear_start = True
        
        # 2. Check for clear end
        for indicator in self.END_INDICATORS:
            if indicator in last_text:
                signals.has_clear_end = True
                break
        
        # Ends with period/exclamation (complete thought)
        if last_text.rstrip().endswith(('.', '!', '?')):
            signals.has_clear_end = True
        
        # 3. Context dependence
        context_words_count = sum(
            1 for word in self.CONTEXT_DEPENDENT
            if word in full_text[:100]  # Check beginning
        )
        
        signals.requires_prior_context = context_words_count >= 2
        signals.is_self_contained = context_words_count == 0 and signals.has_clear_start
        
        # 4. Speaker analysis
        speakers = set(seg.speaker for seg in segments_in_range if seg.speaker)
        signals.single_speaker = len(speakers) <= 1
        
        # Count speaker changes
        if len(segments_in_range) > 1:
            changes = sum(
                1 for i in range(1, len(segments_in_range))
                if segments_in_range[i].speaker != segments_in_range[i-1].speaker
            )
            signals.speaker_changes = changes
        
        # 5. Duration check
        signals.is_optimal_duration = (
            self.min_duration <= signals.duration_seconds <= self.max_duration
        )
        
        # 6. Calculate scores
        signals.completeness_score = self._calculate_completeness_score(signals)
        signals.standalone_score = self._calculate_standalone_score(signals)
        signals.duration_score = self._calculate_duration_score(signals)
        
        return signals
    
    def _calculate_completeness_score(self, signals: StructuralSignals) -> int:
        """Calculate segment completeness (0-10)."""
        score = 3  # Baseline
        
        if signals.has_clear_start:
            score += 3
        
        if signals.has_clear_end:
            score += 3
        
        # Bonus for single speaker (coherent narrative)
        if signals.single_speaker:
            score += 1
        
        return min(10, score)
    
    def _calculate_standalone_score(self, signals: StructuralSignals) -> int:
        """Calculate context independence (0-10)."""
        score = 5  # Baseline
        
        if signals.is_self_contained:
            score += 4
        elif not signals.requires_prior_context:
            score += 2
        else:
            score -= 2
        
        if signals.has_clear_start:
            score += 1
        
        return max(0, min(10, score))
    
    def _calculate_duration_score(self, signals: StructuralSignals) -> int:
        """Calculate optimal duration score (0-10)."""
        duration = signals.duration_seconds
        
        if duration < self.min_duration:
            # Too short
            return max(0, int(10 * duration / self.min_duration))
        elif duration > self.max_duration:
            # Too long
            overage = duration - self.max_duration
            return max(0, 10 - int(overage / 10))
        else:
            # In range - closer to ideal is better
            distance_from_ideal = abs(duration - self.IDEAL_DURATION)
            if distance_from_ideal < 10:
                return 10
            elif distance_from_ideal < 20:
                return 8
            else:
                return 6
    
    def find_complete_segments(
        self,
        transcript: Transcript,
        min_score: int = 20,
    ) -> list[tuple[float, float, StructuralSignals]]:
        """
        Find segments with good structural properties.
        
        Args:
            transcript: Transcript to analyze
            min_score: Minimum combined structural score
            
        Returns:
            List of (start, end, signals) tuples
        """
        candidates = []
        
        if not transcript.segments:
            return candidates
        
        # Try different window sizes
        for window in [30, 45, 60, 75]:
            start = transcript.segments[0].start
            end_transcript = transcript.segments[-1].end
            step = window / 3
            
            while start < end_transcript:
                end = min(start + window, end_transcript)
                signals = self.analyze_segment(transcript, start, end)
                
                total = (
                    signals.completeness_score +
                    signals.standalone_score +
                    signals.duration_score
                )
                
                if total >= min_score:
                    candidates.append((start, end, signals))
                
                start += step
        
        # Deduplicate overlapping candidates
        filtered = []
        candidates.sort(key=lambda x: -(x[2].completeness_score + x[2].standalone_score))
        
        for start, end, signals in candidates:
            overlaps = any(
                abs(s - start) < 10 or abs(e - end) < 10
                for s, e, _ in filtered
            )
            if not overlaps:
                filtered.append((start, end, signals))
        
        return filtered
