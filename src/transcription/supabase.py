import os
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from rich.console import Console
from .base import TranscriptionSource
from src.asr.transcriber import Transcript, Segment

console = Console()

@dataclass
class Utterance:
    """A single utterance from Supabase with speaker and timing."""
    speaker: str       # "A" or "B"
    text: str
    start_time: float
    end_time: float
    confidence: float = 1.0

class SupabaseSource(TranscriptionSource):
    """Fetches transcripts from a private/custom Supabase database."""
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Check for URL and Key."""
        return bool(config.get("supabase_url") and config.get("supabase_key"))

    def get_transcript(self, resource_id: str, **kwargs) -> Optional[Transcript]:
        """
        Fetch transcript by Episode ID (e.g. "EP097").
        Requires 'supabase_url' and 'supabase_key' in kwargs.
        """
        url = kwargs.get("supabase_url")
        key = kwargs.get("supabase_key")
        
        if not url or not key:
            raise ValueError("Supabase URL and Key required for SupabaseSource")

        # Lazy import to avoid dependency issues if not used
        from supabase import create_client
        
        client = create_client(url, key)
        console.print(f"[blue]📡[/blue] Fetching utterances for {resource_id} from Custom Supabase...")

        # 1. Fetch Utterances
        response = (
            client.table("utterances")
            .select("*")
            .eq("episode_id", resource_id)
            .order("start_time")
            .execute()
        )

        if not response.data:
            console.print(f"[yellow]No utterances found for {resource_id}[/yellow]")
            return None

        utterances = []
        for row in response.data:
            start = row.get("start_time")
            end = row.get("end_time")
            if start is None or end is None:
                continue
                
            utterances.append(Utterance(
                speaker=row.get("speaker", "A"),
                text=row.get("text", ""),
                start_time=float(start),
                end_time=float(end),
                confidence=float(row.get("confidence", 1.0)),
            ))

        # 2. Fetch Duration (Optional)
        duration = 0
        try:
            ep_res = client.table("episodes").select("duration_seconds").eq("id", resource_id).single().execute()
            if ep_res.data:
                duration = float(ep_res.data.get("duration_seconds", 0))
        except Exception:
            pass # Ignore if episode metadata missing

        if duration == 0 and utterances:
            duration = max(u.end_time for u in utterances)

        return self._to_transcript(utterances, resource_id, duration)

    def _to_transcript(self, utterances: List[Utterance], episode_id: str, duration: float) -> Transcript:
        """Convert Utterances to Transcript object."""
        speaker_map = {"A": "SPEAKER_00", "B": "SPEAKER_01"}
        segments = []
        
        for utt in utterances:
            segments.append(Segment(
                text=utt.text,
                start=utt.start_time,
                end=utt.end_time,
                words=[],  # Supabase usually lacks word-level timestamps
                speaker=speaker_map.get(utt.speaker, utt.speaker),
            ))
            
        return Transcript(
            segments=segments,
            language="es",
            duration=duration,
            source_file=f"supabase://{episode_id}"
        )
