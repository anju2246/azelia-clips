"""
Domain models for the conversational brief pre-processing feature.
STUB - Implementation pending.
"""
from typing import List, Optional
from pydantic import BaseModel


class BriefCandidate(BaseModel):
    """A clip candidate in the brief session."""
    id: int  # 1-based
    start_time: float
    end_time: float
    title: str
    summary: str
    reasoning: str = ""
    score: float
    critic_approved: bool
    above_threshold: bool
    selected: bool
    origin: str  # "curation" | "rescued" | "found"


class ChatMessage(BaseModel):
    """A message in the conversational brief session."""
    role: str
    content: str
    change_summary: Optional[str] = None


class BriefSession(BaseModel):
    """A complete brief session state."""
    job_id: str
    episode_id: str
    status: str  # "open" | "approved" | "cancelled"
    candidates: List[BriefCandidate]
    messages: List[ChatMessage]
    created_at: str
    updated_at: str

    def to_dict(self):
        """Convert to dict for persistence."""
        raise NotImplementedError("to_dict not implemented")

    @classmethod
    def from_dict(cls, d: dict):
        """Load from dict."""
        raise NotImplementedError("from_dict not implemented")
