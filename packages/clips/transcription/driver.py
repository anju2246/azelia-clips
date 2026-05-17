"""Transcription source factory — local-first MVP.

Sources:
- local_whisper (default, runs on user's machine)
- assemblyai (user BYOK)
- supabase_custom (user's OWN Supabase project — optional; Azelia has none)
"""

from typing import Any, Dict

from .assemblyai import AssemblyAISource
from .base import TranscriptionSource
from .local_whisper import LocalWhisperSource
from .supabase import SupabaseSource


class TranscriptionDriver:
    """Factory for transcription sources."""

    @staticmethod
    def create(source_type: str) -> TranscriptionSource:
        if source_type == "assemblyai":
            return AssemblyAISource()
        if source_type == "supabase_custom":
            return SupabaseSource()
        return LocalWhisperSource()

    @staticmethod
    def get_source_from_config(config: Dict[str, Any]) -> TranscriptionSource:
        source_type = (config.get("source_type") or "").lower()
        if source_type == "supabase_custom":
            return SupabaseSource()
        if source_type == "assemblyai":
            return AssemblyAISource()
        # Legacy fallback: presence of user-owned Supabase keys → supabase_custom
        if config.get("supabase_url") and config.get("supabase_key"):
            return SupabaseSource()
        return LocalWhisperSource()
