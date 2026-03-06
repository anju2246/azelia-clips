"""
Telemetry API Routes — Consent management and admin endpoints.

Public routes (authenticated):
  POST /api/telemetry/consent — Toggle telemetry on/off
  GET  /api/telemetry/status  — Current telemetry state

Admin routes (super_admin only):
  GET  /api/admin/telemetry/events — All telemetry events
  GET  /api/admin/telemetry/stats  — Aggregated statistics
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from packages.core.auth import User, get_current_user, require_super_admin
from packages.core.services.telemetry import telemetry
from packages.core.config import settings
import os
from pathlib import Path

router = APIRouter()


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
    user: User = Depends(get_current_user),
):
    """
    Toggle telemetry consent. Persists to .env file so it survives restarts.
    Also updates user_profiles in Supabase with consent timestamp.
    """
    env_path = Path(".env")

    # Read existing .env content
    env_lines = []
    if env_path.exists():
        env_lines = env_path.read_text().splitlines()

    # Update or add CELIA_TELEMETRY_ENABLED
    found = False
    new_value = "true" if body.enabled else "false"
    for i, line in enumerate(env_lines):
        if line.startswith("CELIA_TELEMETRY_ENABLED"):
            env_lines[i] = f"CELIA_TELEMETRY_ENABLED={new_value}"
            found = True
            break

    if not found:
        env_lines.append(f"CELIA_TELEMETRY_ENABLED={new_value}")

    # Write back
    env_path.write_text("\n".join(env_lines) + "\n")

    # Update environment variable for current process
    os.environ["CELIA_TELEMETRY_ENABLED"] = new_value

    # Reload telemetry service consent state
    telemetry.reload_consent()

    # Record consent change in Supabase (always, for audit trail)
    telemetry.track_consent_change(user.id, body.enabled)

    action = "activated" if body.enabled else "deactivated"
    return ConsentResponse(
        telemetry_enabled=body.enabled,
        message=f"Telemetry {action} successfully. {'Anonymized metrics will be sent to improve IC.' if body.enabled else 'No data will be sent.'}",
    )


@router.get("/telemetry/status", response_model=TelemetryStatusResponse)
async def get_telemetry_status(user: User = Depends(get_current_user)):
    """Returns current telemetry consent state."""
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
            telemetry.supabase.table("user_profiles")
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
