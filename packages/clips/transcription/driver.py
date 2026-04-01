from typing import Dict, Any, Optional
from .base import TranscriptionSource
from .local_whisper import LocalWhisperSource
from .assemblyai import AssemblyAISource
from .supabase import SupabaseSource

class TranscriptionDriver:
    """Factory for creating transcription sources."""
    
    @staticmethod
    def create(source_type: str) -> TranscriptionSource:
        """
        Create a transcription source instance.
        
        Args:
            source_type: 'local_whisper', 'assemblyai', or 'supabase_custom'
        """
        if source_type == "assemblyai":
            return AssemblyAISource()
        elif source_type == "supabase_custom":
            return SupabaseSource()
        else:
            return LocalWhisperSource() # Default
            
    @staticmethod
    def get_source_from_config(config: Dict[str, Any]) -> TranscriptionSource:
        """
        Determine source from configuration payload.
        Priority:
        1. Explicit source_type (user's choice always wins)
        2. Fallback by key presence (legacy / CLI usage)
        3. Local Whisper (default)

        Note: config may contain Azelia's central Supabase keys (for auth/telemetry).
        Those must NOT trigger SupabaseSource — only 'supabase_custom' source_type should.
        """
        source_type = config.get("source_type", "")

        if source_type == "supabase_custom":
            return SupabaseSource()
        elif source_type == "assemblyai":
            return AssemblyAISource()
        elif source_type == "local_whisper":
            return LocalWhisperSource()

        # Legacy fallback: no explicit source_type, infer from dedicated transcript keys
        # Only match supabase if transcript-specific keys are present (not Azelia central keys)
        if config.get("transcript_supabase_url") and config.get("transcript_supabase_key"):
            return SupabaseSource()
        elif config.get("assemblyai_api_key"):
            return AssemblyAISource()

        return LocalWhisperSource()
