"""
Token encryption utilities using Fernet symmetric encryption.
Requires AZELIA_ENCRYPTION_KEY env var (generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
"""
import os
import logging
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet | None:
    global _fernet
    if _fernet is None:
        key = os.environ.get("AZELIA_ENCRYPTION_KEY")
        if not key:
            logger.warning("AZELIA_ENCRYPTION_KEY not set — tokens stored unencrypted")
            return None
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt_token(token: str) -> str:
    """Encrypt a token. Returns original if no key configured."""
    f = _get_fernet()
    if f is None or not token:
        return token
    return f.encrypt(token.encode()).decode()


def decrypt_token(token: str) -> str:
    """Decrypt a token. Returns original if no key or token is legacy plaintext."""
    f = _get_fernet()
    if f is None or not token:
        return token
    try:
        return f.decrypt(token.encode()).decode()
    except (InvalidToken, Exception):
        # Legacy plaintext token — return as-is for backwards compatibility
        return token
