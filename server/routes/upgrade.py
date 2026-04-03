"""
Upgrade Routes — Free → Pro activation.

POST /api/upgrade/pro
  - Sets tier='pro' and pro_expires_at = now() + 3 months
  - Activates telemetry consent (the tradeoff: IC data for Pro access)
  - Idempotent: safe to call again if already Pro
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from pathlib import Path
import os

from server.middleware.auth import require_auth
from packages.core.auth import User
from packages.core.services.telemetry import telemetry
from packages.core.config import settings
from supabase import create_client

router = APIRouter()


def _get_service_client():
    """Returns a Supabase client with service role (bypasses RLS)."""
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not service_key or not settings.supabase_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Upgrade service not available"
        )
    return create_client(settings.supabase_url, service_key)


class UpgradeResponse(BaseModel):
    tier: str
    pro_expires_at: str
    telemetry_enabled: bool
    message: str


@router.post("/upgrade/pro", response_model=UpgradeResponse)
async def activate_pro(user: User = Depends(require_auth)):
    """
    Activate Pro tier for the authenticated user.

    Tradeoff: Pro access (IC Cascade — market intelligence signals) in exchange
    for anonymous telemetry consent. User explicitly accepts this by clicking
    the single CTA button in the upgrade card.

    - Sets tier = 'pro'
    - Sets pro_expires_at = now() + 90 days (beta period)
    - Activates telemetry: updates profiles.telemetry_consent + .env + reloads service
    - Idempotent: if already Pro, refreshes expiry and returns current state
    """
    sb = _get_service_client()

    expires_at = datetime.now(timezone.utc) + timedelta(days=90)
    expires_iso = expires_at.isoformat()

    # Update profiles: tier + expiry
    result = sb.table("profiles").update({
        "tier": "pro",
        "pro_expires_at": expires_iso,
        "telemetry_consent": True,
        "telemetry_consent_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", user.id).execute()

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to activate Pro"
        )

    # Activate telemetry in .env + reload service
    env_path = Path(".env")
    env_lines = env_path.read_text().splitlines() if env_path.exists() else []
    found = False
    for i, line in enumerate(env_lines):
        if line.startswith("AZELIA_TELEMETRY_ENABLED"):
            env_lines[i] = "AZELIA_TELEMETRY_ENABLED=true"
            found = True
            break
    if not found:
        env_lines.append("AZELIA_TELEMETRY_ENABLED=true")
    env_path.write_text("\n".join(env_lines) + "\n")
    os.environ["AZELIA_TELEMETRY_ENABLED"] = "true"
    telemetry.reload_consent()

    # Audit trail + backfill historical data
    telemetry.track_consent_change(user.id, consented=True)

    import threading
    from server.routes.telemetry_routes import _backfill_sqlite_history
    threading.Thread(target=_backfill_sqlite_history, args=(user.id,), daemon=False).start()

    return UpgradeResponse(
        tier="pro",
        pro_expires_at=expires_iso,
        telemetry_enabled=True,
        message="¡Pro activado! Ahora tienes acceso a IC Cascade — inteligencia de mercado en tiempo real.",
    )


@router.get("/upgrade/status")
async def get_upgrade_status(user: User = Depends(require_auth)):
    """Returns current tier and Pro expiry for the authenticated user."""
    sb = _get_service_client()

    result = sb.table("profiles").select(
        "tier, pro_expires_at, telemetry_consent"
    ).eq("id", user.id).execute()

    if not result.data:
        return {"tier": "free", "pro_expires_at": None, "telemetry_enabled": False}

    row = result.data[0]
    pro_expires_at = row.get("pro_expires_at")

    # Auto-downgrade if Pro expired
    if row["tier"] == "pro" and pro_expires_at:
        expires = datetime.fromisoformat(pro_expires_at)
        if expires < datetime.now(timezone.utc):
            sb.table("profiles").update({"tier": "free"}).eq("id", user.id).execute()
            return {"tier": "free", "pro_expires_at": None, "telemetry_enabled": row.get("telemetry_consent", False)}

    return {
        "tier": row["tier"],
        "pro_expires_at": pro_expires_at,
        "telemetry_enabled": row.get("telemetry_consent", False),
    }
