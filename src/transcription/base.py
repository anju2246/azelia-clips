from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class TranscriptionSource(ABC):
    """Abstract base class for transcription sources."""
    
    @abstractmethod
    def get_transcript(self, resource_id: str, **kwargs) -> Any:
        """
        Fetch or generate a transcript.
        
        Args:
            resource_id: Path to file (local) or ID (database/cloud)
            **kwargs: Additional configuration (api_keys, etc.)
            
        Returns:
            Transcript object (src.asr.transcriber.Transcript) or None
        """
        pass
    
    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Validate if the source is properly configured."""
        pass
