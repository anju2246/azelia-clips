from dataclasses import dataclass, field
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
