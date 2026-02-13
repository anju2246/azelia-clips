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
    groq_api_key: str = Field(default="", description="Groq API key for LLM inference")
    hf_token: str = Field(default="", alias="HF_TOKEN", description="HuggingFace token for Pyannote")
    anthropic_api_key: str = Field(default="", description="Anthropic API key for Claude")

    # GCP Configuration
    gcp_project_id: str = Field(default="", alias="GCP_PROJECT_ID", description="Google Cloud Project ID")
    gcp_location: str = Field(default="us-central1", alias="GCP_LOCATION", description="GCP region")


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
        default=Path("external_drive/Backup Inminente"), 
        description="Path to podcast episodes folder"
    )

    def ensure_output_dir(self) -> Path:
        """Create output directory if it doesn't exist."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir


# Global settings instance
settings = Settings()
