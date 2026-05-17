"""Per-user encrypted settings store.

Each authenticated user has their own `data/users/{user_id}/secrets.env`
file containing their provider API keys, model selections, podcast
metadata, and anything else that should be isolated between tenants
sharing the same Azelia installation.

Values are encrypted at rest using the Fernet helper in
`packages.core.crypto`. The encryption key itself lives in the global
`.env` (`AZELIA_ENCRYPTION_KEY`); without it, values are stored in
plaintext (the helper falls back gracefully — a warning is logged).

System-level configuration (Supabase URL/anon key, CORS origins, bind
host, encryption key itself) stays in the global `.env` and is shared
across users.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from pathlib import Path

from packages.core.config import settings as system_settings
from packages.core.crypto import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)

USER_DATA_ROOT = Path("data/users")

# Keys whose values are sensitive enough to encrypt before persisting.
# Non-secret keys (model names, provider order) are written in clear so
# admins can sanity-check files without the master key handy.
_SECRET_KEYS = frozenset(
    {
        "GROQ_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "TRANSCRIPT_SUPABASE_KEY",
    }
)

# All keys recognised by the per-user store. Anything else passed in is
# silently dropped — prevents arbitrary writes to the file.
_ALLOWED_KEYS = frozenset(
    {
        "PODCAST_NAME",
        "PODCAST_DIR",
        "AI_PROVIDER_ORDER",
        "GROQ_API_KEY",
        "GROQ_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_MODEL",
        "GOOGLE_API_KEY",
        "GOOGLE_MODEL",
        "TRANSCRIPT_SUPABASE_URL",
        "TRANSCRIPT_SUPABASE_KEY",
    }
)

# Fallback chain for each setting: if the user has not set a value, fall
# back to the system-wide one (preserves single-user installations that
# still keep keys in the global `.env`).
_SYSTEM_FALLBACKS: dict[str, str] = {
    "PODCAST_NAME": "podcast_name",
    "PODCAST_DIR": "podcast_dir",
    "AI_PROVIDER_ORDER": "ai_provider_order",
    "GROQ_API_KEY": "groq_api_key",
    "GROQ_MODEL": "groq_model",
    "OPENAI_API_KEY": "openai_api_key",
    "OPENAI_MODEL": "openai_model",
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "ANTHROPIC_MODEL": "anthropic_model",
    "GOOGLE_API_KEY": "google_api_key",
    "GOOGLE_MODEL": "google_model",
    "TRANSCRIPT_SUPABASE_URL": "transcript_supabase_url",
    "TRANSCRIPT_SUPABASE_KEY": "transcript_supabase_key",
}


def _validate_user_id(user_id: str) -> str:
    """Reject anything that could traverse out of `data/users/`."""
    if not user_id or "/" in user_id or "\\" in user_id or ".." in user_id:
        raise ValueError(f"Invalid user_id for filesystem path: {user_id!r}")
    return user_id


def _user_dir(user_id: str) -> Path:
    return USER_DATA_ROOT / _validate_user_id(user_id)


def _secrets_path(user_id: str) -> Path:
    return _user_dir(user_id) / "secrets.env"


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip()
    return out


def _serialize(values: dict[str, str]) -> str:
    """Stable serialization — sorted keys, one per line."""
    return "".join(f"{k}={values[k]}\n" for k in sorted(values))


def read_user_settings(user_id: str) -> dict[str, str]:
    """Return the user's settings (decrypted). Missing keys fall back
    to the system-wide value via `effective_setting`. Use this directly
    only when you specifically want the user-level overrides; otherwise
    prefer `effective_setting` for individual reads.
    """
    raw = _parse_env_file(_secrets_path(user_id))
    decoded: dict[str, str] = {}
    for k, v in raw.items():
        if k not in _ALLOWED_KEYS:
            continue
        decoded[k] = decrypt_token(v) if k in _SECRET_KEYS else v
    return decoded


def effective_setting(user_id: str, key: str) -> str:
    """User override if present and non-empty, otherwise the system
    default from the global `.env`. `key` is upper-snake (e.g. GROQ_API_KEY).
    """
    user_vals = read_user_settings(user_id)
    user_val = user_vals.get(key)
    if user_val:
        return user_val
    sys_attr = _SYSTEM_FALLBACKS.get(key)
    if sys_attr:
        sys_val = getattr(system_settings, sys_attr, "")
        return str(sys_val) if sys_val else ""
    return ""


def write_user_settings(user_id: str, updates: dict[str, str | None]) -> dict[str, str]:
    """Merge `updates` into the user's settings file. Pass `""` (empty
    string) to clear a key, `None` to leave it unchanged.

    Returns the post-write user-level values (decrypted).
    """
    path = _secrets_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    current_raw = _parse_env_file(path)
    for key, val in updates.items():
        if val is None or key not in _ALLOWED_KEYS:
            continue
        if val == "":
            current_raw.pop(key, None)
            continue
        current_raw[key] = encrypt_token(val) if key in _SECRET_KEYS else val

    # Atomic write via tmp + replace — avoids torn files under concurrent updates.
    tmp = path.with_suffix(".env.tmp")
    tmp.write_text(_serialize(current_raw), encoding="utf-8")
    os.replace(tmp, path)
    # Tighten perms: only the owner of the process should read these.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    return read_user_settings(user_id)


def effective_settings_dict(user_id: str, keys: Iterable[str] | None = None) -> dict[str, str]:
    """Bulk fetch with system fallback applied. Useful for assembling
    the SettingsResponse and for routes that need several values at once.
    """
    if keys is None:
        keys = _ALLOWED_KEYS
    return {k: effective_setting(user_id, k) for k in keys}
