"""
Server Routes — Application Settings
"""

from pathlib import Path

from fastapi import APIRouter, Depends

from server.models import SettingsResponse, UpdateSettingsRequest
from packages.core.config import settings
from server.middleware.auth import require_auth

router = APIRouter()


def mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return ""
    return f"{key[:4]}...{key[-4:]}"


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(user: dict = Depends(require_auth)):
    """Get current application settings."""
    return SettingsResponse(
        podcast_name=settings.podcast_name,
        podcast_dir=str(settings.podcast_dir),
        groq_api_key=mask_key(settings.groq_api_key),
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
        
    if req.groq_api_key:
        env_content["GROQ_API_KEY"] = req.groq_api_key
        settings.groq_api_key = req.groq_api_key
        
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
