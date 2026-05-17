"""Analytics routes — Local-first MVP (v0.1.0).

YouTube integration is **disabled in v0.1.0** while we rebuild it without
central-DB dependencies. Endpoints return 501 with a "coming-soon" payload
so the frontend can show a friendly placeholder.

YouTube returns in v0.1.1 with: OAuth (unverified app warning), local SQLite
sync to ~/.azelia/data/youtube_shorts.db, and a local-only insights view.

The single live endpoint here is `/api/analytics/insights` which aggregates
the user's local JobStore for the dashboard "What you've made" panel.
"""

from fastapi import APIRouter, Depends, HTTPException

from server.middleware.auth import User, require_auth
from server.workers.job_store import get_job_store

router = APIRouter()


# ─── LIVE: Local pipeline insights ──────────────────────────────────────


@router.get("/analytics/insights")
async def get_insights(user: User = Depends(require_auth)):
    """Stats from the local JobStore. Used by the dashboard."""
    store = get_job_store()
    all_jobs = []
    try:
        for status in ("completed", "processing", "failed", "cancelled", "paused"):
            method = getattr(store, "get_jobs_by_status", None)
            if callable(method):
                all_jobs.extend(method(status) or [])
            else:
                break
    except Exception:
        all_jobs = []

    total_jobs = len(all_jobs)
    completed = sum(1 for j in all_jobs if getattr(j, "status", None) == "completed")
    total_clips = sum(getattr(j, "clips_generated", 0) or 0 for j in all_jobs)

    return {
        "total_jobs": total_jobs,
        "completed_jobs": completed,
        "total_clips": total_clips,
        "youtube_connected": False,
    }


# ─── STUBS: YouTube (coming-soon in v0.1.0) ─────────────────────────────


_COMING_SOON = {
    "status": "coming_soon",
    "message": "YouTube integration is being rebuilt for local-first. Coming in v0.1.1.",
    "version_target": "0.1.1",
}


@router.get("/analytics/youtube/status")
async def youtube_status(user: User = Depends(require_auth)):
    return {"connected": False, **_COMING_SOON}


@router.get("/connections/youtube")
async def connections_youtube(user: User = Depends(require_auth)):
    return {"connected": False, **_COMING_SOON}


@router.post("/analytics/youtube/sync")
async def youtube_sync(user: User = Depends(require_auth)):
    raise HTTPException(status_code=501, detail=_COMING_SOON)


@router.post("/analytics/youtube/sync-with-code")
async def youtube_sync_with_code(user: User = Depends(require_auth)):
    raise HTTPException(status_code=501, detail=_COMING_SOON)


@router.post("/analytics/youtube/auto-sync")
async def youtube_auto_sync(user: User = Depends(require_auth)):
    raise HTTPException(status_code=501, detail=_COMING_SOON)


@router.get("/analytics/youtube/sync-status")
async def youtube_sync_status(user: User = Depends(require_auth)):
    return {"running": False, **_COMING_SOON}


@router.get("/analytics/youtube/historical/estimate")
async def youtube_historical_estimate(user: User = Depends(require_auth)):
    raise HTTPException(status_code=501, detail=_COMING_SOON)


@router.post("/analytics/youtube/historical/sync")
async def youtube_historical_sync(user: User = Depends(require_auth)):
    raise HTTPException(status_code=501, detail=_COMING_SOON)


@router.get("/analytics/youtube/historical/status/{job_id}")
async def youtube_historical_status(job_id: str, user: User = Depends(require_auth)):
    return {"status": "not_found", **_COMING_SOON}


@router.get("/analytics/youtube/insights")
async def youtube_insights(user: User = Depends(require_auth)):
    raise HTTPException(status_code=501, detail=_COMING_SOON)


@router.get("/auth/youtube/authorize")
async def youtube_authorize(user: User = Depends(require_auth)):
    raise HTTPException(status_code=501, detail=_COMING_SOON)


@router.post("/auth/youtube/callback")
async def youtube_callback(user: User = Depends(require_auth)):
    raise HTTPException(status_code=501, detail=_COMING_SOON)
