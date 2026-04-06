"""
Auth routes for Azelia Clips.
Provides server-side auth callback and user info endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
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


class OnboardingCompleteRequest(BaseModel):
    complete: bool = True


@router.get("/auth/me", response_model=UserResponse)
async def get_current_user(user: User = Depends(require_auth)):
    """Return the currently authenticated user's info from the JWT."""
    return UserResponse(
        id=user.id,
        email=user.email,
        role=user.role,
    )


@router.get("/auth/onboarding-status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(user: User = Depends(require_auth)):
    """Return whether this user has completed onboarding."""
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{app_settings.supabase_url}/rest/v1/profiles",
            params={"id": f"eq.{user.id}", "select": "onboarding_complete"},
            headers={
                "apikey": app_settings.supabase_key,
                "Authorization": f"Bearer {app_settings.supabase_key}",
            },
        )
    if res.status_code != 200 or not res.json():
        return OnboardingStatusResponse(onboarding_complete=False)
    return OnboardingStatusResponse(
        onboarding_complete=res.json()[0].get("onboarding_complete", False)
    )


@router.post("/auth/onboarding-complete", response_model=OnboardingStatusResponse)
async def mark_onboarding_complete(user: User = Depends(require_auth)):
    """Mark this user's onboarding as complete."""
    async with httpx.AsyncClient() as client:
        await client.patch(
            f"{app_settings.supabase_url}/rest/v1/profiles",
            params={"id": f"eq.{user.id}"},
            json={"onboarding_complete": True},
            headers={
                "apikey": app_settings.supabase_key,
                "Authorization": f"Bearer {app_settings.supabase_key}",
                "Prefer": "return=minimal",
            },
        )
    return OnboardingStatusResponse(onboarding_complete=True)
