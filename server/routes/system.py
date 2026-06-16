"""System routes — version + self-update.

Self-update model:
- Versions are GitHub releases (semver tags v0.1.0, v0.1.1, …)
- Check: GET /api/system/version compares local __version__ vs latest tag
- Trigger: POST /api/system/update runs scripts/self_update.sh in background
- Watch: GET /api/system/update/status streams the update log
- Restart: the update script touches ~/.azelia/data/.restart; the server's
  watcher exits with code 42; the azelia wrapper detects 42 and re-launches.

Data preservation: ~/.azelia/data/ is OUTSIDE the git checkout, so git pull
+ pip install -e . never touches user jobs / clips / SQLite DBs / secrets.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from packages.core.config import settings
from server.middleware.auth import User, require_auth

try:
    from packages.clips import __version__ as CURRENT_VERSION
except Exception:
    CURRENT_VERSION = "0.0.0"

router = APIRouter()


# ─── Paths ──────────────────────────────────────────────────────────────


def _azelia_home() -> Path:
    """Where the user installation lives (~/.azelia by default)."""
    return Path(os.environ.get("AZELIA_HOME", Path.home() / ".azelia"))


def _checkout_dir() -> Path:
    """Where the git checkout lives. Falls back to repo root in dev mode."""
    home = _azelia_home()
    inside_home = home / "azelia"
    if (inside_home / ".git").exists():
        return inside_home
    # dev mode: this file's repo root
    here = Path(__file__).resolve().parents[2]
    return here


def _update_log_path() -> Path:
    return settings.data_dir / "update.log"


def _update_lock_path() -> Path:
    return settings.data_dir / "update.lock"


def _restart_sentinel_path() -> Path:
    return settings.data_dir / ".restart"


def _self_update_script() -> Path:
    return _checkout_dir() / "scripts" / "self_update.sh"


# ─── Version helpers ────────────────────────────────────────────────────


def _git_current_commit() -> Optional[str]:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_checkout_dir()),
            capture_output=True,
            text=True,
            timeout=3,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        return None
    return None


async def _fetch_latest_release() -> Optional[dict]:
    """GET https://api.github.com/repos/anju2246/azelia-clips/releases/latest

    Returns {tag_name, name, body, html_url} or None on failure.
    """
    try:
        import httpx

        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                "https://api.github.com/repos/anju2246/azelia-clips/releases/latest",
                headers={"Accept": "application/vnd.github+json"},
            )
            if r.status_code != 200:
                return None
            data = r.json()
            return {
                "tag_name": data.get("tag_name"),
                "name": data.get("name"),
                "body": (data.get("body") or "")[:2000],
                "html_url": data.get("html_url"),
                "published_at": data.get("published_at"),
            }
    except Exception:
        return None


def _is_update_in_progress() -> bool:
    return _update_lock_path().exists()


def _has_active_jobs() -> bool:
    """True if any job is currently rendering. Shared with profile switching."""
    from server.services.jobs_guard import has_active_jobs

    return has_active_jobs()[0]


# ─── Endpoints ──────────────────────────────────────────────────────────


@router.get("/system/version")
async def get_version(user: User = Depends(require_auth)):
    """Return installed version + latest available on GitHub."""
    latest = await _fetch_latest_release()
    latest_tag = (latest or {}).get("tag_name", "").lstrip("v")
    behind = bool(latest_tag and latest_tag != CURRENT_VERSION)
    return {
        "current": CURRENT_VERSION,
        "current_commit": _git_current_commit(),
        "latest": latest_tag or None,
        "latest_info": latest,
        "behind": behind,
        "channel": "stable",
        "update_available": behind,
        "update_in_progress": _is_update_in_progress(),
    }


@router.post("/system/update")
async def trigger_update(background: BackgroundTasks, user: User = Depends(require_auth)):
    """Kick off self-update in a background thread.

    Returns immediately. Poll /system/update/status for progress.
    Refuses if another update is running or jobs are active.
    """
    if _is_update_in_progress():
        raise HTTPException(status_code=409, detail="Update already in progress")
    if _has_active_jobs():
        raise HTTPException(
            status_code=409,
            detail="Cannot update while jobs are processing. Cancel or wait for them to finish.",
        )
    script = _self_update_script()
    if not script.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Update script not found at {script}. Reinstall via install.sh.",
        )

    # Truncate the log so the next status poll starts fresh
    log = _update_log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("")

    def _run():
        try:
            subprocess.Popen(
                ["bash", str(script)],
                cwd=str(_checkout_dir()),
                stdout=open(log, "ab"),
                stderr=subprocess.STDOUT,
                env={**os.environ, "AZELIA_HOME": str(_azelia_home())},
                start_new_session=True,
            )
        except Exception as e:
            log.write_text(f"Failed to launch update: {e}\n")

    background.add_task(_run)
    return {"status": "started", "log": str(log)}


@router.get("/system/update/status")
async def update_status(user: User = Depends(require_auth)):
    """Return current update status by reading the log tail."""
    log = _update_log_path()
    running = _is_update_in_progress()
    if not log.exists():
        return {"status": "idle", "log": [], "running": running}

    try:
        # Tail last 80 lines
        lines = log.read_text(errors="ignore").splitlines()[-80:]
    except Exception:
        lines = []

    # Infer phase from log content
    text = "\n".join(lines).lower()
    if "=== update done" in text:
        phase = "done"
    elif "error" in text or "failed" in text:
        phase = "error"
    elif "[restarting]" in text:
        phase = "restarting"
    elif "[building]" in text:
        phase = "building"
    elif "[installing]" in text:
        phase = "installing"
    elif "[fetching]" in text:
        phase = "fetching"
    elif running:
        phase = "starting"
    else:
        phase = "idle"

    return {"status": phase, "log": lines, "running": running}


@router.get("/system/info")
async def system_info(user: User = Depends(require_auth)):
    """Diagnostic info — useful for bug reports."""
    return {
        "version": CURRENT_VERSION,
        "commit": _git_current_commit(),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "azelia_home": str(_azelia_home()),
        "checkout_dir": str(_checkout_dir()),
        "data_dir": str(settings.data_dir),
    }
