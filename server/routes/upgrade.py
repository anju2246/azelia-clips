"""
Upgrade Routes — Free → Pro activation.

Beta Pro: free 3-month trial. No payment required.
Writes directly to Supabase REST API using anon key (RLS must allow user to update own row).
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

BETA_DURATION_DAYS = 90  # 3 months


class UpgradeResponse(BaseModel):
    tier: str
    pro_expires_at: Optional[str]
    telemetry_enabled: bool
    message: str


@router.post("/upgrade/pro", response_model=UpgradeResponse)
async def activate_pro(user: User = Depends(require_auth)):
    """
    Activate beta Pro for the authenticated user.
    Sets tier='pro' and pro_expires_at = now + 90 days in their profiles row.

    Uses the service role key because profiles.tier / pro_expires_at are
    guarded by the enforce_profile_column_restrictions trigger (see migration
    20260403000002). The trigger raises unless auth.uid() IS NULL — which it
    is when service role calls. user.id is trusted here because require_auth
    already verified the caller's JWT server-side.
    """
    svc_key = getattr(settings, "supabase_service_role_key", "") or ""
    if not svc_key:
        raise HTTPException(
            status_code=500,
            detail="Server misconfiguration: SUPABASE_SERVICE_ROLE_KEY is required for Pro activation.",
        )

    pro_expires_at = (datetime.now(timezone.utc) + timedelta(days=BETA_DURATION_DAYS)).isoformat()

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
        message="Pro activated — 3 months of full IC Cascade access.",
    )


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
