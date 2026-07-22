"""
Domain models for the conversational brief pre-processing feature.
"""
from typing import List, Optional

from pydantic import BaseModel

# The conversational agent (T3) emits these action types; the applier (T2)
# executes them deterministically over the candidate selection.
ACTION_TYPES = (
    "drop",
    "rescue",
    "reorder",
    "adjust_times",
    "trim_to_text",
    "find_new",
    "noop",
)


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
    transcript: str = ""  # clip transcript text (for the expandable review card)
    # Editable text shown on-screen for the first N seconds (the "hook title").
    # Initialized to the clip title in build_session; the user may override it in
    # the brief. Only surfaced when the job's template has intro_title enabled.
    hook_text: str = ""


class ChatMessage(BaseModel):
    """A message in the conversational brief session."""
    role: str
    content: str
    change_summary: Optional[str] = None
    clip_id: Optional[int] = None  # which candidate this message refers to (one-by-one flow)


class BriefAction(BaseModel):
    """A single instruction the LLM proposes; the backend applies it.

    One flat model keyed by ``type`` (rather than a class per action) so the
    LLM's JSON maps cleanly and unknown/extra fields are ignored.
    """
    type: str  # one of ACTION_TYPES
    # drop / rescue
    targets: List[int] = []
    # reorder
    order: Optional[List[int]] = None
    by: Optional[str] = None  # "score" | "controversy" | ...
    # adjust_times
    id: Optional[int] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    # trim_to_text
    keep_text: Optional[str] = None
    # find_new
    window_start: Optional[float] = None
    window_end: Optional[float] = None
    hint: Optional[str] = None
    # noop
    reason: Optional[str] = None


class ChangeResult(BaseModel):
    """Outcome of applying one action to a session."""
    ok: bool
    change_summary: str


class BriefSession(BaseModel):
    """A complete brief session state."""
    job_id: str
    episode_id: str
    status: str  # "open" | "approved" | "cancelled"
    candidates: List[BriefCandidate]
    messages: List[ChatMessage]
    created_at: str
    updated_at: str
    # Whether the job's template renders a hook title (intro_title.enabled). When
    # True the UI surfaces the editable hook field per candidate; False → hidden.
    hook_enabled: bool = False
    hook_duration_s: float = 0.0  # informative: "first Ns" label in the UI

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dict for persistence."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, d: dict) -> "BriefSession":
        """Rebuild a session from its persisted dict form."""
        return cls.model_validate(d)
