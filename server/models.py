"""Pydantic models for the API.

Local-first MVP. Restricted to Anthropic + Claude Code providers.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from packages.clips.templates.models import (
    ClipTemplate,
    IntroTitleSpec,
    LayoutSpec,
    SubtitleSpec,
)


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    AWAITING_BRIEF = "awaiting_brief"
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
    template_id: Optional[str] = None  # Clip template to apply (None = profile default)
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
    review_brief_before_processing: bool = Field(
        default=True,
        description="Pause after curation to review clips in a chat before rendering",
    )
    default_template_id: str = Field(default="splitscreen", description="Default clip template slug")
    vision_available: bool = Field(default=False, description="Whether reference-image (vision via Claude Code) is usable")


class ProfileResponse(BaseModel):
    id: str
    name: str
    data_dir: str
    claude_binary: Optional[str] = None
    claude_config_dir: Optional[str] = None
    is_default: bool = False
    created_at: str = ""
    active: bool = False


class ProfilesListResponse(BaseModel):
    active_profile: Optional[str] = None
    profiles: List[ProfileResponse] = Field(default_factory=list)


class CreateProfileRequest(BaseModel):
    name: str
    claude_binary: Optional[str] = None
    claude_config_dir: Optional[str] = None


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    claude_binary: Optional[str] = None
    claude_config_dir: Optional[str] = None


class ValidateClaudeRequest(BaseModel):
    path: Optional[str] = None
    config_dir: Optional[str] = None


class UpdateSettingsRequest(BaseModel):
    podcast_name: Optional[str] = None
    podcast_dir: Optional[str] = None
    ai_provider_order: Optional[List[str]] = None
    anthropic_api_key: Optional[str] = None
    anthropic_model: Optional[str] = None
    transcript_supabase_url: Optional[str] = None
    transcript_supabase_key: Optional[str] = None
    review_brief_before_processing: Optional[bool] = None
    default_template_id: Optional[str] = None


# ── Clip templates ──────────────────────────────────────────────────────────


class TemplateListResponse(BaseModel):
    templates: List[ClipTemplate] = Field(default_factory=list)


class CreateTemplateRequest(BaseModel):
    """Create a custom template. subtitles/layout default to a sane baseline."""

    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=280)
    author: str = Field(default="", max_length=60)
    subtitles: Optional[SubtitleSpec] = None
    layout: Optional[LayoutSpec] = None
    intro_title: Optional[IntroTitleSpec] = None


class UpdateTemplateRequest(BaseModel):
    """Replace the editable fields of a custom template (id/timestamps preserved)."""

    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=280)
    author: str = Field(default="", max_length=60)
    subtitles: Optional[SubtitleSpec] = None
    layout: Optional[LayoutSpec] = None
    # Omitted → keep existing; sent as null → disable. (Handler checks
    # model_fields_set to tell "not sent" from "sent as null".)
    intro_title: Optional[IntroTitleSpec] = None


class CloneTemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class TemplateChatMessage(BaseModel):
    role: str = "user"
    content: str = ""


class TemplateChatRequest(BaseModel):
    template: ClipTemplate
    messages: List[TemplateChatMessage] = Field(default_factory=list)
    image_b64: Optional[str] = None  # reference image (vision; T6)


class TemplateChatResponse(BaseModel):
    explanation: str
    template: ClipTemplate
    provider_used: str = ""


class ImportTemplateResponse(BaseModel):
    template: ClipTemplate
    warnings: List[str] = Field(default_factory=list)


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
