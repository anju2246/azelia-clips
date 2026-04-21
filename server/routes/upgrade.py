"""
Upgrade Routes — Free → Pro activation.

Beta Pro model (effective 2026-04-20):
- During the BETA, users have a 3-month REDEMPTION WINDOW to claim Pro.
- Claiming Pro during that window grants 12 MONTHS of full access.
- Users who don't redeem inside the window remain on Free; Pro
  pricing activates 3 months after the redemption window closes.

Redemption window start is configured via the BETA_START constant
below. When the actual launch date is confirmed, update that single
value (see LAUNCH_CHECKLIST.md §7). Everything else derives from it.
"""

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel
from typing import Optional
import httpx
from server.middleware.auth import require_auth, optional_auth
from packages.core.auth import User
from packages.core.config import settings

router = APIRouter()

# Duration of Pro access once redeemed (12 months).
PRO_DURATION_DAYS = 365

# Length of the window within which users can redeem Pro (3 months).
REDEMPTION_WINDOW_DAYS = 90

# Placeholder start of the public redemption window. UPDATE this when
# the Show HN launch date is locked. Before this date the endpoint
# still accepts redemptions (helpful for pre-launch dogfooding); after
# BETA_START + REDEMPTION_WINDOW_DAYS the endpoint returns 410.
BETA_START = datetime(2026, 5, 6, tzinfo=timezone.utc)


def _redemption_window_open(now: datetime) -> bool:
    """Inside the redemption window a POST /upgrade/pro is allowed."""
    closes = BETA_START + timedelta(days=REDEMPTION_WINDOW_DAYS)
    return now <= closes


class UpgradeResponse(BaseModel):
    tier: str
    pro_expires_at: Optional[str]
    telemetry_enabled: bool
    message: str


@router.post("/upgrade/pro", response_model=UpgradeResponse)
async def activate_pro(user: User = Depends(require_auth)):
    """
    Activate beta Pro for the authenticated user.

    Grants 12 months of Pro access when the user redeems inside the
    3-month redemption window. Returns 410 Gone once the window has
    closed (caller should show a "redemption window closed" UI).

    Uses the service role key because profiles.tier / pro_expires_at are
    guarded by the enforce_profile_column_restrictions trigger (see migration
    20260403000002). The trigger raises unless auth.uid() IS NULL — which it
    is when service role calls. user.id is trusted here because require_auth
    already verified the caller's JWT server-side.
    """
    now = datetime.now(timezone.utc)
    if not _redemption_window_open(now):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="The Pro redemption window has closed.",
        )

    svc_key = getattr(settings, "supabase_service_role_key", "") or ""
    if not svc_key:
        raise HTTPException(
            status_code=500,
            detail="Server misconfiguration: SUPABASE_SERVICE_ROLE_KEY is required for Pro activation.",
        )

    pro_expires_at = (now + timedelta(days=PRO_DURATION_DAYS)).isoformat()

    async with httpx.AsyncClient() as client:
        res = await client.patch(
            f"{settings.supabase_url}/rest/v1/profiles",
            params={"id": f"eq.{user.id}"},
            json={"tier": "pro", "pro_expires_at": pro_expires_at},
            headers={
                "apikey": svc_key,
                "Authorization": f"Bearer {svc_key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
        )

    if res.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not activate Pro: {res.status_code} {res.text[:200]}",
        )
    try:
        rows = res.json()
    except Exception:
        rows = []
    if not rows:
        raise HTTPException(
            status_code=500,
            detail="Pro activation affected 0 rows — profile missing for user.id",
        )

    return UpgradeResponse(
        tier="pro",
        pro_expires_at=pro_expires_at,
        telemetry_enabled=True,
        message="Pro activated — 12 months of full IC Cascade access.",
    )


@router.get("/upgrade/redemption")
async def get_redemption_info():
    """Public endpoint (no auth required) describing the beta redemption window.

    Used by the UI to show 'Pro redemption window — X days left' copy and to
    disable the activate button once the window closes.
    """
    now = datetime.now(timezone.utc)
    closes = BETA_START + timedelta(days=REDEMPTION_WINDOW_DAYS)
    days_remaining = max(0, (closes - now).days)
    return {
        "beta_start": BETA_START.isoformat(),
        "window_days": REDEMPTION_WINDOW_DAYS,
        "closes_at": closes.isoformat(),
        "days_remaining": days_remaining,
        "is_open": now <= closes,
        "pro_duration_days": PRO_DURATION_DAYS,
    }


@router.get("/upgrade/status")
async def get_upgrade_status(user: User = Depends(optional_auth)):
    """Returns current tier and Pro expiry for the authenticated user.

    Reads via the service role key because the anon client is blocked from
    reading arbitrary profiles.* fields under RLS. user.id is trusted — it
    came from a server-verified JWT (optional_auth decodes + validates).
    """
    from datetime import datetime, timezone
    import httpx as _httpx

    if not user or not settings.supabase_url:
        return {"tier": "free", "pro_expires_at": None, "telemetry_enabled": False}

    svc_key = getattr(settings, "supabase_service_role_key", "") or settings.supabase_key

    try:
        async with _httpx.AsyncClient() as client:
            r = await client.get(
                f"{settings.supabase_url}/rest/v1/profiles",
                params={
                    "id": f"eq.{user.id}",
                    "select": "tier,pro_expires_at,telemetry_consent",
                },
                headers={"apikey": svc_key, "Authorization": f"Bearer {svc_key}"},
                timeout=10,
            )
        if r.status_code != 200:
            return {"tier": "free", "pro_expires_at": None, "telemetry_enabled": False}
        data = r.json()
        if not data:
            return {"tier": "free", "pro_expires_at": None, "telemetry_enabled": False}

        row = data[0]
        pro_expires_at = row.get("pro_expires_at")

        # Client-side expiry check (DB trigger handles authoritative enforcement).
        if row.get("tier") == "pro" and pro_expires_at:
            try:
                expires = datetime.fromisoformat(pro_expires_at.replace("Z", "+00:00"))
                if expires < datetime.now(timezone.utc):
                    return {
                        "tier": "free",
                        "pro_expires_at": None,
                        "telemetry_enabled": row.get("telemetry_consent", False),
                    }
            except Exception:
                pass

        return {
            "tier": row.get("tier", "free"),
            "pro_expires_at": pro_expires_at,
            "telemetry_enabled": row.get("telemetry_consent", False),
        }
    except Exception:
        return {"tier": "free", "pro_expires_at": None, "telemetry_enabled": False}
