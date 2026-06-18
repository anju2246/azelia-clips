"""Centralized configuration using Pydantic Settings.

Local-first MVP — no central backend, single user.
LLM providers restricted to Claude Code (local subscription) and Anthropic API.
"""

import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _azelia_home() -> Path:
    """Where the user installation lives (~/.azelia by default). Holds the
    machine-global profile registry, outside any single profile's data dir."""
    return Path(os.environ.get("AZELIA_HOME", Path.home() / ".azelia"))


def _resolve_data_dir(home: Path, override: str | None) -> Path:
    """Resolve the effective data dir WITHOUT side effects (no migration here).

    Order: AZELIA_DATA_DIR override > active profile (if a registry exists) >
    legacy ~/.azelia/data fallback. Migration that *creates* the registry is
    deferred to `initialize_active_profile()` at server boot, so merely
    importing this module never mutates the filesystem.
    """
    if override:
        return Path(override).expanduser()
    from packages.core.profiles import ProfileManager

    pm = ProfileManager(home)
    if pm.registry_path.exists():
        return pm.active_data_dir()
    return home / "data"


def _default_data_dir() -> Path:
    """User data lives under the active profile by default, never inside the
    checkout. Honors AZELIA_DATA_DIR for isolated installs."""
    return _resolve_data_dir(_azelia_home(), os.environ.get("AZELIA_DATA_DIR"))


def _secrets_env_path() -> str:
    """secrets.env always lives next to the rest of the user data so an
    AZELIA_DATA_DIR override moves it too. Hardcoding Path.home() here
    (the old behavior) leaked across isolated installs: every new
    install on the same machine would still read the developer's
    ~/.azelia/data/secrets.env even when AZELIA_DATA_DIR was set.
    """
    return str(_default_data_dir() / "secrets.env")


class Settings(BaseSettings):
    """Application settings loaded from env vars + secrets.env under the data dir."""

    model_config = SettingsConfigDict(
        env_file=(".env", _secrets_env_path()),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Data persistence ────────────────────────────────────────────────
    data_dir: Path = Field(
        default_factory=_default_data_dir,
        alias="AZELIA_DATA_DIR",
        description="Where user data lives (jobs, SQLite DBs, secrets). Never modified by self-update. Override with AZELIA_DATA_DIR env var.",
    )

    # ── LLM providers (restricted to Claude Code + Anthropic) ──────────
    ai_provider_order: str = Field(
        default="claude_code,anthropic",
        description="Comma-separated list of AI providers by priority. MVP supports: claude_code, anthropic.",
    )
    anthropic_api_key: str = Field(default="", description="Anthropic API key for Claude")
    anthropic_model: str = Field(default="claude-sonnet-4-6", description="Selected Anthropic model")

    # ── Claude Code binding (per active profile, set at boot) ──────────
    claude_binary: str | None = Field(default=None, description="Path to the Claude Code binary for the active profile (None ⇒ `claude` on PATH)")
    claude_config_dir: str | None = Field(default=None, description="CLAUDE_CONFIG_DIR for the active profile's Claude account (None ⇒ CLI default)")

    # ── User-owned transcript DB (optional, BYO Supabase) ──────────────
    # If the user already has their podcast transcripts in their own Supabase
    # project, they can configure these in Settings → Integrations. The local
    # pipeline will pull transcripts from there instead of re-running Whisper.
    # Azelia has nothing to do with this DB — it's the user's own infra.
    transcript_supabase_url: str = Field(default="", description="User's own Supabase URL for transcript ingestion (optional)")
    transcript_supabase_key: str = Field(default="", description="User's own Supabase service key for transcripts (optional)")

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

    # ── Clip templates ─────────────────────────────────────────────────
    default_template_id: str = Field(
        default="splitscreen",
        alias="DEFAULT_TEMPLATE_ID",
        description="Slug of the clip template applied by default (per profile). Override per-job at upload.",
    )

    # ── Human-in-the-loop brief gate ───────────────────────────────────
    review_brief_before_processing: bool = Field(
        default=True,
        description="Pause after AI curation to review/curate clips in a chat before rendering",
    )

    def ensure_output_dir(self) -> Path:
        """Create output directory if it doesn't exist."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir

    def jobs_dir(self) -> Path:
        """Where job data lives. Created on demand."""
        d = self.data_dir / "jobs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def templates_dir(self) -> Path:
        """Where the active profile's clip templates (.azt) live. Created on demand."""
        d = self.data_dir / "templates"
        d.mkdir(parents=True, exist_ok=True)
        return d


# Global settings instance
settings = Settings()


def initialize_active_profile() -> None:
    """Run ONCE at server boot: migrate the legacy tree on first run, then bind
    the active profile's data dir + Claude account onto the live settings.

    This is the only place migration happens (it mutates the filesystem), so it
    must be called explicitly at startup — never as an import side effect.
    """
    from packages.core.profiles import ProfileManager

    home = _azelia_home()
    override = os.environ.get("AZELIA_DATA_DIR")
    pm = ProfileManager(home)
    pm.ensure_initialized(
        legacy_data_dir=home / "data",
        override_data_dir=Path(override).expanduser() if override else None,
    )
    active = pm.active()
    settings.data_dir = Path(active.data_dir)
    settings.claude_binary = active.claude_binary
    settings.claude_config_dir = active.claude_config_dir
