"""Pydantic models for the API.

Local-first MVP. Restricted to Anthropic + Claude Code providers.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    PAUSED = "paused"
    RESUMING = "resuming"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


class Clip(BaseModel):
    id: int
    filename: str
    start_time: float
    end_time: float
    duration: float
    virality_score: float
    title: str
    summary: str
    status: str  # approved, review
    download_url: Optional[str] = None
    thumbnail_url: Optional[str] = None


class JobResponse(BaseModel):
    id: str
    status: JobStatus
    filename: str
    created_at: datetime
    progress: int = 0
    message: str = ""
    clips: List[Clip] = []
    error: Optional[str] = None


class ProcessRequest(BaseModel):
    min_duration: int = 30
    max_duration: int = 90
    min_score: int = 70
    subtitle_style: str = "highlight"
    transcription_source: str = "local_whisper"
    # Optional: user-owned Supabase for transcript ingestion (not Azelia's)
    supabase_url: Optional[str] = None
    supabase_key: Optional[str] = None
    assemblyai_key: Optional[str] = None
    # Re-process from scratch: wipe curation.json + existing clips/{approved,review}
    # so the pipeline doesn't short-circuit on cached files.
    force_reset: bool = False


class ProcessLocalRequest(ProcessRequest):
    video_path: str


class SettingsResponse(BaseModel):
    podcast_name: Optional[str] = Field(default="")
    podcast_dir: Optional[str] = Field(default="")
    ai_provider_order: List[str] = Field(default=["claude_code", "anthropic"])
    anthropic_api_key: str = Field(default="", description="Masked key")
    anthropic_model: str = Field(default="claude-sonnet-4-6")
    # User-owned Supabase for transcripts (optional)
    transcript_supabase_url: str = Field(default="")
    transcript_supabase_key: str = Field(default="", description="Masked key")


class UpdateSettingsRequest(BaseModel):
    podcast_name: Optional[str] = None
    podcast_dir: Optional[str] = None
    ai_provider_order: Optional[List[str]] = None
    anthropic_api_key: Optional[str] = None
    anthropic_model: Optional[str] = None
    transcript_supabase_url: Optional[str] = None
    transcript_supabase_key: Optional[str] = None


class EpisodeResponse(BaseModel):
    id: str
    number: int
    title: str
    has_video: bool
    has_transcript: bool
    is_processed: bool
    path: str
    # Job state surfaced to the UI so the library card can show
    # "Procesando" / "Pausado" instead of falsely claiming "Done"
    # just because a half-rendered clips/ folder exists on disk.
    job_status: str | None = None  # None | processing | paused | completed | failed | cancelled
    job_progress: int | None = None
