"""
Telemetry Service — Opt-in consent-based telemetry for Collective Intelligence.

Rules:
  1. Default OFF — no data sent without explicit user consent
  2. Never sends: raw audio, video, transcripts, titles, channel names, video IDs
  3. Only sends: anonymized aggregated metrics (scores, durations, hook types, counts)
  4. Fire-and-forget — never blocks or crashes the main pipeline
  5. Source tagged as 'user_telemetry' for IC data origin tracking
"""

import hashlib
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
from supabase import create_client, Client
from pydantic import BaseModel
from packages.core.config import settings

# Per-user consent cache TTL (5 minutes). Avoids a DB call on every event
# while ensuring consent changes propagate quickly.
_CONSENT_CACHE_TTL = 300

# Cached cohort salt — fetched once from the central DB on first need.
# The same value is used to hash user_id → cohort_hash so telemetry is
# anonymous (GDPR / Habeas Data compliant) yet events from the same user
# still group together for aggregate analysis.
_cohort_salt: Optional[str] = None
_cohort_salt_lock = threading.Lock()


def _utc_now_iso() -> str:
    """Return current UTC timestamp as ISO string (Supabase-compatible)."""
    return datetime.now(timezone.utc).isoformat()


def _resolve_cohort_salt() -> Optional[str]:
    """One-shot fetch of the DB-side telemetry salt. Cached after first success."""
    global _cohort_salt
    if _cohort_salt is not None:
        return _cohort_salt
    with _cohort_salt_lock:
        if _cohort_salt is not None:
            return _cohort_salt
        svc = getattr(settings, "supabase_service_role_key", "") or ""
        url = getattr(settings, "supabase_url", "") or ""
        if not (svc and url):
            return None
        try:
            import httpx as _httpx
            r = _httpx.get(
                f"{url}/rest/v1/_telemetry_salt",
                params={"select": "salt", "id": "eq.1"},
                headers={"apikey": svc, "Authorization": f"Bearer {svc}"},
                timeout=5,
            )
            if r.status_code == 200 and r.json():
                _cohort_salt = r.json()[0].get("salt")
                return _cohort_salt
        except Exception:
            pass
        return None


def _cohort_hash(user_id: str) -> Optional[str]:
    """Map a user_id to a one-way cohort_hash. Returns None if salt unavailable
    — caller must skip the telemetry write in that case to avoid leaking PII."""
    if not user_id:
        return None
    salt = _resolve_cohort_salt()
    if not salt:
        return None
    return hashlib.sha256((user_id + salt).encode()).hexdigest()[:12]


class TelemetryEvent(BaseModel):
    event_type: str
    cohort_hash: str
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
        # Service-level flag: is Supabase reachable? (not the same as user consent)
        self.supabase: Optional[Client] = None
        # Per-user consent cache: {user_id: (consented: bool, expires_at: float)}
        self._consent_cache: Dict[str, Tuple[bool, float]] = {}

        if settings.supabase_url and settings.supabase_key:
            try:
                self.supabase = create_client(settings.supabase_url, settings.supabase_key)
            except Exception as e:
                print(f"[Telemetry] Warning: Could not initialize Supabase client: {e}")

    @property
    def enabled(self) -> bool:
        """True if the Supabase client is available (service-level check)."""
        return self.supabase is not None

    def _is_user_consented(self, user_id: str) -> bool:
        """
        Check if this specific user has opted in to telemetry.
        Reads from profiles.telemetry_consent with a 5-minute in-memory cache.
        This is the authoritative check — not a global env var.
        """
        if not self.supabase or not user_id or user_id == "anonymous":
            return False
        now = time.monotonic()
        cached = self._consent_cache.get(user_id)
        if cached and now < cached[1]:
            return cached[0]
        try:
            result = self.supabase.table("profiles").select("telemetry_consent").eq("id", user_id).single().execute()
            consented = bool(result.data and result.data.get("telemetry_consent"))
        except Exception:
            consented = False
        self._consent_cache[user_id] = (consented, now + _CONSENT_CACHE_TTL)
        return consented

    def invalidate_consent_cache(self, user_id: str):
        """Call after a user changes their consent so the next event re-checks DB."""
        self._consent_cache.pop(user_id, None)

    def reload_consent(self):
        """Legacy: clear the whole cache so all users re-check on next event."""
        self._consent_cache.clear()
        if not self.supabase and settings.supabase_url and settings.supabase_key:
            try:
                self.supabase = create_client(settings.supabase_url, settings.supabase_key)
            except Exception:
                pass

    # ── Normalization helpers (align with IC Signal Contract) ────────────

    @staticmethod
    def _normalize_hook_type(raw: Optional[str]) -> Optional[str]:
        """Map free-form hook type to canonical values from ic_contract."""
        if not raw:
            return None
        from packages.core.ic_contract import VALID_HOOK_TYPES
        raw_lower = raw.lower().strip().replace(" ", "_").replace("-", "_")
        # Direct match
        if raw_lower in VALID_HOOK_TYPES:
            return raw_lower
        # Fuzzy mapping
        HOOK_ALIASES = {
            "pregunta": "question", "interrogative": "question",
            "dato_sorprendente": "surprising_fact", "surprising": "surprising_fact", "fact": "surprising_fact",
            "controversial": "controversial_statement", "polemico": "controversial_statement", "bold_claim": "controversial_statement",
            "story": "storytelling", "narrative": "storytelling", "anecdote": "storytelling", "historia": "storytelling",
            "negative": "negative_frame", "negativo": "negative_frame", "pain_point": "negative_frame",
            "how_to": "tutorial", "instructional": "tutorial", "educational": "tutorial",
            "debil": "weak", "generic": "weak", "none": "weak",
        }
        return HOOK_ALIASES.get(raw_lower, raw_lower if raw_lower in VALID_HOOK_TYPES else "weak")

    @staticmethod
    def _normalize_emotional_charge(raw: Optional[str]) -> Optional[str]:
        """Map free-form emotional charge to canonical values."""
        if not raw:
            return None
        from packages.core.ic_contract import VALID_EMOTIONAL_CHARGES
        raw_lower = raw.lower().strip().replace(" ", "_").replace("-", "_")
        if raw_lower in VALID_EMOTIONAL_CHARGES:
            return raw_lower
        EMOTION_ALIASES = {
            "inspirador": "inspirational", "motivational": "inspirational",
            "urgente": "urgent", "alarming": "urgent",
            "comedia": "comedic", "humor": "comedic", "funny": "comedic",
            "indignacion": "outrage", "anger": "outrage", "rage": "outrage",
            "educativo": "educational", "informative": "educational",
            "empatico": "empathetic", "emotional": "empathetic", "vulnerable": "empathetic",
        }
        return EMOTION_ALIASES.get(raw_lower, raw_lower if raw_lower in VALID_EMOTIONAL_CHARGES else None)

    @staticmethod
    def _compute_duration_bucket(seconds: Optional[float]) -> Optional[str]:
        """Map duration to canonical bucket."""
        if seconds is None:
            return None
        if seconds <= 15:
            return "0-15"
        elif seconds <= 30:
            return "15-30"
        elif seconds <= 45:
            return "30-45"
        else:
            return "45-60"

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
        category: Optional[str] = None,
        episode_format: Optional[str] = None,
    ):
        """
        Records anonymized metadata about a curation run.
        
        NEVER includes: episode title, podcast name, video URL, transcript text.
        ONLY includes: aggregated metrics and structural patterns.
        """
        if not self._is_user_consented(user_id):
            return

        # Normalize hook_types to canonical values
        normalized_hooks = [
            self._normalize_hook_type(h) for h in (hook_types or [])
        ]

        cohort = _cohort_hash(user_id)
        if not cohort:
            return
        event = TelemetryEvent(
            event_type="curation_run",
            cohort_hash=cohort,
            metadata={
                "clips_generated": num_clips_found,
                "avg_virality_score": round(avg_virality_score, 2),
                "topic_patterns": top_topics[:5],  # Max 5 topics, no PII
                "duration_seconds": duration_seconds,
                "hook_types": [h for h in normalized_hooks if h],
                # IC Signal Contract fields
                "category": category,
                "episode_format": episode_format,
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
        if not self._is_user_consented(user_id):
            return

        def _upsert():
            try:
                self.supabase.table("tool_usage").upsert(
                    {
                        "user_id": user_id,
                        "tool": tool,
                        "last_used_at": _utc_now_iso(),
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
        category: Optional[str] = None,
        episode_format: Optional[str] = None,
    ):
        """
        Records anonymized structural signals from a single clip.
        These feed IC pattern detection (hook effectiveness, duration optimization).
        Fields normalized to IC Signal Contract canonical values.
        """
        if not self._is_user_consented(user_id):
            return

        cohort = _cohort_hash(user_id)
        if not cohort:
            return
        event = TelemetryEvent(
            event_type="clip_signal",
            cohort_hash=cohort,
            metadata={
                "predicted_score": round(predicted_score, 2),
                "hook_type": self._normalize_hook_type(hook_type),
                "duration_seconds": duration_seconds,
                "duration_bucket": self._compute_duration_bucket(duration_seconds),
                "emotional_charge": self._normalize_emotional_charge(emotional_charge),
                "has_cta": has_cta,
                "word_count": word_count,
                "question_density": round(question_density, 3) if question_density else None,
                # IC Signal Contract fields
                "category": category,
                "episode_format": episode_format,
            },
        )
        self._send_event(event)

    def track_consent_change(self, user_id: str, consented: bool):
        """Records consent state change (audit trail write, authed server-side).

        Uses the service role key so the UPDATE bypasses RLS for this specific
        server-side audit write. The user's identity was already verified by
        require_auth before we got here, so writing to user_id's own row is safe.
        """
        svc_key = getattr(settings, "supabase_service_role_key", "") or ""
        if not (settings.supabase_url and svc_key):
            # Fallback: try anon client (old behavior) — will typically no-op due to RLS
            if not self.supabase and settings.supabase_url and settings.supabase_key:
                try:
                    self.supabase = create_client(settings.supabase_url, settings.supabase_key)
                except Exception:
                    return
            if not self.supabase:
                return
            client = self.supabase
        else:
            # Service-role client — authoritative audit write
            try:
                client = create_client(settings.supabase_url, svc_key)
            except Exception as e:
                print(f"[Telemetry] Service-role client init failed: {e}")
                return

        def _record():
            try:
                res = client.table("profiles").update({
                    "telemetry_consent": consented,
                    "telemetry_consent_at": _utc_now_iso() if consented else None,
                }).eq("id", user_id).execute()
                # Verify the update landed — Supabase returns list of updated rows
                if not getattr(res, "data", None):
                    print(f"[Telemetry] consent UPDATE affected 0 rows for user {user_id}")
            except Exception as e:
                print(f"[Telemetry] Failed to record consent change: {e}")

        threading.Thread(target=_record, daemon=True).start()

    def track_youtube_performance(
        self,
        user_id: str,
        youtube_id: str,
        views: int,
        likes: int,
        comments: int,
        duration_seconds: Optional[float] = None,
        hook_type: Optional[str] = None,
        predicted_score: Optional[float] = None,
        title_hash: Optional[str] = None,
        category: Optional[str] = None,
        episode_format: Optional[str] = None,
    ):
        """
        Records an aggregated snapshot of YouTube performance metrics for a clip.
        Matches the architectural requirement for batch IC processing: one row per clip sync,
        containing the snapshot of views and the matched contextual patterns.
        
        NEVER includes: video title, URL, channel name.
        """
        if not self._is_user_consented(user_id):
            return

        cohort = _cohort_hash(user_id)
        if not cohort:
            return
        event = TelemetryEvent(
            event_type="youtube_clip_aggregate",
            cohort_hash=cohort,
            metadata={
                "platform": "youtube",
                "youtube_id": youtube_id,
                "title_hash": title_hash,
                "views_snapshot": views,
                "likes_snapshot": likes,
                "comments_snapshot": comments,
                "duration_seconds": duration_seconds,
                "hook_type": self._normalize_hook_type(hook_type),
                "predicted_score": predicted_score,
                "category": category,
                "episode_format": episode_format,
            },
        )
        
        def _push_user_telemetry():
            try:
                # Attempt to retrieve episode_format from the user's profile if missing
                final_format = event.metadata.get("episode_format")
                if not final_format:
                    res = self.supabase.table("profiles").select("preferences").eq("id", user_id).execute()
                    if res.data and res.data[0].get("preferences"):
                        prefs = res.data[0]["preferences"]
                        final_format = prefs.get("episode_format")
                    
                    event.metadata["episode_format"] = final_format or "interview"

                self.supabase.table("ic_user_telemetry").insert({
                    "cohort_hash": cohort,
                    "podcast_fingerprint": event.metadata.get("title_hash", "unknown_hash"),
                    "category": event.metadata.get("category"),
                    "episode_format": final_format or "interview",
                    "platform": "youtube",
                    "avg_view_duration_s": event.metadata.get("duration_seconds"),
                    "signal_type": "youtube_clip_aggregate",
                    "pattern_applied": {
                        "hook_type": event.metadata.get("hook_type"),
                        "predicted_score": event.metadata.get("predicted_score"),
                        "views": event.metadata.get("views_snapshot"),
                        "likes": event.metadata.get("likes_snapshot"),
                        "comments": event.metadata.get("comments_snapshot"),
                    },
                    "metrics_window_days": 7
                }).execute()
            except Exception as e:
                print(f"[Telemetry] Failed to record user telemetry: {e}")

        threading.Thread(target=_push_user_telemetry, daemon=False).start()

    def _send_event(self, event: TelemetryEvent):
        """Fire-and-forget: sends event in background thread. Never blocks pipeline."""
        def _push():
            try:
                self.supabase.table("ic_telemetry_events").insert(
                    event.model_dump()
                ).execute()
            except Exception as e:
                print(f"[Telemetry] Failed to record event: {e}")

        # Use daemon=False to ensure the thread finishes writing to Supabase
        # even if the main FastAPI application is shutting down.
        threading.Thread(target=_push, daemon=False).start()


# Global singleton
telemetry = TelemetryService()
