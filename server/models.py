from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum
from datetime import datetime

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
    assemblyai_key: Optional[str] = None
    supabase_url: Optional[str] = None
    supabase_key: Optional[str] = None

class ProcessLocalRequest(ProcessRequest):
    video_path: str

# --- New Models for Local Mode ---

class SettingsResponse(BaseModel):
    podcast_name: str
    podcast_dir: str
    ai_provider_order: List[str] = Field(default=["groq", "openai", "anthropic", "vertex"])
    groq_api_key: str = Field(default="", description="Masked key")
    groq_model: str = Field(default="llama-3.3-70b-versatile")
    openai_api_key: str = Field(default="", description="Masked key")
    openai_model: str = Field(default="gpt-4o")
    anthropic_api_key: str = Field(default="", description="Masked key")
    anthropic_model: str = Field(default="claude-3-7-sonnet-20250219")
    gcp_project_id: str = Field(default="", description="Plaintext project ID")
    vertex_model: str = Field(default="meta/llama-3.3-70b-instruct-maas")
    supabase_url: str = Field(default="")
    supabase_key: str = Field(default="", description="Masked key")
    generate_teasers: bool = Field(default=False)
    
class UpdateSettingsRequest(BaseModel):
    podcast_name: Optional[str] = None
    podcast_dir: Optional[str] = None
    ai_provider_order: Optional[List[str]] = None
    groq_api_key: Optional[str] = None
    groq_model: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    anthropic_model: Optional[str] = None
    gcp_project_id: Optional[str] = None
    vertex_model: Optional[str] = None
    supabase_url: Optional[str] = None
    supabase_key: Optional[str] = None
    generate_teasers: Optional[bool] = None

class EpisodeResponse(BaseModel):
    id: str
    number: int
    title: str
    has_video: bool
    has_transcript: bool
    is_processed: bool
    path: str
