"""
Upgrade Routes — Free → Pro activation.

The actual upgrade logic lives in a Supabase Edge Function (upgrade-pro),
running on Supabase's infrastructure. The service_role key never touches
this repo. Business rules (beta cutoff, consent enforcement) are enforced
at two layers:
  1. Edge Function (Supabase servers)
  2. DB trigger trg_enforce_pro_upgrade (Supabase DB)

This file is just a thin proxy that forwards the user's JWT to the Edge Function.
"""

import os
import urllib.request
import json
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from typing import Optional
from server.middleware.auth import require_auth, optional_auth
from packages.core.auth import User
from packages.core.config import settings

router = APIRouter()

EDGE_FUNCTION_URL = f"{settings.supabase_url}/functions/v1/upgrade-pro"


class UpgradeResponse(BaseModel):
    tier: str
    pro_expires_at: Optional[str]
    telemetry_enabled: bool
    message: str


@router.post("/upgrade/pro", response_model=UpgradeResponse)
async def activate_pro(request: Request, user: User = Depends(require_auth)):
    """
    Proxy to Supabase Edge Function 'upgrade-pro'.
    Business logic (beta cutoff, consent, service_role) lives in Supabase — not here.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")

    req = urllib.request.Request(
        EDGE_FUNCTION_URL,
        method="POST",
        headers={
            "Authorization": auth_header,
            "Content-Type": "application/json",
            "apikey": settings.supabase_key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
            return UpgradeResponse(**body)
    except urllib.error.HTTPError as e:
        body = json.loads(e.read())
        raise HTTPException(status_code=e.code, detail=body.get("error", "Error activando Pro"))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upgrade service unavailable: {e}")


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
