from typing import Optional, List
from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship

class UserConnection(SQLModel, table=True):
    """Stores third-party platform connections (YouTube, TikTok) for the user."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True, description="The Supabase Auth User ID")
    platform: str = Field(index=True, description="E.g., youtube, tiktok, linkedin")
    access_token: str
    refresh_token: Optional[str] = None
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class Episode(SQLModel, table=True):
    """Local representation of a Podcast Episode to be processed."""
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: Optional[str] = Field(default=None, index=True, description="ID of the processing Job")
    user_id: str = Field(index=True, description="The Supabase Auth User ID who owns this episode")
    
    title: str
    video_path: Optional[str] = None
    audio_path: Optional[str] = None
    transcript_path: Optional[str] = None
    
    status: str = Field(default="pending", description="pending, transcribing, curating, failed, completed")
    error_message: Optional[str] = None
    
    # Progress tracking for resuming
    progress_percent: int = Field(default=0)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    clips: List["Clip"] = Relationship(back_populates="episode")

class Clip(SQLModel, table=True):
    """A curated video clip generated from an Episode."""
    id: Optional[int] = Field(default=None, primary_key=True)
    episode_id: int = Field(foreign_key="episode.id")
    episode: Episode = Relationship(back_populates="clips")
    
    title: str
    summary: str
    virality_score: float
    start_time: float
    end_time: float
    duration: float
    
    video_path: Optional[str] = None
    status: str = Field(default="pending", description="pending, rendering, completed, failed, approved, rejected")
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
