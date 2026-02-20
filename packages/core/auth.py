import jwt
from typing import Dict, Any
from fastapi import HTTPException, status
from packages.core.config import settings

def verify_supabase_jwt(token: str) -> Dict[str, Any]:
    """
    Verifies a Supabase-issued JWT and returns the parsed payload.
    Extracts the user ID, role, and standard claims.
    """
    if not settings.supabase_jwt_secret:
        # If running locally without a secret configured, fail secure
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
        return payload
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
