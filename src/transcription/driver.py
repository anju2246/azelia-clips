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
        1. Custom Supabase (if URL/Key present)
        2. AssemblyAI (if Key present)
        3. Local Whisper (Default)
        """
        if config.get("supabase_url") and config.get("supabase_key"):
            return SupabaseSource()
        elif config.get("assemblyai_api_key"):
            return AssemblyAISource()
        else:
            return LocalWhisperSource()
