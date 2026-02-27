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
    Auth dependency that is truly optional for local-first usage.
    - If credentials are provided, validates the JWT.
    - If no credentials are provided, returns a dev user (local mode).
    """
    if credentials is None:
        return User(id="dev-user", email="dev@local", role="authenticated")
    return verify_supabase_jwt(credentials.credentials)
