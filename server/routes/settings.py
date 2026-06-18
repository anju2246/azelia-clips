"""Settings routes — Local-first MVP.

Two LLM providers only: Claude Code (local) + Anthropic API.
Settings persist to ~/.azelia/data/secrets.env (outside the git checkout).
"""

import os
import re
import string
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from packages.core.config import settings
from packages.core.llm_provider import claude_code_available, claude_code_authenticated, reset_llm
from packages.core.services.model_registry import model_registry
from server.middleware.auth import User, require_auth
from server.models import SettingsResponse, UpdateSettingsRequest

router = APIRouter()


# ─── Helpers ────────────────────────────────────────────────────────────


def _get_allowed_roots() -> list[Path]:
    """Platform-aware allowed roots for filesystem browsing (security)."""
    roots = [Path.home().resolve()]
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
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:\\")
            if drive.exists():
                roots.append(drive)
    return roots


def _secrets_path() -> Path:
    """Where API keys live (outside the git checkout so self-update can't wipe them)."""
    p = settings.data_dir / "secrets.env"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return ""
    return f"{key[:4]}...{key[-4:]}"


def _is_masked(value: str) -> bool:
    return not value or "..." in value or value == "********"


def _validate_anthropic_key(value: str) -> str | None:
    if not value or not value.strip():
        return None
    v = value.strip()
    if len(v) < 10:
        return f"API key too short (got {len(v)} chars)"
    if not v.startswith("sk-ant-"):
        return "Anthropic keys start with 'sk-ant-'"
    return None


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def _write_env_file(path: Path, env: dict[str, str]) -> None:
    lines = [f"{k}={v}" for k, v in env.items()]
    path.write_text("\n".join(lines) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# ─── Settings CRUD ──────────────────────────────────────────────────────


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(user: User = Depends(require_auth)):
    order = (
        [p.strip() for p in settings.ai_provider_order.split(",") if p.strip()]
        if settings.ai_provider_order
        else ["claude_code", "anthropic"]
    )
    return SettingsResponse(
        podcast_name=settings.podcast_name or "",
        podcast_dir=str(settings.podcast_dir) if settings.podcast_dir else "",
        ai_provider_order=order,
        anthropic_api_key=mask_key(settings.anthropic_api_key),
        anthropic_model=settings.anthropic_model,
        transcript_supabase_url=settings.transcript_supabase_url,
        transcript_supabase_key=mask_key(settings.transcript_supabase_key),
        review_brief_before_processing=settings.review_brief_before_processing,
        default_template_id=settings.default_template_id,
    )


@router.post("/settings", response_model=SettingsResponse)
async def update_settings(req: UpdateSettingsRequest, user: User = Depends(require_auth)):
    """Update settings: writes to ~/.azelia/data/secrets.env and reloads in-process."""
    if req.anthropic_api_key is not None and not _is_masked(req.anthropic_api_key):
        err = _validate_anthropic_key(req.anthropic_api_key)
        if err:
            raise HTTPException(status_code=422, detail=err)

    env_path = _secrets_path()
    env = _read_env_file(env_path)

    if req.podcast_name is not None:
        env["PODCAST_NAME"] = req.podcast_name
        settings.podcast_name = req.podcast_name
    if req.podcast_dir is not None:
        env["PODCAST_DIR"] = req.podcast_dir
        settings.podcast_dir = Path(req.podcast_dir)
    if req.ai_provider_order is not None:
        # Filter to allowed providers only
        allowed = {"claude_code", "anthropic"}
        clean = [p for p in req.ai_provider_order if p in allowed]
        if not clean:
            clean = ["claude_code", "anthropic"]
        order_str = ",".join(clean)
        env["AI_PROVIDER_ORDER"] = order_str
        settings.ai_provider_order = order_str
    if req.anthropic_api_key is not None and not _is_masked(req.anthropic_api_key):
        env["ANTHROPIC_API_KEY"] = req.anthropic_api_key
        settings.anthropic_api_key = req.anthropic_api_key
    if req.anthropic_model is not None:
        env["ANTHROPIC_MODEL"] = req.anthropic_model
        settings.anthropic_model = req.anthropic_model
    # User-owned Supabase for transcripts (optional)
    if req.transcript_supabase_url is not None and not _is_masked(req.transcript_supabase_url):
        env["TRANSCRIPT_SUPABASE_URL"] = req.transcript_supabase_url
        settings.transcript_supabase_url = req.transcript_supabase_url
    if req.transcript_supabase_key is not None and not _is_masked(req.transcript_supabase_key):
        env["TRANSCRIPT_SUPABASE_KEY"] = req.transcript_supabase_key
        settings.transcript_supabase_key = req.transcript_supabase_key
    if req.review_brief_before_processing is not None:
        env["REVIEW_BRIEF_BEFORE_PROCESSING"] = "true" if req.review_brief_before_processing else "false"
        settings.review_brief_before_processing = req.review_brief_before_processing
    if req.default_template_id is not None:
        env["DEFAULT_TEMPLATE_ID"] = req.default_template_id
        settings.default_template_id = req.default_template_id

    _write_env_file(env_path, env)
    reset_llm()  # invalidate cached provider list

    return await get_settings(user=user)


# ─── LLM providers ──────────────────────────────────────────────────────


@router.get("/providers")
async def get_providers(user: User = Depends(require_auth)):
    """Discover available LLM providers (Claude Code + Anthropic API only)."""
    cc_info = claude_code_authenticated()
    return {
        "claude_code": {
            "available": claude_code_available(),
            "authenticated": cc_info is not None,
            "auth_method": (cc_info or {}).get("method"),
            "active": cc_info is not None,
        },
        "api_providers": [
            {
                "id": "anthropic",
                "name": "Anthropic API",
                "configured": bool(settings.anthropic_api_key),
                "model": settings.anthropic_model,
            }
        ],
        "active_primary": "claude_code" if cc_info else ("anthropic" if settings.anthropic_api_key else None),
    }


@router.get("/models")
async def get_available_models(user: User = Depends(require_auth)):
    """Dynamically list available models from configured providers."""
    models = await model_registry.get_all_models()
    return {"data": [m.dict() for m in models]}


@router.post("/models/refresh")
async def refresh_models(user: User = Depends(require_auth)):
    """Force model registry to re-query provider APIs."""
    models = await model_registry.force_refresh()
    return {"data": [m.dict() for m in models]}


@router.get("/integrations/transcript-supabase/test")
async def test_transcript_supabase(user: User = Depends(require_auth)):
    """Verify the user's transcript-Supabase credentials actually work.

    Returns:
        {ok: True, episodes: N}              when URL+key reach a Supabase that
                                              has an `episodes` table.
        {ok: False, reason: "not_configured"} when URL or key is missing.
        {ok: False, reason: "<short tag>", detail: "..."} on DNS / auth / schema
                                              errors so the UI can be specific.
    """
    url = (settings.transcript_supabase_url or "").strip()
    key = (settings.transcript_supabase_key or "").strip()
    if not url or not key:
        return {"ok": False, "reason": "not_configured"}

    try:
        import httpx

        # Probe via PostgREST count header — cheapest possible call.
        r = httpx.get(
            f"{url.rstrip('/')}/rest/v1/episodes",
            params={"select": "id", "limit": "1"},
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Prefer": "count=exact",
                "Range-Unit": "items",
                "Range": "0-0",
            },
            timeout=8,
        )
        if r.status_code == 401:
            return {"ok": False, "reason": "invalid_key"}
        if r.status_code == 404:
            return {"ok": False, "reason": "no_episodes_table"}
        if r.status_code >= 400:
            return {
                "ok": False,
                "reason": f"http_{r.status_code}",
                "detail": (r.text or "")[:200],
            }
        # Content-Range header carries the total count when Prefer: count=exact
        total = None
        cr = r.headers.get("content-range", "")
        if "/" in cr:
            try:
                total = int(cr.split("/")[-1])
            except ValueError:
                total = None
        return {"ok": True, "episodes": total}
    except httpx.ConnectError as e:
        return {"ok": False, "reason": "unreachable", "detail": str(e)[:200]}
    except Exception as e:
        return {"ok": False, "reason": type(e).__name__, "detail": str(e)[:200]}


@router.get("/credits/status")
async def get_credits_status(user: User = Depends(require_auth)):
    """Quick probe of the Anthropic API key billing state."""
    results: dict = {}

    if settings.anthropic_api_key and settings.anthropic_api_key.startswith("sk-ant-"):
        try:
            from anthropic import Anthropic

            client = Anthropic(api_key=settings.anthropic_api_key)
            client.messages.create(
                model=settings.anthropic_model or "claude-haiku-4-5-20251001",
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            results["anthropic"] = {"ok": True, "reason": None, "model_used": settings.anthropic_model}
        except Exception as e:
            msg = str(e).lower()
            if "credit" in msg or "balance" in msg or "insufficient" in msg:
                reason = "credit_balance_too_low"
            elif "billing" in msg:
                reason = "billing_not_active"
            elif "authentication" in msg or "invalid" in msg or "401" in msg:
                reason = "invalid_key"
            elif "rate" in msg or "429" in msg:
                reason = "rate_limited"
            else:
                reason = type(e).__name__
            results["anthropic"] = {"ok": False, "reason": reason, "model_used": None}
    else:
        results["anthropic"] = {"ok": None, "reason": "not_configured", "model_used": None}

    return {
        "any_provider_ok": any(r.get("ok") is True for r in results.values()) or claude_code_available(),
        "providers": results,
    }


# ─── Filesystem browsing (for directory pickers) ────────────────────────


@router.get("/browse")
async def browse_directory(path: str = "~", user: User = Depends(require_auth)):
    """Browse directories — used by Settings directory picker."""
    target = Path(os.path.expanduser(path)).resolve()
    if not any(target.is_relative_to(root) for root in _get_allowed_roots()):
        return {
            "path": str(target),
            "parent": str(Path.home()),
            "dirs": [],
            "error": "Access restricted to home directory and external drives",
        }
    if not target.exists() or not target.is_dir():
        return {"path": str(target), "parent": str(target.parent), "dirs": [], "error": "Directory not found"}
    dirs = []
    try:
        for entry in sorted(target.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                try:
                    child_count = sum(1 for c in entry.iterdir() if c.is_dir() and not c.name.startswith("."))
                except PermissionError:
                    child_count = 0
                dirs.append({"name": entry.name, "path": str(entry), "has_children": child_count > 0})
    except PermissionError:
        return {"path": str(target), "parent": str(target.parent), "dirs": [], "error": "Permission denied"}
    return {
        "path": str(target),
        "parent": str(target.parent) if target.parent != target else None,
        "dirs": dirs,
    }


@router.get("/browse-files")
async def browse_files(path: str = "~", user: User = Depends(require_auth)):
    """Browse directories + video files — used by manual upload picker."""
    target = Path(os.path.expanduser(path)).resolve()
    if not any(target.is_relative_to(root) for root in _get_allowed_roots()):
        return {
            "path": str(target),
            "parent": str(Path.home()),
            "entries": [],
            "error": "Access restricted",
        }
    if not target.exists() or not target.is_dir():
        return {"path": str(target), "parent": str(target.parent), "entries": [], "error": "Directory not found"}
    entries = []
    try:
        for entry in sorted(target.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                try:
                    child_count = sum(1 for c in entry.iterdir() if c.is_dir() and not c.name.startswith("."))
                except PermissionError:
                    child_count = 0
                entries.append(
                    {"name": entry.name, "path": str(entry), "is_dir": True, "has_children": child_count > 0}
                )
        for entry in sorted(target.iterdir()):
            if entry.is_file() and not entry.name.startswith(".") and entry.name.lower().endswith((".mp4", ".mov", ".mkv")):
                try:
                    size_mb = f"{entry.stat().st_size / (1024 * 1024):.1f}"
                except OSError:
                    size_mb = "0"
                entries.append({"name": entry.name, "path": str(entry), "is_dir": False, "size_mb": size_mb})
    except PermissionError:
        return {"path": str(target), "parent": str(target.parent), "entries": [], "error": "Permission denied"}
    return {
        "path": str(target),
        "parent": str(target.parent) if target.parent != target else None,
        "entries": entries,
    }


@router.get("/resolve-path")
async def resolve_path(name: str, user: User = Depends(require_auth)):
    """Resolve a folder name to absolute path(s) via `find`."""
    if ".." in name or "/" in name or "\\" in name or not name.strip():
        return {"name": name, "matches": [], "count": 0, "error": "Invalid folder name"}
    if not re.match(r"^[\w\s\-]+$", name):
        return {"name": name, "matches": [], "count": 0, "error": "Only alphanumeric/spaces/hyphens allowed"}
    matches: list[str] = []
    for root in _get_allowed_roots():
        if not root.exists():
            continue
        try:
            result = subprocess.run(
                [
                    "find",
                    str(root),
                    "-maxdepth", "5",
                    "-type", "d",
                    "-name", name,
                    "-not", "-path", "*/Library/*",
                    "-not", "-path", "*/.*",
                    "-not", "-path", "*/node_modules/*",
                    "-not", "-path", "*/.Trash/*",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            for line in result.stdout.strip().split("\n"):
                if line and Path(line).is_dir():
                    matches.append(line)
        except (subprocess.TimeoutExpired, Exception):
            continue
    matches = list(dict.fromkeys(matches))
    return {"name": name, "matches": matches, "count": len(matches)}
