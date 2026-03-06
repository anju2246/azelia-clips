import jwt
from typing import Dict, Any, Optional
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
    Verifies a Supabase-issued JWT and returns the parsed User model.
    """
    if not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfigured: SUPABASE_JWT_SECRET is missing."
        )

    try:
        # Supabase uses HS256 for JWT signing
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            options={"verify_aud": False} # Sometimes aud is custom or missing
        )
        
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token payload missing required 'sub' claim"
            )
            
        return User(
            id=user_id,
            email=payload.get("email"),
            role=payload.get("role")
        )
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token"
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
    The role comes from the JWT, which is signed by Supabase's JWT secret.
    It cannot be forged — the user_profiles.role column is the source of truth.
    
    Usage in route: async def admin_route(user: User = Depends(require_super_admin)):
    """
    if user.role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )
    return user
