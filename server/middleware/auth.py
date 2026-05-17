"""Local-only auth for Azelia Clips MVP.

Self-hosted, single-user, bound to 127.0.0.1 by default.
Anyone who can reach localhost is the owner — no real authentication.

The auth dependencies are kept as no-ops so route signatures remain unchanged
and we can re-introduce real auth later without touching every endpoint.
"""

from pydantic import BaseModel


class User(BaseModel):
    """Stub user object. Single local owner."""

    id: str = "local"
    email: str = "local@azelia"
    role: str = "owner"


LOCAL_USER = User()


def require_auth() -> User:
    """No-op auth: always returns the local owner."""
    return LOCAL_USER


def optional_auth() -> User:
    """No-op auth: always returns the local owner."""
    return LOCAL_USER


def require_auth_flexible() -> User:
    """No-op auth: always returns the local owner.

    Kept for backward-compat with routes that previously accepted either
    a Bearer token or a `?token=` query param (e.g. <video src>).
    """
    return LOCAL_USER


def require_onboarding() -> User:
    """No-op auth: always returns the local owner.

    Real onboarding gating (e.g. "has at least one LLM provider configured")
    lives in the frontend now — the wizard guides the user before letting
    them reach the dashboard.
    """
    return LOCAL_USER
