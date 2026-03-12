import logging
from typing import Optional
from fastapi import HTTPException, status, Security, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from packages.core.config import settings

security = HTTPBearer()

class User(BaseModel):
    id: str
    email: Optional[str] = None
    role: Optional[str] = None

def verify_supabase_jwt(token: str) -> User:
    """
    Verifies a Supabase-issued JWT by calling the Supabase Auth API.
    No local JWT secret needed — validation is always done server-side by Supabase.
    Returns the parsed User model on success.
    """
    try:
        from supabase import create_client

        if not settings.supabase_url or not settings.supabase_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Server misconfigured: SUPABASE_URL or SUPABASE_KEY is missing."
            )

        sb_client = create_client(settings.supabase_url, settings.supabase_key)
        user_resp = sb_client.auth.get_user(token)

        if not user_resp or not user_resp.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token"
            )

        user = user_resp.user
        return User(
            id=user.id,
            email=user.email,
            role=user.role or "authenticated"
        )

    except HTTPException:
        raise
    except Exception as e:
        error_type = type(e).__name__
        if error_type == 'AuthApiError':
            logging.warning(f"Supabase API rejected token: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Supabase rejected the authentication token"
            )
        logging.error(f"Auth error: {error_type}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal auth error"
        )

async def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)) -> User:
    """
    FastAPI Dependency to get the current authenticated user from the Authorization header.
    Usage in route: async def my_route(user: User = Depends(get_current_user)):
    """
    token = credentials.credentials
    return verify_supabase_jwt(token)


async def require_super_admin(user: User = Depends(get_current_user)) -> User:
    """
    FastAPI Dependency that rejects any request not from a super_admin.
    The role comes from Supabase Auth — validated server-side via API.
    The profiles.role column is the source of truth.
    
    Usage in route: async def admin_route(user: User = Depends(require_super_admin)):
    """
    if user.role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )
    return user
