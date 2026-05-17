"""Transcription source factory — local-first MVP.

Supabase-based transcripts removed in v0.1.0. Sources:
- local_whisper (default, runs on user's machine)
- assemblyai (user BYOK)
- srt (load pre-existing SRT file)
"""

from typing import Any, Dict

from .assemblyai import AssemblyAISource
from .base import TranscriptionSource
from .local_whisper import LocalWhisperSource


class TranscriptionDriver:
    """Factory for transcription sources."""

    @staticmethod
    def create(source_type: str) -> TranscriptionSource:
        if source_type == "assemblyai":
            return AssemblyAISource()
        return LocalWhisperSource()

    @staticmethod
    def get_source_from_config(config: Dict[str, Any]) -> TranscriptionSource:
        source_type = (config.get("source_type") or "").lower()
        if source_type == "assemblyai":
            return AssemblyAISource()
        # local_whisper, supabase_custom (degraded to local), anything else → local
        return LocalWhisperSource()
