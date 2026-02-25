import os
from typing import Dict, Any, Optional
from supabase import create_client, Client
from pydantic import BaseModel
from packages.core.config import settings

class TelemetryEvent(BaseModel):
    event_type: str
    user_id: str
    metadata: Dict[str, Any]

class TelemetryService:
    """
    Handles opt-out telemetry for the Collective Intelligence (IC) Engine.
    Strictly forbids sending raw audio, video, or full transcripts.
    Only sends aggregated metrics (speaking pace, sentiment, topic patterns).
    """
    def __init__(self):
        # We need a valid Supabase configuration to send telemetry
        self.enabled = os.environ.get("CELIA_TELEMETRY_OPT_OUT", "false").lower() != "true"
        self.supabase: Optional[Client] = None
        
        if self.enabled and settings.supabase_url and settings.supabase_key:
            try:
                self.supabase = create_client(settings.supabase_url, settings.supabase_key)
            except Exception as e:
                print(f"[Telemetry] Warning: Could not initialize Supabase client for IC: {e}")
                self.enabled = False

    def track_curation_metrics(self, user_id: str, episode_id: str, num_clips_found: int, avg_virality_score: float, top_topics: list[str]):
        """Records metadata about an episode curation run."""
        if not self.enabled or not self.supabase:
            return
            
        event = TelemetryEvent(
            event_type="curation_run",
            user_id=user_id,
            metadata={
                "episode_id": episode_id,
                "clips_generated": num_clips_found,
                "avg_virality_score": avg_virality_score,
                "topic_patterns": top_topics
            }
        )
        self._send_event(event)

    def track_clip_performance_prediction(self, user_id: str, clip_id: str, predicted_score: float, sentiment: str, pacing_wpm: float):
        """Records metadata about a specific clip generated for the IC Engine."""
        if not self.enabled or not self.supabase:
            return
            
        event = TelemetryEvent(
            event_type="clip_prediction",
            user_id=user_id,
            metadata={
                "clip_id": clip_id,
                "predicted_score": predicted_score,
                "sentiment_profile": sentiment,
                "pacing_words_per_minute": pacing_wpm
            }
        )
        self._send_event(event)

    def _send_event(self, event: TelemetryEvent):
        """Internal method to push to Supabase table asynchronously if possible, or synchronously."""
        try:
            # Table 'ic_telemetry_events' must exist in Supabase
            self.supabase.table("ic_telemetry_events").insert(event.model_dump()).execute()
        except Exception as e:
            # Fire and forget; never crash the app for telemetry
            print(f"[Telemetry] Failed to record event: {e}")

# Global singleton
telemetry = TelemetryService()
