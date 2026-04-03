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
import os
import sqlite3
import hashlib
import threading
from pathlib import Path

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
    Toggle telemetry consent. Persists to .env file so it survives restarts.
    Also updates profiles in Supabase with consent timestamp.
    """
    env_path = Path(".env")

    # Read existing .env content
    env_lines = []
    if env_path.exists():
        env_lines = env_path.read_text().splitlines()

    # Update or add AZELIA_TELEMETRY_ENABLED
    found = False
    new_value = "true" if body.enabled else "false"
    for i, line in enumerate(env_lines):
        if line.startswith("AZELIA_TELEMETRY_ENABLED"):
            env_lines[i] = f"AZELIA_TELEMETRY_ENABLED={new_value}"
            found = True
            break

    if not found:
        env_lines.append(f"AZELIA_TELEMETRY_ENABLED={new_value}")

    # Write back
    env_path.write_text("\n".join(env_lines) + "\n")

    # Update environment variable for current process
    os.environ["AZELIA_TELEMETRY_ENABLED"] = new_value

    # Reload telemetry service consent state
    telemetry.reload_consent()

    # Record consent change in Supabase (always, for audit trail)
    telemetry.track_consent_change(user.id, body.enabled)

    # Backfill historical SQLite data when user activates telemetry
    if body.enabled:
        threading.Thread(
            target=_backfill_sqlite_history, args=(user.id,), daemon=False
        ).start()

    action = "activated" if body.enabled else "deactivated"
    return ConsentResponse(
        telemetry_enabled=body.enabled,
        message=f"Telemetry {action} successfully. {'Anonymized metrics will be sent to improve IC.' if body.enabled else 'No data will be sent.'}",
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
        except Exception:
            pass
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
