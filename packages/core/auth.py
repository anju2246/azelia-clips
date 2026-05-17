"""Compatibility shim for packages.core.auth (SaaS era).

The MVP single-user model lives in server/middleware/auth.py — re-export
from here so existing imports (`from packages.core.auth import User`,
`verify_supabase_jwt`) keep compiling without per-call gating.

Anything that called verify_supabase_jwt(token) now just gets back the
local owner User regardless of the token value.
"""

from server.middleware.auth import LOCAL_USER, User


def verify_supabase_jwt(_token: str) -> User:
    """No-op: single-user local mode — any token resolves to the local owner."""
    return LOCAL_USER


__all__ = ["User", "verify_supabase_jwt", "LOCAL_USER"]
