"""
Telemetry Service — Opt-in consent-based telemetry for Collective Intelligence.

Rules:
  1. Default OFF — no data sent without explicit user consent
  2. Never sends: raw audio, video, transcripts, titles, channel names, video IDs
  3. Only sends: anonymized aggregated metrics (scores, durations, hook types, counts)
  4. Fire-and-forget — never blocks or crashes the main pipeline
  5. Source tagged as 'user_telemetry' for IC data origin tracking
"""

import threading
from typing import Dict, Any, Optional, List
from supabase import create_client, Client
from pydantic import BaseModel
from packages.core.config import settings


class TelemetryEvent(BaseModel):
    event_type: str
    user_id: str
    source: str = "user_telemetry"
    metadata: Dict[str, Any]


class TelemetryService:
    """
    Handles opt-in telemetry for the Collective Intelligence (IC) Engine.
    
    Consent model:
      - AZELIA_TELEMETRY_ENABLED=true in .env → user has opted in
      - Default: false (OFF) — no data leaves the machine
      - Toggled via Settings UI or during Onboarding wizard
    """

    def __init__(self):
        # Opt-in: only enabled when user explicitly consents
        self.enabled = settings.azelia_telemetry_enabled
        self.supabase: Optional[Client] = None

        if self.enabled and settings.supabase_url and settings.supabase_key:
            try:
                self.supabase = create_client(settings.supabase_url, settings.supabase_key)
            except Exception as e:
                print(f"[Telemetry] Warning: Could not initialize Supabase client: {e}")
                self.enabled = False

    def reload_consent(self):
        """Re-check consent status (called after user toggles telemetry)."""
        # Re-read from environment / .env
        from importlib import reload
        import packages.core.config as config_module
        reload(config_module)
        self.enabled = config_module.settings.azelia_telemetry_enabled

        if self.enabled and not self.supabase and settings.supabase_url and settings.supabase_key:
            try:
                self.supabase = create_client(settings.supabase_url, settings.supabase_key)
            except Exception:
                self.enabled = False

    def track_curation_metrics(
        self,
        user_id: str,
        num_clips_found: int,
        avg_virality_score: float,
        top_topics: List[str],
        duration_seconds: Optional[float] = None,
        hook_types: Optional[List[str]] = None,
        content_niche: Optional[str] = None,
        region: Optional[str] = None,
        language: Optional[str] = None,
    ):
        """
        Records anonymized metadata about a curation run.
        
        NEVER includes: episode title, podcast name, video URL, transcript text.
        ONLY includes: aggregated metrics and structural patterns.
        """
        if not self.enabled or not self.supabase:
            return

        event = TelemetryEvent(
            event_type="curation_run",
            user_id=user_id,
            metadata={
                "clips_generated": num_clips_found,
                "avg_virality_score": round(avg_virality_score, 2),
                "topic_patterns": top_topics[:5],  # Max 5 topics, no PII
                "duration_seconds": duration_seconds,
                "hook_types": hook_types or [],
                # Context segmentation for IC
                "content_niche": content_niche,
                "region": region,
                "language": language,
            },
        )
        self._send_event(event)

    def track_tool_usage(self, user_id: str, tool: str):
        """
        Upserts tool usage tracking.
        Tools: 'clips', 'studio', 'crm', 'ros_maker'
        """
        if not self.enabled or not self.supabase:
            return

        def _upsert():
            try:
                self.supabase.table("tool_usage").upsert(
                    {
                        "user_id": user_id,
                        "tool": tool,
                        "last_used_at": "now()",
                        "usage_count": 1,  # Supabase handles increment via ON CONFLICT
                    },
                    on_conflict="user_id,tool",
                ).execute()
            except Exception as e:
                print(f"[Telemetry] Failed to track tool usage: {e}")

        threading.Thread(target=_upsert, daemon=True).start()

    def track_clip_performance(
        self,
        user_id: str,
        predicted_score: float,
        hook_type: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        emotional_charge: Optional[str] = None,
        has_cta: Optional[bool] = None,
        word_count: Optional[int] = None,
        question_density: Optional[float] = None,
    ):
        """
        Records anonymized structural signals from a single clip.
        These feed IC pattern detection (hook effectiveness, duration optimization).
        """
        if not self.enabled or not self.supabase:
            return

        event = TelemetryEvent(
            event_type="clip_signal",
            user_id=user_id,
            metadata={
                "predicted_score": round(predicted_score, 2),
                "hook_type": hook_type,
                "duration_seconds": duration_seconds,
                "emotional_charge": emotional_charge,
                "has_cta": has_cta,
                "word_count": word_count,
                "question_density": round(question_density, 3) if question_density else None,
            },
        )
        self._send_event(event)

    def track_consent_change(self, user_id: str, consented: bool):
        """Records consent state change (for audit trail, always sent regardless of consent)."""
        if not self.supabase and settings.supabase_url and settings.supabase_key:
            try:
                self.supabase = create_client(settings.supabase_url, settings.supabase_key)
            except Exception:
                return

        if not self.supabase:
            return

        def _record():
            try:
                # Update user_profiles with consent status
                self.supabase.table("user_profiles").update({
                    "telemetry_consent": consented,
                    "telemetry_consent_at": "now()" if consented else None,
                }).eq("id", user_id).execute()
            except Exception as e:
                print(f"[Telemetry] Failed to record consent change: {e}")

        threading.Thread(target=_record, daemon=True).start()

    def _send_event(self, event: TelemetryEvent):
        """Fire-and-forget: sends event in background thread. Never blocks pipeline."""
        def _push():
            try:
                self.supabase.table("ic_telemetry_events").insert(
                    event.model_dump()
                ).execute()
            except Exception as e:
                print(f"[Telemetry] Failed to record event: {e}")

        threading.Thread(target=_push, daemon=True).start()


# Global singleton
telemetry = TelemetryService()

