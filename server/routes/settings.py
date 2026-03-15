"""
Server Routes — Application Settings
"""

import os
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from server.models import SettingsResponse, UpdateSettingsRequest
from packages.core.config import settings
from packages.core.services.model_registry import model_registry
from server.middleware.auth import require_auth
from packages.core.auth import User

router = APIRouter()


def _get_allowed_roots() -> list[Path]:
    """Platform-aware allowed roots for filesystem browsing."""
    home = Path(os.path.expanduser("~")).resolve()
    roots = [home]

    if sys.platform == "darwin":
        volumes = Path("/Volumes")
        if volumes.exists():
            roots.append(volumes.resolve())
    elif sys.platform == "linux":
        for mount in ["/mnt", "/media", "/run/media"]:
            p = Path(mount)
            if p.exists():
                roots.append(p.resolve())
    elif sys.platform == "win32":
        import string
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:\\")
            if drive.exists():
                roots.append(drive)

    return roots


API_KEY_PREFIXES = {
    "groq_api_key": ("gsk_", "Groq keys start with 'gsk_'"),
    "openai_api_key": ("sk-", "OpenAI keys start with 'sk-'"),
    "anthropic_api_key": ("sk-ant-", "Anthropic keys start with 'sk-ant-'"),
}


def _validate_api_key(field: str, value: str) -> str | None:
    """Validate API key format. Returns error message or None."""
    if not value or not value.strip():
        return None  # Empty is OK (clearing a key)
    value = value.strip()
    if len(value) < 10:
        return f"API key too short (got {len(value)} chars)"
    if field in API_KEY_PREFIXES:
        prefix, msg = API_KEY_PREFIXES[field]
        if not value.startswith(prefix):
            return msg
    return None


def mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return ""
    return f"{key[:4]}...{key[-4:]}"


def _is_masked(value: str) -> bool:
    """Check if a value is a masked placeholder (e.g. 'eyJh...lLBU') that should not be saved."""
    return not value or '...' in value or value == '********'


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(user: User = Depends(require_auth)):
    """Get current application settings."""
    provider_order = [p.strip() for p in settings.ai_provider_order.split(',')] if settings.ai_provider_order else ["groq", "openai", "anthropic", "vertex"]
    return SettingsResponse(
        podcast_name=settings.podcast_name or "",
        podcast_dir=str(settings.podcast_dir) if settings.podcast_dir else "",
        ai_provider_order=provider_order,
        groq_api_key=mask_key(settings.groq_api_key),
        groq_model=settings.groq_model,
        openai_api_key=mask_key(settings.openai_api_key),
        openai_model=settings.openai_model,
        anthropic_api_key=mask_key(settings.anthropic_api_key),
        anthropic_model=settings.anthropic_model,
        gcp_project_id=settings.gcp_project_id,
        vertex_model=settings.vertex_model,
        transcript_supabase_url=settings.transcript_supabase_url,
        transcript_supabase_key=mask_key(settings.transcript_supabase_key),
        generate_teasers=settings.generate_teasers
    )

@router.post("/settings", response_model=SettingsResponse)
async def update_settings(req: UpdateSettingsRequest, user: User = Depends(require_auth)):
    """Update settings in .env file."""
    # Validate API keys before saving
    validation_errors = []
    for field in ["groq_api_key", "openai_api_key", "anthropic_api_key"]:
        value = getattr(req, field, None)
        if value is not None:
            error = _validate_api_key(field, value)
            if error:
                validation_errors.append(f"{field}: {error}")

    if validation_errors:
        raise HTTPException(status_code=422, detail="; ".join(validation_errors))

    env_path = Path(".env")

    # Read existing env
    env_content = {}
    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    key, val = line.strip().split("=", 1)
                    env_content[key] = val

    # Update values
    if req.podcast_name:
        env_content["PODCAST_NAME"] = req.podcast_name
        settings.podcast_name = req.podcast_name

    if req.podcast_dir:
        env_content["PODCAST_DIR"] = req.podcast_dir
        settings.podcast_dir = Path(req.podcast_dir)
        
    if req.ai_provider_order is not None:
        order_str = ",".join(req.ai_provider_order)
        env_content["AI_PROVIDER_ORDER"] = order_str
        settings.ai_provider_order = order_str
        
    if req.groq_api_key is not None and not _is_masked(req.groq_api_key):
        env_content["GROQ_API_KEY"] = req.groq_api_key
        settings.groq_api_key = req.groq_api_key
        
    if req.groq_model is not None:
        env_content["GROQ_MODEL"] = req.groq_model
        settings.groq_model = req.groq_model
        
    if req.openai_api_key is not None and not _is_masked(req.openai_api_key):
        env_content["OPENAI_API_KEY"] = req.openai_api_key
        settings.openai_api_key = req.openai_api_key
        
    if req.openai_model is not None:
        env_content["OPENAI_MODEL"] = req.openai_model
        settings.openai_model = req.openai_model
        
    if req.anthropic_api_key is not None and not _is_masked(req.anthropic_api_key):
        env_content["ANTHROPIC_API_KEY"] = req.anthropic_api_key
        settings.anthropic_api_key = req.anthropic_api_key
        
    if req.anthropic_model is not None:
        env_content["ANTHROPIC_MODEL"] = req.anthropic_model
        settings.anthropic_model = req.anthropic_model
        
    if req.gcp_project_id is not None:
        env_content["GCP_PROJECT_ID"] = req.gcp_project_id
        settings.gcp_project_id = req.gcp_project_id
        
    if req.vertex_model is not None:
        env_content["VERTEX_MODEL"] = req.vertex_model
        settings.vertex_model = req.vertex_model
        
    if req.transcript_supabase_url is not None and not _is_masked(req.transcript_supabase_url):
        env_content["TRANSCRIPT_SUPABASE_URL"] = req.transcript_supabase_url
        settings.transcript_supabase_url = req.transcript_supabase_url

    if req.transcript_supabase_key is not None and not _is_masked(req.transcript_supabase_key):
        env_content["TRANSCRIPT_SUPABASE_KEY"] = req.transcript_supabase_key
        settings.transcript_supabase_key = req.transcript_supabase_key

    if req.generate_teasers is not None:
        env_content["GENERATE_TEASERS"] = str(req.generate_teasers).lower()
        settings.generate_teasers = req.generate_teasers
    
    # Write back to .env
    with open(env_path, "w") as f:
        for key, val in env_content.items():
            f.write(f"{key}={val}\n")
            
    return await get_settings()

@router.get("/models")
async def get_available_models(user: User = Depends(require_auth)):
    """
    Dynamically discover and return available AI models via native SDKs.
    """
    models = await model_registry.get_all_models()
    return {"data": [m.dict() for m in models]}

@router.get("/browse")
async def browse_directory(path: str = "~"):
    """
    Browse directories on the local filesystem.
    Used by the Settings UI to pick a podcast directory with full absolute paths.
    """
    # Expand ~ and resolve
    target = Path(os.path.expanduser(path)).resolve()

    # Security: restrict browsing to user home and external drives
    home = Path(os.path.expanduser("~")).resolve()
    allowed_roots = _get_allowed_roots()
    if not any(target.is_relative_to(root) for root in allowed_roots):
        return {"path": str(target), "parent": str(home), "dirs": [], "error": "Access restricted to home directory and external drives"}

    if not target.exists() or not target.is_dir():
        return {"path": str(target), "parent": str(target.parent), "dirs": [], "error": "Directory not found"}

    dirs = []
    try:
        for entry in sorted(target.iterdir()):
            if entry.is_dir() and not entry.name.startswith('.'):
                # Count children to hint if it has sub-folders
                try:
                    child_count = sum(1 for c in entry.iterdir() if c.is_dir() and not c.name.startswith('.'))
                except PermissionError:
                    child_count = 0
                dirs.append({
                    "name": entry.name,
                    "path": str(entry),
                    "has_children": child_count > 0
                })
    except PermissionError:
        return {"path": str(target), "parent": str(target.parent), "dirs": [], "error": "Permission denied"}

    return {
        "path": str(target),
        "parent": str(target.parent) if target.parent != target else None,
        "dirs": dirs
    }

@router.get("/browse-files")
async def browse_files(path: str = "~"):
    """
    Browse directories and video files on the local filesystem.
    Used by the Upload manual UI to pick a file without uploading.
    """
    target = Path(os.path.expanduser(path)).resolve()

    # Security: restrict browsing to user home and external drives
    home = Path(os.path.expanduser("~")).resolve()
    allowed_roots = _get_allowed_roots()
    if not any(target.is_relative_to(root) for root in allowed_roots):
        return {"path": str(target), "parent": str(home), "entries": [], "error": "Access restricted to home directory and external drives"}

    if not target.exists() or not target.is_dir():
        return {"path": str(target), "parent": str(target.parent), "entries": [], "error": "Directory not found"}

    entries = []
    try:
        # First add directories
        for entry in sorted(target.iterdir()):
            if entry.is_dir() and not entry.name.startswith('.'):
                try:
                    child_count = sum(1 for c in entry.iterdir() if c.is_dir() and not c.name.startswith('.'))
                except PermissionError:
                    child_count = 0
                entries.append({
                    "name": entry.name,
                    "path": str(entry),
                    "is_dir": True,
                    "has_children": child_count > 0
                })
                
        # Then add supported video files
        for entry in sorted(target.iterdir()):
            if entry.is_file() and not entry.name.startswith('.') and entry.name.lower().endswith(('.mp4', '.mov', '.mkv')):
                try:
                    size_mb = f"{entry.stat().st_size / (1024 * 1024):.1f}"
                except OSError:
                    size_mb = "0"
                entries.append({
                    "name": entry.name,
                    "path": str(entry),
                    "is_dir": False,
                    "size_mb": size_mb
                })
    except PermissionError:
        return {"path": str(target), "parent": str(target.parent), "entries": [], "error": "Permission denied"}

    return {
        "path": str(target),
        "parent": str(target.parent) if target.parent != target else None,
        "entries": entries
    }

@router.get("/resolve-path")
async def resolve_path(name: str):
    """
    Resolve a folder name (from native showDirectoryPicker) to full absolute path(s).
    Searches common locations: home dir, /Volumes (external drives), Desktop, Documents.
    """
    import os
    import subprocess
    import re

    # Security: sanitize folder name (alphanumeric, hyphens, underscores, spaces only)
    if not re.match(r'^[\w\s\-\.]+$', name):
        return {"name": name, "matches": [], "count": 0, "error": "Invalid folder name"}

    home = Path(os.path.expanduser("~"))

    # Search locations: home tree + platform-specific mount points
    search_roots = [str(r) for r in _get_allowed_roots()]
    
    matches = []
    try:
        # Use `find` for fast filesystem search, excluding system/hidden directories
        for root in search_roots:
            if not Path(root).exists():
                continue
            result = subprocess.run(
                [
                    "find", root,
                    "-maxdepth", "5",
                    "-type", "d",
                    "-name", name,
                    "-not", "-path", "*/Library/*",
                    "-not", "-path", "*/.*",
                    "-not", "-path", "*/node_modules/*",
                    "-not", "-path", "*/.Trash/*",
                ],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.strip().split("\n"):
                if line and Path(line).is_dir():
                    matches.append(line)
    except (subprocess.TimeoutExpired, Exception):
        pass

    # Deduplicate
    matches = list(dict.fromkeys(matches))

    return {
        "name": name,
        "matches": matches,
        "count": len(matches)
    }
