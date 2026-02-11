"""Text signal extraction for clip curation."""

import re
from dataclasses import dataclass, field

from src.asr.transcriber import Transcript


@dataclass
class TextSignals:
    """Extracted text signals for a segment."""
    # Hook indicators
    has_question: bool = False
    has_controversial_phrase: bool = False
    has_storytelling_pattern: bool = False
    
    # Quotability
    has_short_punchy_statement: bool = False
    has_emotional_keywords: bool = False
    
    # Scores (0-10)
    hook_score: int = 0
    quotability_score: int = 0
    storytelling_score: int = 0
    controversy_score: int = 0
    
    # Details
    detected_patterns: list = field(default_factory=list)


class TextAnalyzer:
    """
    Analyze transcript text to extract engagement signals.
    All analysis is done locally without external APIs.
    """
    
    # Spanish + English patterns
    STORYTELLING_PATTERNS = [
        r'\b(hace|when|cuando)\s+\d+\s+(años|meses|días|years|months|days)\b',
        r'\b(un día|one day|once upon)\b',
        r'\b(recuerdo|remember|i remember)\b',
        r'\b(me pasó|happened to me|sucedió)\b',
        r'\b(mi primer|my first)\b',
        r'\b(la historia|the story|te cuento)\b',
    ]
    
    CONTROVERSIAL_PATTERNS = [
        r'\b(nadie te dice|nobody tells you)\b',
        r'\b(la verdad es|the truth is)\b',
        r'\b(lo que no sabes|what you don\'t know)\b',
        r'\b(el problema es|the problem is)\b',
        r'\b(no estoy de acuerdo|i disagree)\b',
        r'\b(esto es mentira|this is a lie|bullshit)\b',
        r'\b(controversial|polémico)\b',
        r'\b(secreto|secret)\b',
        r'\b(nunca|never)\s+.{0,20}\b(deberías|should)',
    ]
    
    HOOK_PATTERNS = [
        r'^(¿|como|cómo|why|por qué|what if|qué pasaría)',  # Questions
        r'\b(increíble|incredible|amazing|sorprendente)\b',
        r'\b(esto cambió|this changed|game changer)\b',
        r'\b(número \d|number \d|\d cosas|\d things)\b',  # Numbered lists
        r'\b(el error más|the biggest mistake)\b',
    ]
    
    EMOTIONAL_KEYWORDS = {
        # Spanish
        'increíble', 'horrible', 'terrible', 'maravilloso', 'perfecto',
        'odio', 'amo', 'miedo', 'terror', 'alegría', 'tristeza',
        'furioso', 'emocionado', 'asombrado', 'frustrado', 'feliz',
        # English  
        'incredible', 'horrible', 'terrible', 'amazing', 'perfect',
        'hate', 'love', 'fear', 'terror', 'joy', 'sad',
        'angry', 'excited', 'amazed', 'frustrated', 'happy',
    }
    
    def __init__(self):
        # Compile patterns for efficiency
        self.storytelling_re = [re.compile(p, re.IGNORECASE) for p in self.STORYTELLING_PATTERNS]
        self.controversial_re = [re.compile(p, re.IGNORECASE) for p in self.CONTROVERSIAL_PATTERNS]
        self.hook_re = [re.compile(p, re.IGNORECASE) for p in self.HOOK_PATTERNS]
    
    def analyze_segment(self, text: str) -> TextSignals:
        """
        Analyze a text segment and extract engagement signals.
        
        Args:
            text: The text content to analyze
            
        Returns:
            TextSignals with detected patterns and scores
        """
        signals = TextSignals()
        text_lower = text.lower()
        words = text_lower.split()
        
        # 1. Detect patterns
        # Storytelling
        for pattern in self.storytelling_re:
            if pattern.search(text_lower):
                signals.has_storytelling_pattern = True
                signals.detected_patterns.append(f"storytelling: {pattern.pattern}")
                break
        
        # Controversy
        for pattern in self.controversial_re:
            if pattern.search(text_lower):
                signals.has_controversial_phrase = True
                signals.detected_patterns.append(f"controversy: {pattern.pattern}")
                break
        
        # Hooks
        for pattern in self.hook_re:
            if pattern.search(text_lower):
                signals.detected_patterns.append(f"hook: {pattern.pattern}")
        
        # Questions
        if '?' in text or text_lower.startswith(('¿', 'cómo', 'como', 'por qué', 'why', 'what', 'how')):
            signals.has_question = True
            signals.detected_patterns.append("question")
        
        # Emotional keywords
        emotional_count = sum(1 for word in words if word.strip('.,!?') in self.EMOTIONAL_KEYWORDS)
        if emotional_count > 0:
            signals.has_emotional_keywords = True
            signals.detected_patterns.append(f"emotional_keywords: {emotional_count}")
        
        # Short punchy statement (quotable)
        sentences = re.split(r'[.!?]', text)
        for sentence in sentences:
            word_count = len(sentence.split())
            if 3 <= word_count <= 12 and any(w in sentence.lower() for w in ['nunca', 'siempre', 'never', 'always', 'todo', 'everything']):
                signals.has_short_punchy_statement = True
                signals.detected_patterns.append(f"quotable: {sentence.strip()[:50]}")
                break
        
        # 2. Calculate scores (0-10)
        signals.hook_score = self._calculate_hook_score(signals, text)
        signals.quotability_score = self._calculate_quotability_score(signals, text)
        signals.storytelling_score = self._calculate_storytelling_score(signals, text)
        signals.controversy_score = self._calculate_controversy_score(signals, text)
        
        return signals
    
    def _calculate_hook_score(self, signals: TextSignals, text: str) -> int:
        """Calculate hook strength (0-10)."""
        score = 0
        
        # Questions are good hooks
        if signals.has_question:
            score += 3
        
        # Controversial statements hook attention
        if signals.has_controversial_phrase:
            score += 3
        
        # Pattern matches
        hook_patterns_found = sum(1 for p in signals.detected_patterns if 'hook' in p)
        score += min(4, hook_patterns_found * 2)
        
        return min(10, score)
    
    def _calculate_quotability_score(self, signals: TextSignals, text: str) -> int:
        """Calculate quotability (0-10)."""
        score = 0
        
        if signals.has_short_punchy_statement:
            score += 5
        
        if signals.has_emotional_keywords:
            score += 3
        
        # Shorter segments are often more quotable
        word_count = len(text.split())
        if 20 <= word_count <= 50:
            score += 2
        
        return min(10, score)
    
    def _calculate_storytelling_score(self, signals: TextSignals, text: str) -> int:
        """Calculate storytelling pattern strength (0-10)."""
        score = 0
        
        if signals.has_storytelling_pattern:
            score += 6
        
        # Personal pronouns indicate personal stories
        personal_pronouns = ['yo', 'me', 'mi', 'i', 'my', 'we', 'nosotros']
        text_lower = text.lower()
        pronoun_count = sum(text_lower.count(f' {p} ') for p in personal_pronouns)
        score += min(4, pronoun_count)
        
        return min(10, score)
    
    def _calculate_controversy_score(self, signals: TextSignals, text: str) -> int:
        """Calculate controversy potential (0-10)."""
        score = 0
        
        if signals.has_controversial_phrase:
            score += 7
        
        # Strong language
        if signals.has_emotional_keywords:
            score += 2
        
        # Negations often indicate disagreement
        negations = ['no', 'nunca', 'jamás', 'never', 'not', 'don\'t']
        negation_count = sum(text.lower().count(f' {n} ') for n in negations)
        score += min(3, negation_count)
        
        return min(10, score)
    
    def analyze_transcript(self, transcript: Transcript) -> dict[float, TextSignals]:
        """
        Analyze all segments in a transcript.
        
        Args:
            transcript: Transcript object with segments
            
        Returns:
            Dictionary mapping segment start time to TextSignals
        """
        results = {}
        for seg in transcript.segments:
            signals = self.analyze_segment(seg.text)
            results[seg.start] = signals
        return results
    
    def find_high_signal_windows(
        self,
        transcript: Transcript,
        window_seconds: float = 45.0,
        min_score: int = 15,
    ) -> list[tuple[float, float, TextSignals]]:
        """
        Find time windows with high text signal scores.
        
        Args:
            transcript: Transcript to analyze
            window_seconds: Length of sliding window
            min_score: Minimum combined score to consider
            
        Returns:
            List of (start, end, combined_signals) tuples
        """
        segment_signals = self.analyze_transcript(transcript)
        
        candidates = []
        segments = transcript.segments
        
        for i, start_seg in enumerate(segments):
            # Find segments within window
            window_end = start_seg.start + window_seconds
            window_segments = [s for s in segments if start_seg.start <= s.start < window_end]
            
            if not window_segments:
                continue
            
            # Combine signals for window
            combined_text = ' '.join(s.text for s in window_segments)
            combined_signals = self.analyze_segment(combined_text)
            
            total_score = (
                combined_signals.hook_score +
                combined_signals.quotability_score +
                combined_signals.storytelling_score +
                combined_signals.controversy_score
            )
            
            if total_score >= min_score:
                actual_end = window_segments[-1].end
                candidates.append((start_seg.start, actual_end, combined_signals))
        
        # Remove overlapping windows, keep highest scoring
        filtered = []
        for start, end, signals in sorted(candidates, key=lambda x: -(x[2].hook_score + x[2].quotability_score)):
            # Check if overlaps with existing
            overlaps = any(
                (s <= start < e) or (s < end <= e) or (start <= s and end >= e)
                for s, e, _ in filtered
            )
            if not overlaps:
                filtered.append((start, end, signals))
        
        return filtered
