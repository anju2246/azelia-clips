"""
Telemetry API Routes — Consent management and admin endpoints.

Public routes (authenticated):
  POST /api/telemetry/consent — Toggle telemetry on/off
  GET  /api/telemetry/status  — Current telemetry state

Admin routes (super_admin only):
  GET  /api/admin/telemetry/events — All telemetry events
  GET  /api/admin/telemetry/stats  — Aggregated statistics
"""

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from server.middleware.auth import require_auth, optional_auth
from packages.core.auth import User
from packages.core.services.telemetry import telemetry
from packages.core.config import settings
import sqlite3
import hashlib
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

YT_DB_PATH = Path(__file__).parent.parent / "data" / "youtube_shorts.db"


def _backfill_sqlite_history(user_id: str):
    """
    Reads all historical YouTube data from local SQLite and sends it to
    ic_user_telemetry. Called in a background thread when user activates telemetry.
    Only runs if telemetry is enabled and Supabase is connected.
    """
    if not telemetry.enabled or not telemetry.supabase:
        return

    if not YT_DB_PATH.exists():
        return

    try:
        conn = sqlite3.connect(str(YT_DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT video_id, title, duration_seconds, view_count, like_count,
                      comment_count, hook_type, average_view_duration
               FROM youtube_shorts WHERE user_id = ?""",
            (user_id,)
        ).fetchall()
        conn.close()
    except Exception as e:
        print(f"[Telemetry Backfill] Failed to read SQLite: {e}")
        return

    sent = 0
    for row in rows:
        try:
            title_hash = hashlib.sha256((row["title"] or "").encode()).hexdigest()[:12]
            telemetry.track_youtube_performance(
                user_id=user_id,
                youtube_id=row["video_id"],
                views=row["view_count"] or 0,
                likes=row["like_count"] or 0,
                comments=row["comment_count"] or 0,
                duration_seconds=row["average_view_duration"] or row["duration_seconds"],
                hook_type=row["hook_type"],
                title_hash=title_hash,
            )
            sent += 1
        except Exception as e:
            print(f"[Telemetry Backfill] Failed to send {row['video_id']}: {e}")

    print(f"[Telemetry Backfill] Sent {sent}/{len(rows)} historical records for user {user_id}")

router = APIRouter()


def require_super_admin(user: User = Depends(require_auth)) -> User:
    """Rejects any request not from a super_admin."""
    if user.role != 'super_admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Insufficient permissions'
        )
    return user


class ConsentRequest(BaseModel):
    enabled: bool


class ConsentResponse(BaseModel):
    telemetry_enabled: bool
    message: str


class TelemetryStatusResponse(BaseModel):
    telemetry_enabled: bool
    supabase_connected: bool


# ─── Public Routes (any authenticated user) ─────────────────────────

@router.post("/telemetry/consent", response_model=ConsentResponse)
async def toggle_telemetry_consent(
    body: ConsentRequest,
    user: User = Depends(require_auth),
):
    """
    Toggle telemetry consent for this user. Persisted in profiles.telemetry_consent
    (Supabase DB) — NOT in a global .env file, so multi-user installs are safe.
    """
    # Persist consent in profiles (authoritative source)
    telemetry.track_consent_change(user.id, body.enabled)

    # Invalidate this user's in-memory consent cache so next event re-reads DB
    telemetry.invalidate_consent_cache(user.id)

    # Backfill historical SQLite data when user activates telemetry
    if body.enabled:
        threading.Thread(
            target=_backfill_sqlite_history, args=(user.id,), daemon=True, name=f"telemetry_backfill_{user.id}"
        ).start()

    action = "enabled" if body.enabled else "disabled"
    return ConsentResponse(
        telemetry_enabled=body.enabled,
        message=f"Telemetry {action}. {'Your anonymous metrics will contribute to the collective IC.' if body.enabled else 'No data will be sent.'}",
    )


@router.get("/telemetry/status", response_model=TelemetryStatusResponse)
async def get_telemetry_status(user: User = Depends(optional_auth)):
    """Returns telemetry consent for the current user, read from their profile in Supabase."""
    if user and telemetry.supabase:
        try:
            result = telemetry.supabase.table("profiles").select("telemetry_consent").eq("id", user.id).single().execute()
            if result.data:
                return TelemetryStatusResponse(
                    telemetry_enabled=bool(result.data.get("telemetry_consent")),
                    supabase_connected=True,
                )
        except Exception as e:
            logger.warning(f"[Telemetry] Failed to fetch user consent from Supabase: {type(e).__name__}: {str(e)}")
    return TelemetryStatusResponse(
        telemetry_enabled=telemetry.enabled,
        supabase_connected=telemetry.supabase is not None,
    )


# ─── Admin Routes (super_admin only) ────────────────────────────────

@router.get("/admin/telemetry/stats")
async def get_telemetry_stats(user: User = Depends(require_super_admin)):
    """
    Aggregated telemetry statistics for the admin dashboard.
    Shows: total events, unique users, events by type, events by source.
    """
    if not telemetry.supabase:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase not connected",
        )

    try:
        # Total events count
        events_resp = (
            telemetry.supabase.table("ic_telemetry_events")
            .select("id", count="exact")
            .execute()
        )

        # Events by source
        by_source = (
            telemetry.supabase.rpc("count_events_by_source", {}).execute()
        )

        # Users with telemetry consent
        consent_resp = (
            telemetry.supabase.table("profiles")
            .select("id", count="exact")
            .eq("telemetry_consent", True)
            .execute()
        )

        return {
            "total_events": events_resp.count or 0,
            "users_with_consent": consent_resp.count or 0,
            "events_by_source": by_source.data if by_source.data else [],
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch stats: {str(e)}",
        )


@router.get("/admin/telemetry/events")
async def get_telemetry_events(
    user: User = Depends(require_super_admin),
    source: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """
    List telemetry events with optional filtering. Super admin only.
    """
    if not telemetry.supabase:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase not connected",
        )

    try:
        query = (
            telemetry.supabase.table("ic_telemetry_events")
            .select("*")
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
        )

        if source:
            query = query.eq("source", source)
        if event_type:
            query = query.eq("event_type", event_type)

        resp = query.execute()
        return {"events": resp.data, "count": len(resp.data)}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch events: {str(e)}",
        )
