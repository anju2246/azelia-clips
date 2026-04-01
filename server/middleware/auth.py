from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from packages.core.auth import verify_supabase_jwt, User
from packages.core.config import settings
from typing import Optional

security = HTTPBearer(auto_error=False)

def require_auth(credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
    """
    FastAPI dependency to extract and validate the Supabase JWT.
    Returns the decoded token as a User object on success.
    Raises HTTPException 401 on failure.
    """
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization")
    token = credentials.credentials
    user = verify_supabase_jwt(token)
    return user

def optional_auth(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Optional[User]:
    """
    Auth dependency that is optional.
    - If credentials are provided, validates the JWT (throws 401 if invalid).
    - If no credentials, returns None. No fake users.
    """
    if credentials is None:
        return None

    return verify_supabase_jwt(credentials.credentials)

def require_onboarding(credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
    """
    FastAPI dependency that validates auth AND checks onboarding completion.
    Returns 428 Precondition Required if user hasn't completed onboarding
    (content_niche is NULL in their profile).
    """
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization")

    token = credentials.credentials
    user = verify_supabase_jwt(token)

    try:
        from supabase import create_client
        sb = create_client(settings.supabase_url, settings.supabase_key)
        res = sb.table("profiles").select("content_niche").eq("id", user.id).execute()

        if res.data and res.data[0].get("content_niche") is None:
            raise HTTPException(
                status_code=428,
                detail="Onboarding required. Please complete your profile setup first."
            )
    except HTTPException:
        raise
    except Exception:
        pass  # If profile check fails, don't block the user

    return user
