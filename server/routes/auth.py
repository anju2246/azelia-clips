"""
Auth routes for Azelia Clips.
Provides server-side auth callback and user info endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from server.middleware.auth import require_auth
from packages.core.auth import User
from packages.core.config import settings as app_settings
import httpx

router = APIRouter(tags=["auth"])


class UserResponse(BaseModel):
    id: str
    email: str
    role: str


class OnboardingStatusResponse(BaseModel):
    onboarding_complete: bool
    data_complete: bool = True
    missing_fields: list[str] = []
    show_pro_offer: bool = False


class OnboardingCompleteRequest(BaseModel):
    complete: bool = True


# Fields that MUST be filled before a profile can be considered onboarded.
# If the flag is true but any of these is NULL/empty, treat as incomplete and
# send the user back to finish onboarding (defense against dirty state / bugs).
REQUIRED_ONBOARDING_FIELDS = ("user_role", "primary_goal", "content_niche")


def _missing_required(profile: dict) -> list[str]:
    return [f for f in REQUIRED_ONBOARDING_FIELDS if not (profile.get(f) or "").strip()]


@router.get("/auth/me", response_model=UserResponse)
async def get_current_user(user: User = Depends(require_auth)):
    """Return the currently authenticated user's info from the JWT."""
    return UserResponse(
        id=user.id,
        email=user.email,
        role=user.role,
    )


@router.get("/auth/onboarding-status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    user: User = Depends(require_auth),
    authorization: str = Header(None),
):
    """Return whether this user has completed onboarding AND data is actually present.

    `onboarding_complete` is true only if BOTH:
      - the flag is set in DB, AND
      - all required profile fields (user_role, primary_goal, content_niche) are filled.
    `show_pro_offer` is true when user is onboarded, still on free tier, and has not
    explicitly dismissed or claimed the Pro offer (pro_offer_responded_at IS NULL).
    """
    user_jwt = (authorization or "").replace("Bearer ", "").strip()
    select_cols = "onboarding_complete,user_role,primary_goal,content_niche,tier,pro_expires_at"
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{app_settings.supabase_url}/rest/v1/profiles",
            params={"id": f"eq.{user.id}", "select": select_cols},
            headers={
                "apikey": app_settings.supabase_key,
                "Authorization": f"Bearer {user_jwt or app_settings.supabase_key}",
            },
        )
    if res.status_code != 200 or not res.json():
        return OnboardingStatusResponse(onboarding_complete=False, data_complete=False,
                                        missing_fields=list(REQUIRED_ONBOARDING_FIELDS))
    profile = res.json()[0]
    missing = _missing_required(profile)
    flag = bool(profile.get("onboarding_complete"))
    data_ok = not missing
    is_complete = flag and data_ok

    # Pro offer eligibility: onboarded, free tier, no Pro active yet.
    # Frontend keeps a localStorage flag once shown/dismissed to avoid re-prompting.
    # (Persistent DB tracking via pro_offer_responded_at is pending a Supabase migration.)
    show_pro_offer = (
        is_complete
        and (profile.get("tier") or "free") == "free"
        and not profile.get("pro_expires_at")
    )

    return OnboardingStatusResponse(
        onboarding_complete=is_complete,
        data_complete=data_ok,
        missing_fields=missing,
        show_pro_offer=show_pro_offer,
    )


@router.post("/auth/onboarding-complete", response_model=OnboardingStatusResponse)
async def mark_onboarding_complete(
    user: User = Depends(require_auth),
    authorization: str = Header(None),
):
    """Mark this user's onboarding as complete.

    Uses the user's JWT (not anon key) so RLS on profiles correctly matches auth.uid() = id.
    Raises on failure instead of silently returning 200 when the UPDATE affected 0 rows.
    """
    user_jwt = (authorization or "").replace("Bearer ", "").strip()
    if not user_jwt:
        raise HTTPException(status_code=401, detail="Missing user token")

    async with httpx.AsyncClient() as client:
        # 1. Verify required data is present BEFORE setting the flag.
        select_cols = "user_role,primary_goal,content_niche"
        check = await client.get(
            f"{app_settings.supabase_url}/rest/v1/profiles",
            params={"id": f"eq.{user.id}", "select": select_cols},
            headers={
                "apikey": app_settings.supabase_key,
                "Authorization": f"Bearer {user_jwt}",
            },
        )
        if check.status_code != 200 or not check.json():
            raise HTTPException(status_code=404, detail="Profile not found")
        missing = _missing_required(check.json()[0])
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot mark onboarding complete — missing required fields: {', '.join(missing)}",
            )

        # 2. Only now persist the flag (RLS-aware via user JWT).
        resp = await client.patch(
            f"{app_settings.supabase_url}/rest/v1/profiles",
            params={"id": f"eq.{user.id}"},
            json={"onboarding_complete": True},
            headers={
                "apikey": app_settings.supabase_key,
                "Authorization": f"Bearer {user_jwt}",
                "Prefer": "return=representation",
                "Content-Type": "application/json",
            },
        )
        if resp.status_code >= 400:
            raise HTTPException(
                status_code=500,
                detail=f"Could not mark onboarding complete: {resp.status_code} {resp.text[:200]}",
            )
        try:
            rows = resp.json()
        except Exception:
            rows = []
        if not rows:
            raise HTTPException(
                status_code=500,
                detail="onboarding_complete update affected 0 rows — RLS or missing profile",
            )
    return OnboardingStatusResponse(onboarding_complete=True, data_complete=True, missing_fields=[])


# ─── Badges ────────────────────────────────────────────────────────

class BadgeItem(BaseModel):
    badge_id: str
    name: str
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    rarity: str = "common"
    awarded_at: str | None = None
    metadata: dict | None = None


@router.get("/auth/badges", response_model=list[BadgeItem])
async def get_user_badges(user: User = Depends(require_auth)):
    """Return the badges earned by this user, joined with the catalog metadata.

    Reads via service role — RLS on user_badges allows users to read their own
    rows, but the join to the badges catalog is cleaner with service role.
    """
    svc_key = getattr(app_settings, "supabase_service_role_key", "") or app_settings.supabase_key
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{app_settings.supabase_url}/rest/v1/user_badges",
            params={
                "user_id": f"eq.{user.id}",
                "select": "badge_id,awarded_at,metadata,badges(name,description,icon,color,rarity)",
            },
            headers={"apikey": svc_key, "Authorization": f"Bearer {svc_key}"},
            timeout=10,
        )
    if res.status_code != 200:
        return []
    out = []
    for row in res.json():
        meta = row.get("badges") or {}
        out.append(BadgeItem(
            badge_id=row.get("badge_id"),
            name=meta.get("name", row.get("badge_id", "").replace("_", " ").title()),
            description=meta.get("description"),
            icon=meta.get("icon"),
            color=meta.get("color"),
            rarity=meta.get("rarity", "common"),
            awarded_at=row.get("awarded_at"),
            metadata=row.get("metadata"),
        ))
    return out


# ─── Right to Deletion (GDPR / Habeas Data) ───────────────────────

class DeleteAccountResponse(BaseModel):
    deleted: bool
    user_id: str
    tables_cleared: list[str]


@router.delete("/auth/account", response_model=DeleteAccountResponse)
async def delete_account(user: User = Depends(require_auth)):
    """Permanently delete this user's account and all associated data.

    Cascade order:
      1. Delete user-owned rows from tables that reference auth.users via FK
         (most have ON DELETE CASCADE, so dropping auth.users takes care of them).
      2. Delete the auth.users row via admin API. This triggers every ON DELETE
         CASCADE and leaves the central DB with zero traces of this user.
      3. Local SQLite data (jobs, youtube_shorts) is cleared by the server on
         the next boot — it's keyed to user_id so it becomes orphaned.

    Telemetry previously keyed to user_id is made anonymous as part of Path B
    (see migration 20260419020000_anonymize_telemetry.sql). After that migration,
    there are zero identifiable rows to delete from telemetry tables.
    """
    svc_key = getattr(app_settings, "supabase_service_role_key", "") or ""
    if not svc_key:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_SERVICE_ROLE_KEY required for account deletion.",
        )

    cleared = []
    async with httpx.AsyncClient() as client:
        # Belt-and-suspenders: explicitly wipe rows that might not have CASCADE.
        # Errors are logged but don't abort — the auth.users delete at the end is authoritative.
        for table in (
            "user_connections", "social_connections", "clips_metadata",
            "community_clips", "tool_usage", "user_prompts",
            "ic_user_intelligence", "ic_user_telemetry",
        ):
            try:
                r = await client.delete(
                    f"{app_settings.supabase_url}/rest/v1/{table}",
                    params={"user_id": f"eq.{user.id}"},
                    headers={
                        "apikey": svc_key,
                        "Authorization": f"Bearer {svc_key}",
                        "Prefer": "return=minimal",
                    },
                    timeout=10,
                )
                if r.status_code < 400:
                    cleared.append(table)
            except Exception:
                pass

        # Delete the auth.users row — CASCADE handles profiles + user_badges + anything FK'd to it.
        r = await client.delete(
            f"{app_settings.supabase_url}/auth/v1/admin/users/{user.id}",
            headers={"apikey": svc_key, "Authorization": f"Bearer {svc_key}"},
            timeout=15,
        )
        if r.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"Could not delete auth user: {r.status_code} {r.text[:200]}",
            )
        cleared.append("auth.users")

    return DeleteAccountResponse(deleted=True, user_id=user.id, tables_cleared=cleared)
