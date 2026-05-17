"""Token encryption utilities using Fernet symmetric encryption.

Local-first MVP: if AZELIA_ENCRYPTION_KEY isn't set, we auto-generate a
random key on first use and persist it to ~/.azelia/data/encryption.key
(mode 600). That way OAuth tokens are encrypted at rest by default —
no setup required from the user, no plaintext fallback either.
"""

import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _key_file() -> Path:
    try:
        from packages.core.config import settings
        return settings.data_dir / "encryption.key"
    except Exception:
        return Path.home() / ".azelia" / "data" / "encryption.key"


def _load_or_create_key() -> bytes:
    """Read AZELIA_ENCRYPTION_KEY env var, or auto-generate + persist."""
    env_key = os.environ.get("AZELIA_ENCRYPTION_KEY")
    if env_key:
        return env_key.encode() if isinstance(env_key, str) else env_key

    key_path = _key_file()
    if key_path.exists():
        return key_path.read_bytes().strip()

    key_path.parent.mkdir(parents=True, exist_ok=True)
    new_key = Fernet.generate_key()
    key_path.write_bytes(new_key)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    logger.info("Generated new encryption key at %s", key_path)
    return new_key


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_key())
    return _fernet


def encrypt_token(token: str) -> str:
    if not token:
        return token
    return _get_fernet().encrypt(token.encode()).decode()


def decrypt_token(token: str) -> str:
    """Decrypt a token. Returns as-is if the token isn't encrypted
    (backwards-compat with plaintext tokens from earlier installs)."""
    if not token:
        return token
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except (InvalidToken, Exception):
        return token
