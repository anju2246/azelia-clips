"""Profile + Claude Code endpoints (F1–F7).

Multi-podcast isolation: each profile is its own data tree. Switching profiles
restarts the server (sentinel `.restart` + exit 42), blocked while a job is
rendering. Claude Code binary + account (CLAUDE_CONFIG_DIR) are selectable per
profile and identified by the logged-in email.
"""

from fastapi import APIRouter, Depends, HTTPException

from packages.core import claude_detect
from packages.core.config import _azelia_home, settings
from packages.core.profiles import (
    ActiveProfileError,
    LastProfileError,
    Profile,
    ProfileError,
    ProfileManager,
    ProfileNotFound,
)
from server.middleware.auth import User, require_auth
from server.models import (
    CreateProfileRequest,
    ProfileResponse,
    ProfilesListResponse,
    UpdateProfileRequest,
    ValidateClaudeRequest,
)
from server.services.jobs_guard import has_active_jobs

router = APIRouter()


def _pm() -> ProfileManager:
    return ProfileManager(_azelia_home())


def _to_response(p: Profile, active_id: str | None) -> ProfileResponse:
    return ProfileResponse(
        id=p.id,
        name=p.name,
        data_dir=p.data_dir,
        claude_binary=p.claude_binary,
        claude_config_dir=p.claude_config_dir,
        is_default=p.is_default,
        created_at=p.created_at,
        active=(p.id == active_id),
    )


# ── F1 list ────────────────────────────────────────────────────────────────


@router.get("/profiles", response_model=ProfilesListResponse)
async def list_profiles(user: User = Depends(require_auth)):
    pm = _pm()
    try:
        active_id = pm.active().id
    except ProfileNotFound:
        active_id = None
    return ProfilesListResponse(
        active_profile=active_id,
        profiles=[_to_response(p, active_id) for p in pm.list()],
    )


# ── F2 create ────────────────────────────────────────────────────────────────


@router.post("/profiles", response_model=ProfileResponse, status_code=201)
async def create_profile(req: CreateProfileRequest, user: User = Depends(require_auth)):
    pm = _pm()
    try:
        p = pm.create(req.name, claude_binary=req.claude_binary, claude_config_dir=req.claude_config_dir)
    except ProfileError as e:
        raise HTTPException(status_code=422, detail=str(e))
    active_id = pm.active().id
    return _to_response(p, active_id)


# ── F3 update ────────────────────────────────────────────────────────────────


@router.patch("/profiles/{profile_id}", response_model=ProfileResponse)
async def update_profile(profile_id: str, req: UpdateProfileRequest, user: User = Depends(require_auth)):
    pm = _pm()
    fields = req.model_dump(exclude_unset=True)
    try:
        p = pm.update(profile_id, **fields)
    except ProfileNotFound:
        raise HTTPException(status_code=404, detail="PROFILE_NOT_FOUND")
    except ProfileError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _to_response(p, pm.active().id)


# ── F4 delete ────────────────────────────────────────────────────────────────


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: str, delete_data: bool = False, user: User = Depends(require_auth)):
    pm = _pm()
    try:
        pm.delete(profile_id, delete_data=delete_data)
    except ProfileNotFound:
        raise HTTPException(status_code=404, detail="PROFILE_NOT_FOUND")
    except ActiveProfileError:
        raise HTTPException(status_code=409, detail="PROFILE_ACTIVE")
    except LastProfileError:
        raise HTTPException(status_code=409, detail="LAST_PROFILE")
    return {"deleted": profile_id, "data_removed": delete_data}


# ── F5 activate (switch) ─────────────────────────────────────────────────────


@router.post("/profiles/{profile_id}/activate")
async def activate_profile(profile_id: str, user: User = Depends(require_auth)):
    pm = _pm()
    if pm.get(profile_id) is None:
        raise HTTPException(status_code=404, detail="PROFILE_NOT_FOUND")
    try:
        already = pm.active().id == profile_id
    except ProfileNotFound:
        already = False
    if already:
        return {"status": "noop", "active_profile": profile_id}

    active, ids = has_active_jobs()
    if active:
        raise HTTPException(status_code=409, detail={"code": "ACTIVE_JOBS", "jobs": ids})

    # Write the active pointer FIRST so the relaunched process reads the right
    # profile, THEN trip the restart sentinel watched against the current dir.
    pm.set_active(profile_id)
    sentinel = settings.data_dir / ".restart"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.touch()
    return {"status": "restarting", "active_profile": profile_id}


# ── F6 detect installations + accounts ───────────────────────────────────────


@router.get("/claude/installations")
async def claude_installations(user: User = Depends(require_auth)):
    extra = [p.claude_config_dir for p in _pm().list() if p.claude_config_dir]
    return {
        "installations": claude_detect.detect_installations(),
        "accounts": claude_detect.detect_accounts(extra_config_dirs=extra),
    }


# ── F7 validate manual binary + config dir ───────────────────────────────────


@router.post("/claude/validate")
async def claude_validate(req: ValidateClaudeRequest, user: User = Depends(require_auth)):
    return claude_detect.validate(path=req.path, config_dir=req.config_dir)
