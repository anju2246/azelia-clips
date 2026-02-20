from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from packages.core.auth import verify_supabase_jwt
from packages.core.config import settings
from typing import Optional

security = HTTPBearer(auto_error=False)

def require_auth(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """
    FastAPI dependency to extract and validate the Supabase JWT.
    Returns the decoded token payload on success.
    Raises HTTPException 401 on failure.
    """
    if credentials is None:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization")
    token = credentials.credentials
    user_payload = verify_supabase_jwt(token)
    return user_payload

def optional_auth(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Optional[dict]:
    """
    Auth dependency that skips validation in local dev (when SUPABASE_JWT_SECRET is not set).
    In production, validates the JWT normally.
    """
    if not settings.supabase_jwt_secret:
        return {"sub": "dev-user", "role": "authenticated", "dev_mode": True}
    if credentials is None:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization")
    return verify_supabase_jwt(credentials.credentials)
