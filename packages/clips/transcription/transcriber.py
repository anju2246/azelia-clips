import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

@dataclass
class Word:
    word: str
    start: float
    end: float
    score: float = 1.0

@dataclass
class Segment:
    text: str
    start: float
    end: float
    speaker: Optional[str] = None
    words: List[Word] = field(default_factory=list)

@dataclass
class Transcript:
    segments: List[Segment]
    language: str = "es"
    duration: float = 0.0
    source_file: str = ""
    
    def slice(self, start: float, end: float) -> "Transcript":
        """
        Extract a sub-transcript between start and end times.
        
        Filters segments that overlap with [start, end] and adjusts
        timestamps so the slice starts at t=0.
        
        Args:
            start: Start time in seconds.
            end: End time in seconds.
            
        Returns:
            New Transcript with adjusted segments.
        """
        sliced_segments = []
        for seg in self.segments:
            # Keep segments that overlap with the [start, end] window
            if seg.end <= start or seg.start >= end:
                continue
            
            # Clamp and adjust timestamps relative to slice start
            new_start = max(0.0, seg.start - start)
            new_end = min(end - start, seg.end - start)
            
            # Adjust word timestamps too
            new_words = []
            for w in seg.words:
                if w.end <= start or w.start >= end:
                    continue
                new_words.append(Word(
                    word=w.word,
                    start=max(0.0, w.start - start),
                    end=min(end - start, w.end - start),
                    score=w.score,
                ))
            
            sliced_segments.append(Segment(
                text=seg.text,
                start=new_start,
                end=new_end,
                speaker=seg.speaker,
                words=new_words,
            ))
        
        return Transcript(
            segments=sliced_segments,
            language=self.language,
            duration=end - start,
            source_file=self.source_file,
        )
    
    @property
    def full_text(self) -> str:
        """Concatenate all segment texts."""
        return " ".join(seg.text for seg in self.segments)

    def save(self, path: Path) -> None:
        """Save transcript to a JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: Path) -> "Transcript":
        """Load transcript from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        segments = [
            Segment(
                text=s["text"],
                start=s["start"],
                end=s["end"],
                speaker=s.get("speaker"),
                words=[Word(**w) for w in s.get("words", [])],
            )
            for s in data.get("segments", [])
        ]
        return cls(
            segments=segments,
            language=data.get("language", "es"),
            duration=data.get("duration", 0.0),
            source_file=data.get("source_file", ""),
        )
