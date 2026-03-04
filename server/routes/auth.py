"""
Auth routes for Celia Clips.
Provides server-side auth callback and user info endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from server.middleware.auth import require_auth
from packages.core.auth import User

router = APIRouter(tags=["auth"])


class UserResponse(BaseModel):
    id: str
    email: str
    role: str


@router.get("/auth/me", response_model=UserResponse)
async def get_current_user(user: User = Depends(require_auth)):
    """Return the currently authenticated user's info from the JWT."""
    return UserResponse(
        id=user.id,
        email=user.email,
        role=user.role,
    )
