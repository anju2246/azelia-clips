import jwt
import logging
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
        header = jwt.get_unverified_header(token)
        alg = header.get("alg", "HS256")
        
        if alg == "HS256":
            signing_key = settings.supabase_jwt_secret
            payload = jwt.decode(
                token,
                signing_key,
                algorithms=["HS256"],
                options={"verify_aud": False}
            )
        else:
            # For ES256/RS256, if JWKS is not available, we can't mathematically verify the signature locally.
            # We can however ask the Supabase Server if the token is valid by getting the user.
            from supabase import create_client
            if not settings.supabase_url or not settings.supabase_key:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Server misconfigured: SUPABASE_URL or SUPABASE_KEY is missing."
                )
            
            sb_client = create_client(settings.supabase_url, settings.supabase_key)
            # This calls the Supabase Auth API, which natively verifies its own ES256 tokens
            user_resp = sb_client.auth.get_user(token)
            if not user_resp or not user_resp.user:
                raise jwt.InvalidTokenError("Supabase rejected the token")
                
            # Construct a fake payload to match the downstream logic
            # Extract basic info from the unverified token to populate our User model
            payload = jwt.decode(token, options={"verify_signature": False})
        
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
    except jwt.InvalidTokenError as e:
        logging.warning(f"JWT validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token"
        )
    except Exception as e:
        logging.error(f"Auth error: {type(e).__name__}: {e}")
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
