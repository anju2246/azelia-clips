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
async def activate_pro(
    user: User = Depends(require_auth),
    authorization: str = Header(None),
):
    """
    Activate beta Pro for the authenticated user.
    Sets tier='pro' and pro_expires_at = now + 90 days in their profiles row.

    Uses the user's JWT so RLS (auth.uid() = id) actually lets the UPDATE land.
    Previously used anon key which silently returned 204 with zero rows affected.
    """
    user_jwt = (authorization or "").replace("Bearer ", "").strip()
    if not user_jwt:
        raise HTTPException(status_code=401, detail="Missing user token")

    pro_expires_at = (datetime.now(timezone.utc) + timedelta(days=BETA_DURATION_DAYS)).isoformat()

    async with httpx.AsyncClient() as client:
        res = await client.patch(
            f"{settings.supabase_url}/rest/v1/profiles",
            params={"id": f"eq.{user.id}"},
            json={"tier": "pro", "pro_expires_at": pro_expires_at},
            headers={
                "apikey": settings.supabase_key,
                "Authorization": f"Bearer {user_jwt}",
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
            detail="Pro activation affected 0 rows — RLS or missing profile row",
        )

    return UpgradeResponse(
        tier="pro",
        pro_expires_at=pro_expires_at,
        telemetry_enabled=True,
        message="¡Pro activado! Tienes 3 meses de acceso completo al IC Cascade.",
    )


@router.get("/upgrade/status")
async def get_upgrade_status(user: User = Depends(optional_auth)):
    """Returns current tier and Pro expiry. Reads directly from Supabase (anon key + RLS)."""
    from supabase import create_client
    from datetime import datetime, timezone

    if not user or not settings.supabase_url or not settings.supabase_key:
        return {"tier": "free", "pro_expires_at": None, "telemetry_enabled": False}

    try:
        sb = create_client(settings.supabase_url, settings.supabase_key)
        # Use user's JWT for RLS-scoped read (anon key is safe here — only reads own row)
        result = sb.table("profiles").select(
            "tier, pro_expires_at, telemetry_consent"
        ).eq("id", user.id).execute()

        if not result.data:
            return {"tier": "free", "pro_expires_at": None, "telemetry_enabled": False}

        row = result.data[0]
        pro_expires_at = row.get("pro_expires_at")

        # Client-side expiry check (DB trigger handles the authoritative enforcement)
        if row["tier"] == "pro" and pro_expires_at:
            expires = datetime.fromisoformat(pro_expires_at)
            if expires < datetime.now(timezone.utc):
                return {"tier": "free", "pro_expires_at": None, "telemetry_enabled": row.get("telemetry_consent", False)}

        return {
            "tier": row["tier"],
            "pro_expires_at": pro_expires_at,
            "telemetry_enabled": row.get("telemetry_consent", False),
        }
    except Exception:
        return {"tier": "free", "pro_expires_at": None, "telemetry_enabled": False}
