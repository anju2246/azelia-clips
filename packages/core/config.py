"""Centralized configuration using Pydantic Settings."""

from pathlib import Path
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API Keys
    ai_provider_order: str = Field(default="groq,openai,anthropic,google", description="Comma-separated list of AI providers by priority")
    groq_api_key: str = Field(default="", description="Groq API key for LLM inference")
    groq_model: str = Field(default="llama-3.3-70b-versatile", description="Selected Groq model")
    groq_api_key_2: str = Field(default="", description="Secondary Groq API key (fallback)")
    hf_token: str = Field(default="", alias="HF_TOKEN", description="HuggingFace token for Pyannote")
    anthropic_api_key: str = Field(default="", description="Anthropic API key for Claude")
    anthropic_model: str = Field(default="claude-sonnet-4-6", description="Selected Anthropic model")
    openai_api_key: str = Field(default="", description="OpenAI API key for ChatGPT")
    openai_model: str = Field(default="gpt-4o", description="Selected OpenAI model")

    # Google AI (Gemini via AI Studio — simple API key, no gcloud needed)
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY", description="Google AI Studio API key")
    google_model: str = Field(default="gemini-2.5-pro", description="Selected Google Gemini model")

    # ── Azelia Central DB (Supabase) ──────────────────────────────────────
    # ⚠️ DO NOT expose in Settings UI. These power telemetry, auth, and IC.
    # The anon key is public by Supabase design (RLS protects data).
    # Auth tokens are validated via Supabase API (no JWT secret needed).
    supabase_url: str = Field(
        default="https://REDACTED-OLD-SUPABASE-PROJECT.supabase.co",
        description="Azelia Central Supabase URL (telemetry, auth, IC)"
    )
    supabase_key: str = Field(
        default="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.REDACTED-OLD-ANON-JWT-PAYLOAD.0Y2f5rmMw-jLa17d3XPjmdtQvbXO7dI0AUONzvalLBU",
        description="Azelia Central Supabase anon key (public by design)"
    )
    supabase_service_role_key: str = Field(
        default="",
        alias="SUPABASE_SERVICE_ROLE_KEY",
        description="Azelia Central Supabase service-role key — KEEP SECRET. Used only for server-side audit writes (consent, upgrade) that the anon key cannot do under RLS.",
    )

    # ── User Transcript DB (Supabase, optional) ─────────────────────────
    # Podcasters can connect their own Supabase if they store transcripts there.
    # Configured via Settings UI.
    transcript_supabase_url: str = Field(default="", description="User's own Supabase URL for transcript ingestion")
    transcript_supabase_key: str = Field(default="", description="User's own Supabase service key for transcripts")
    
    # Security / API
    allowed_cors_origins: str = Field(
        default="http://localhost:4321,http://localhost:3000,http://127.0.0.1:4321",
        description="Comma separated list of valid frontend origins"
    )

    # Whisper Configuration
    whisper_model: str = Field(default="small", description="Whisper model size (tiny, base, small, medium, large-v3)")
    whisper_device: Literal["cuda", "mps", "cpu"] = Field(
        default="mps", description="Device for Whisper inference"
    )
    whisper_compute_type: str = Field(
        default="float16", description="Compute type for Whisper"
    )
    whisper_batch_size: int = Field(default=8, description="Batch size for transcription")

    # Clip Settings
    clip_min_duration: int = Field(default=15, description="Minimum clip duration in seconds")
    clip_max_duration: int = Field(default=90, description="Maximum clip duration in seconds")
    clip_top_n: int = Field(default=10, description="Number of top clips to extract")
    clip_overlap: int = Field(default=2, description="Overlap seconds for context")

    # LLM Settings
    llm_model: str = Field(
        default="llama-3.3-70b-versatile", description="Groq model for curation"
    )
    llm_temperature: float = Field(default=0.3, description="LLM temperature")

    # Output
    output_dir: Path = Field(default=Path("./output"), description="Output directory")
    
    # Local Library
    podcast_dir: Path = Field(
        default=Path("external_drive/MyPodcast"), 
        description="Path to podcast episodes folder"
    )
    podcast_name: str = Field(
        default="My Podcast",
        description="Name of the podcast for captions and context"
    )

    # Telemetry (opt-in, default OFF — no data sent without explicit consent)
    azelia_telemetry_enabled: bool = Field(
        default=False,
        description="Whether user has consented to anonymous telemetry for IC"
    )

    def ensure_output_dir(self) -> Path:
        """Create output directory if it doesn't exist."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir


# Global settings instance
settings = Settings()
