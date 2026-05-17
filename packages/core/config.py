"""Centralized configuration using Pydantic Settings.

Local-first MVP — no central backend, single user.
LLM providers restricted to Claude Code (local subscription) and Anthropic API.
"""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> Path:
    """User data lives in ~/.azelia/data by default, never inside the checkout.

    Override with AZELIA_DATA_DIR for dev mode (e.g. ./data inside the repo).
    """
    return Path.home() / ".azelia" / "data"


class Settings(BaseSettings):
    """Application settings loaded from environment variables and ~/.azelia/data/secrets.env."""

    model_config = SettingsConfigDict(
        env_file=(".env", str(Path.home() / ".azelia" / "data" / "secrets.env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Data persistence ────────────────────────────────────────────────
    data_dir: Path = Field(
        default_factory=_default_data_dir,
        description="Where user data lives (jobs, SQLite DBs, secrets). Never modified by self-update.",
    )

    # ── LLM providers (restricted to Claude Code + Anthropic) ──────────
    ai_provider_order: str = Field(
        default="claude_code,anthropic",
        description="Comma-separated list of AI providers by priority. MVP supports: claude_code, anthropic.",
    )
    anthropic_api_key: str = Field(default="", description="Anthropic API key for Claude")
    anthropic_model: str = Field(default="claude-sonnet-4-6", description="Selected Anthropic model")

    # ── Optional HuggingFace token for speaker diarization (Pyannote) ──
    hf_token: str = Field(default="", alias="HF_TOKEN", description="HuggingFace token for Pyannote diarization (optional)")

    # ── Network ─────────────────────────────────────────────────────────
    bind_host: str = Field(
        default="127.0.0.1",
        alias="AZELIA_BIND_HOST",
        description="Host to bind the server. Default 127.0.0.1 (localhost-only). Set to 0.0.0.0 for LAN access (no auth!).",
    )
    allowed_cors_origins: str = Field(
        default="http://localhost:4321,http://localhost:8000,http://127.0.0.1:4321,http://127.0.0.1:8000",
        description="Comma separated list of allowed frontend origins (dev mode mostly)",
    )

    # ── Whisper Configuration ──────────────────────────────────────────
    whisper_model: str = Field(default="small", description="Whisper model size (tiny, base, small, medium, large-v3)")
    whisper_device: Literal["cuda", "mps", "cpu"] = Field(default="mps", description="Device for Whisper inference")
    whisper_compute_type: str = Field(default="float16", description="Compute type for Whisper")
    whisper_batch_size: int = Field(default=8, description="Batch size for transcription")

    # ── Clip Settings ──────────────────────────────────────────────────
    clip_min_duration: int = Field(default=15, description="Minimum clip duration in seconds")
    clip_max_duration: int = Field(default=90, description="Maximum clip duration in seconds")
    clip_top_n: int = Field(default=10, description="Number of top clips to extract")
    clip_overlap: int = Field(default=2, description="Overlap seconds for context")

    # ── LLM Settings ───────────────────────────────────────────────────
    llm_temperature: float = Field(default=0.3, description="LLM temperature")

    # ── Output / Library ───────────────────────────────────────────────
    output_dir: Path = Field(default=Path("./output"), description="Default output directory (CLI mode)")
    podcast_dir: Path = Field(
        default=Path.home() / "Podcasts",
        description="Path to podcast episodes folder (library mode)",
    )
    podcast_name: str = Field(default="My Podcast", description="Name of the podcast for captions and context")

    def ensure_output_dir(self) -> Path:
        """Create output directory if it doesn't exist."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir

    def jobs_dir(self) -> Path:
        """Where job data lives. Created on demand."""
        d = self.data_dir / "jobs"
        d.mkdir(parents=True, exist_ok=True)
        return d


# Global settings instance
settings = Settings()
