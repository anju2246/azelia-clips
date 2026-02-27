"""
Server Routes — Application Settings
"""

from pathlib import Path

from fastapi import APIRouter, Depends

from server.models import SettingsResponse, UpdateSettingsRequest
from packages.core.config import settings
from server.middleware.auth import optional_auth

router = APIRouter()


def mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return ""
    return f"{key[:4]}...{key[-4:]}"


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(user: dict = Depends(optional_auth)):
    """Get current application settings."""
    provider_order = [p.strip() for p in settings.ai_provider_order.split(',')] if settings.ai_provider_order else ["groq", "openai", "anthropic", "vertex"]
    return SettingsResponse(
        podcast_name=settings.podcast_name,
        podcast_dir=str(settings.podcast_dir),
        ai_provider_order=provider_order,
        groq_api_key=mask_key(settings.groq_api_key),
        groq_model=settings.groq_model,
        openai_api_key=mask_key(settings.openai_api_key),
        openai_model=settings.openai_model,
        anthropic_api_key=mask_key(settings.anthropic_api_key),
        anthropic_model=settings.anthropic_model,
        gcp_project_id=settings.gcp_project_id,
        vertex_model=settings.vertex_model,
        supabase_url=settings.supabase_url,
        supabase_key=mask_key(settings.supabase_key)
    )

@router.post("/settings", response_model=SettingsResponse)
async def update_settings(req: UpdateSettingsRequest):
    """Update settings in .env file."""
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
        
    if req.groq_api_key is not None:
        env_content["GROQ_API_KEY"] = req.groq_api_key
        settings.groq_api_key = req.groq_api_key
        
    if req.groq_model is not None:
        env_content["GROQ_MODEL"] = req.groq_model
        settings.groq_model = req.groq_model
        
    if req.openai_api_key is not None:
        env_content["OPENAI_API_KEY"] = req.openai_api_key
        settings.openai_api_key = req.openai_api_key
        
    if req.openai_model is not None:
        env_content["OPENAI_MODEL"] = req.openai_model
        settings.openai_model = req.openai_model
        
    if req.anthropic_api_key is not None:
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
        
    if req.supabase_url:
        env_content["SUPABASE_URL"] = req.supabase_url
        settings.supabase_url = req.supabase_url
        
    if req.supabase_key:
        env_content["SUPABASE_KEY"] = req.supabase_key
        settings.supabase_key = req.supabase_key
    
    # Write back to .env
    with open(env_path, "w") as f:
        for key, val in env_content.items():
            f.write(f"{key}={val}\n")
            
    return await get_settings()


@router.get("/browse")
async def browse_directory(path: str = "~"):
    """
    Browse directories on the local filesystem.
    Used by the Settings UI to pick a podcast directory with full absolute paths.
    """
    import os

    # Expand ~ and resolve
    target = Path(os.path.expanduser(path)).resolve()

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
    import os

    target = Path(os.path.expanduser(path)).resolve()

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

    home = Path(os.path.expanduser("~"))
    
    # Search locations: home tree + all mounted volumes
    search_roots = [str(home), "/Volumes"]
    
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
