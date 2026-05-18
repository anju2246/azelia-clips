"""
Server Routes — Clip Processing, Jobs, Faces, Episodes, WebSocket
"""

import shutil
import hashlib
import uuid
import json
import asyncio
from pathlib import Path
from datetime import datetime
from typing import List

from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException, Form, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from server.models import (
    JobResponse, JobStatus, ProcessRequest, ProcessLocalRequest, Clip,
    EpisodeResponse
)
from server.dependencies import job_queue
from server.workers.job_store import get_job_store
from packages.core.config import settings
from server.middleware.auth import require_auth, require_onboarding, require_auth_flexible, User
from packages.clips.vision.face_tracker import FaceTracker

router = APIRouter()
store = get_job_store()

# Base directory for job data — settings.jobs_dir() ensures ~/.azelia/data/jobs by default
DATA_DIR = settings.jobs_dir()


def mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return ""
    return f"{key[:4]}...{key[-4:]}"


# ─── Video Upload & Processing ──────────────────────────────────────────────

@router.post("/process", response_model=JobResponse)
async def process_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    min_duration: int = Form(30),
    max_duration: int = Form(90),
    min_score: int = Form(70),
    subtitle_style: str = Form("highlight"),
    transcription_source: str = Form("local_whisper"),
    assemblyai_key: str | None = Form(None),
    supabase_url: str | None = Form(None),
    supabase_key: str | None = Form(None),
    user: User = Depends(require_onboarding)
):
    """Upload a video and start processing."""
    
    # Validate file type by extension AND magic bytes (prevent disguised uploads)
    if not file.filename.lower().endswith(('.mp4', '.mov', '.mkv')):
        raise HTTPException(status_code=400, detail="Invalid file type. Only MP4, MOV, MKV supported.")

    header = await file.read(12)
    await file.seek(0)
    # MP4/MOV: bytes 4-7 are 'ftyp' or 'moov' or 'wide'
    # MKV/WebM: starts with 0x1A 0x45 0xDF 0xA3
    is_mp4_mov = len(header) >= 8 and header[4:8] in (b'ftyp', b'moov', b'wide', b'mdat', b'free')
    is_mkv    = header[:4] == b'\x1a\x45\xdf\xa3'
    if not (is_mp4_mov or is_mkv):
        raise HTTPException(status_code=400, detail="File content does not match a valid video format.")
    
    # Create Job ID
    job_id = str(uuid.uuid4())
    job_dir = DATA_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    
    # User Token injected via dependency
    auth_token = None # Deprecated manual passing, using Depends() instead
    
    # Save file
    file_path = job_dir / "source.mp4"
    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")
    
    # Create Job config
    process_settings = ProcessRequest(
        min_duration=min_duration,
        max_duration=max_duration,
        min_score=min_score,
        subtitle_style=subtitle_style
    )
    
    # Build transcription config. The user can optionally route through their
    # own Supabase if they have transcripts there — Azelia has no Supabase of
    # its own anymore.
    t_url = supabase_url or settings.transcript_supabase_url or None
    t_key = supabase_key or settings.transcript_supabase_key or None
    effective_source = transcription_source
    if t_url and t_key and transcription_source == "local_whisper":
        effective_source = "supabase_custom"
    transcription_config = {
        "source_type": effective_source,
        "assemblyai_api_key": assemblyai_key,
        "supabase_url": t_url,
        "supabase_key": t_key,
    }
    
    # Initialize Job in Store (Legacy for UI compatibility)
    store.create_job(
        job_id=job_id,
        episode_id=file.filename,
        config=process_settings.dict(),
        user_id=user.id,
    )
    
    # Create Episode in SQLite
    with Session(engine) as session:
        episode = Episode(
            user_id=user.id if user else "anonymous",
            title=file.filename,
            video_path=str(file_path),
            status="queued"
        )
        session.add(episode)
        session.commit()
        session.refresh(episode)
    
    # Enqueue locally using the Hybrid Queue interface
    payload = {
        "episode_id": episode.id,
        "video_path": str(file_path),
        "settings": process_settings.dict(),
        "transcription_config": transcription_config,
        "auth_token": auth_token,
        "user_id": user.id if hasattr(user, 'id') else "anonymous"
    }
    
    asyncio.create_task(job_queue.enqueue(job_id=job_id, payload=payload))
    
    # Return initial status
    job = store.get_job(job_id)
    return JobResponse(
        id=job.job_id,
        status=JobStatus(job.status),
        filename=file.filename,
        created_at=job.created_at,
        progress=0,
        message="Queued for processing"
    )

@router.post("/process-local", response_model=JobResponse)
async def process_local_video(
    background_tasks: BackgroundTasks,
    req: ProcessLocalRequest,
    user: User = Depends(require_onboarding)
):
    """Process a video directly from the local file system using the Server-Side Picker."""
    import os
    
    file_path_obj = Path(req.video_path).resolve()
    if not file_path_obj.exists() or not file_path_obj.is_file():
        raise HTTPException(status_code=400, detail="Local file does not exist")
    
    # Security: Only allow files under user home or /Volumes (external drives)
    home = Path(os.path.expanduser("~")).resolve()
    allowed_roots = [home, Path("/Volumes").resolve()]
    if not any(file_path_obj.is_relative_to(root) for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Access denied: file must be in your home directory or external drives")
        
    filename = file_path_obj.name
    if not filename.lower().endswith(('.mp4', '.mov', '.mkv')):
        raise HTTPException(status_code=400, detail="Invalid file type. Only MP4, MOV, MKV supported.")
        
    # Create stable Job ID from file path
    job_id = hashlib.md5(str(file_path_obj).encode()).hexdigest()
    job_dir = DATA_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    
    # Symlink the file instantly instead of copying gigabytes
    target_link = job_dir / "source.mp4"
    if not target_link.exists():
        try:
            os.symlink(file_path_obj, target_link)
        except FileExistsError:
            pass  # Already linked from a previous run
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to link local file: {e}")
        
    # User-owned Supabase opt-in (transcripts only — Azelia has no DB)
    t_url = req.supabase_url or settings.transcript_supabase_url or None
    t_key = req.supabase_key or settings.transcript_supabase_key or None
    effective_source = req.transcription_source
    if t_url and t_key and req.transcription_source == "local_whisper":
        effective_source = "supabase_custom"
    transcription_config = {
        "source_type": effective_source,
        "assemblyai_api_key": getattr(req, "assemblyai_key", None),
        "supabase_url": t_url,
        "supabase_key": t_key,
    }

    # If job is already running, just return it
    existing = store.get_job(job_id)
    if existing and existing.status in ["processing", "pending", "resuming"]:
        return JobResponse(
            id=existing.job_id,
            status=JobStatus(existing.status),
            filename=filename,
            created_at=existing.created_at,
            progress=existing.progress,
            message=existing.message
        )

    # Initialize Job in Store (Legacy for UI compatibility)
    store.create_job(
        job_id=job_id,
        episode_id=filename,
        config=req.dict(),
        user_id=user.id,
    )
    
    with Session(engine) as session:
        episode = Episode(
            user_id=user.id if user else "anonymous",
            title=filename,
            video_path=str(target_link),
            status="queued"
        )
        session.add(episode)
        session.commit()
        session.refresh(episode)
        
    payload = {
        "episode_id": episode.id,
        "video_path": str(target_link),
        "settings": req.dict(),
        "transcription_config": transcription_config,
        "auth_token": None,
        "user_id": user.id if hasattr(user, 'id') else "anonymous"
    }
    
    asyncio.create_task(job_queue.enqueue(job_id=job_id, payload=payload))
    
    job = store.get_job(job_id)
    return JobResponse(
        id=job.job_id,
        status=JobStatus(job.status),
        filename=filename,
        created_at=job.created_at,
        progress=0,
        message="Queued local file for processing"
    )

# ─── Job Status & Clips ─────────────────────────────────────────────────────

@router.get("/jobs/history")
async def get_jobs_history(user: User = Depends(require_auth)):
    """Get a unified history of all processing jobs (both episodes and ad-hoc)."""
    all_jobs = store.get_latest_jobs_per_episode()
    # Filter: show only jobs owned by this user (legacy jobs with empty user_id are visible to all)
    jobs = {k: v for k, v in all_jobs.items() if not v.user_id or v.user_id == user.id}
    history = []
    
    # Sort by created_at descending
    sorted_jobs = sorted(jobs.values(), key=lambda j: j.created_at, reverse=True)
    
    for job in sorted_jobs:
        # Check if clips actually exist before counting as processed.
        # Library jobs render into {podcast_dir}/EPNNN - .../clips/, NOT
        # into DATA_DIR/{job_id}/clips/, so we need the resolver here.
        clips_dir = _resolve_clips_dir(job.job_id, job.episode_id)
        approved = clips_dir / "approved"
        review = clips_dir / "review"
        try:
            has_approved = approved.exists() and any(approved.iterdir())
        except (PermissionError, OSError):
            has_approved = False
        try:
            has_review = review.exists() and any(review.iterdir())
        except (PermissionError, OSError):
            has_review = False
        
        # Determine format
        is_episode = job.episode_id.startswith("EP") and len(job.episode_id) == 5
        
        history.append({
            "id": job.job_id,
            "filename": job.episode_id,
            "status": job.status,
            "created_at": job.created_at,
            "clips_generated": job.clips_generated,
            "has_clips": has_approved or has_review,
            "type": "episode" if is_episode else "adhoc",
            # Include standard episode properties for frontend compatibility
            "number": int(job.episode_id[2:]) if is_episode and job.episode_id[2:].isdigit() else 0,
            "title": job.episode_id
        })
        
    return history

def _get_video_duration(path: Path) -> float:
    """Get video duration in seconds using ffprobe."""
    import subprocess
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=5
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0

def _load_curation(job_dir: Path) -> list:
    """Load curation.json if it exists, returns list of dicts."""
    curation_path = job_dir / "curation.json"
    if not curation_path.exists():
        # Also check the clips parent (for ad-hoc, curation may be in episode_folder)
        return []
    try:
        with open(curation_path, "r") as f:
            return json.load(f)
    except Exception:
        return []


# Cache of EP-number → episode folder. Library jobs render clips into the
# user's own drive (`{podcast_dir}/EPNNN - …/clips/`), NOT under DATA_DIR,
# so every clips endpoint needs to know where to look. Scanning podcast_dir
# is cheap (one iterdir) but we cache anyway so /jobs/history with 100
# episodes doesn't re-scan 100 times.
_episode_folder_cache: dict[int, Path] = {}


def _episode_folder_for(ep_num: int) -> Path | None:
    cached = _episode_folder_cache.get(ep_num)
    if cached and cached.exists():
        return cached
    try:
        for folder in settings.podcast_dir.iterdir():
            if not folder.is_dir():
                continue
            name = folder.name
            if not name.upper().startswith(f"EP{ep_num:03d}"):
                continue
            _episode_folder_cache[ep_num] = folder
            return folder
    except (FileNotFoundError, OSError):
        return None
    return None


def _resolve_clips_dir(job_id: str, episode_id: str | None = None) -> Path:
    """Return the clips/ directory for a job, regardless of flow.

    - Upload jobs (UUID): `DATA_DIR/{job_id}/clips`
    - Library jobs (id starts with EPNNN- and episode is on disk): the
      `clips/` folder inside the matching `{podcast_dir}/EPNNN - …/`
      folder. Falls back to the DATA_DIR layout if discovery fails so
      callers always get a valid Path.
    """
    default = DATA_DIR / job_id / "clips"
    ep_id = (episode_id or "").upper()
    if not ep_id.startswith("EP"):
        # Try to parse from job_id (jobs are typically `EP024-process` etc.)
        upper = job_id.upper()
        if upper.startswith("EP"):
            ep_id = upper.split("-")[0]
    if ep_id.startswith("EP") and ep_id[2:].isdigit():
        ep_num = int(ep_id[2:])
        folder = _episode_folder_for(ep_num)
        if folder is not None:
            return folder / "clips"
    return default

@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, user: User = Depends(require_auth)):
    """Get job status."""
    job = store.get_job_for_user(job_id, user.id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Collect generated clips. For library jobs the clips_dir is on the
    # user's drive (resolved from podcast_dir + EP folder); curation.json
    # lives next to it. For upload jobs both live under DATA_DIR/{job_id}.
    clips = []
    if job.status in ["processing", "completed", "paused"]:
        clips_dir = _resolve_clips_dir(job_id, job.episode_id)
        job_dir = clips_dir.parent

        # Try to load curation metadata for richer clip info
        curation = _load_curation(job_dir)
        
        def _clip_meta(index: int) -> dict:
            """Get curation metadata for clip at index (1-based clip_XX)."""
            if index <= len(curation):
                c = curation[index - 1]
                return {
                    "title": c.get("title", f"Clip {index}"),
                    "summary": c.get("summary", ""),
                    "score": c.get("virality_score", {}).get("total", 0) if isinstance(c.get("virality_score"), dict) else c.get("virality_score", 0),
                    "start_time": c.get("start_time", 0),
                    "end_time": c.get("end_time", 0),
                }
            return {"title": f"Clip {index}", "summary": "", "score": 0, "start_time": 0, "end_time": 0}
        
        # Scan approved folder. Skip AppleDouble shadow files (`._clip_XX.mp4`)
        # that macOS creates on non-HFS drives — they have the same glob hit
        # but are 4 KB metadata stubs, not real clips.
        if (clips_dir / "approved").exists():
            approved_files = [
                p for p in sorted((clips_dir / "approved").glob("*.mp4"))
                if not p.name.startswith("._")
            ]
            for i, clip_file in enumerate(approved_files):
                # Extract clip number from filename (clip_01.mp4 -> 1)
                try:
                    clip_num = int(clip_file.stem.split("_")[1])
                except (IndexError, ValueError):
                    clip_num = i + 1
                meta = _clip_meta(clip_num)
                dur = _get_video_duration(clip_file)
                clips.append(Clip(
                    id=i+1,
                    filename=clip_file.name,
                    start_time=meta["start_time"],
                    end_time=meta["end_time"],
                    duration=round(dur, 1),
                    virality_score=meta["score"] or 85,
                    title=meta["title"],
                    summary=meta["summary"] or "Aprobado automáticamente",
                    status="approved",
                    download_url=f"/api/clips/{job_id}/{clip_file.name}"
                ))
        
        # Scan review folder (same AppleDouble filter as above).
        if (clips_dir / "review").exists():
            base_id = len(clips)
            review_files = [
                p for p in sorted((clips_dir / "review").glob("*.mp4"))
                if not p.name.startswith("._")
            ]
            for i, clip_file in enumerate(review_files):
                try:
                    clip_num = int(clip_file.stem.split("_")[1])
                except (IndexError, ValueError):
                    clip_num = base_id + i + 1
                meta = _clip_meta(clip_num)
                dur = _get_video_duration(clip_file)
                clips.append(Clip(
                    id=base_id+i+1,
                    filename=clip_file.name,
                    start_time=meta["start_time"],
                    end_time=meta["end_time"],
                    duration=round(dur, 1),
                    virality_score=meta["score"] or 75,
                    title=meta["title"],
                    summary=meta["summary"] or "Requiere revisión manual",
                    status="review",
                    download_url=f"/api/clips/{job_id}/{clip_file.name}"
                ))
    
    try:
        status = JobStatus(job.status)
    except ValueError:
        status = JobStatus.ERROR
    
    return JobResponse(
        id=job.job_id,
        status=status,
        filename=job.episode_id,
        created_at=job.created_at,
        progress=job.progress,
        message=job.message,
        clips=clips,
        error=job.error
    )

@router.get("/jobs/{job_id}/critic-decisions")
async def get_critic_decisions(job_id: str, user: User = Depends(require_auth)):
    """Return the Critic's full decision (approved + rejected) for a job.

    Reads critic_decisions.json from the episode folder and joins it with
    any feedback the user has previously given on the same clip timestamps.
    Front-end shows the rejected entries with the Critic's reasoning and
    the user's prior verdict + note (so they can revise).
    """
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    clips_dir = _resolve_clips_dir(job_id, job.episode_id)
    decisions_path = clips_dir.parent / "critic_decisions.json"

    if not decisions_path.exists():
        return {
            "episode_id": job.episode_id,
            "available": False,
            "approved": [],
            "rejected": [],
            "message": (
                "No Critic decisions saved for this job. Re-process the "
                "episode (Process Again) to capture them."
            ),
        }

    try:
        decisions = json.loads(decisions_path.read_text())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not parse decisions: {e}")

    # Pull existing feedback so the UI can pre-fill the user's verdict.
    feedback_rows = store.get_critic_feedback_for_episode(job.episode_id)
    feedback_by_range: dict[tuple, dict] = {
        (round(f["start_time"], 2), round(f["end_time"], 2)): f
        for f in feedback_rows
    }

    approved: list[dict] = []
    rejected: list[dict] = []
    for d in decisions:
        key = (round(float(d.get("start_time", 0)), 2), round(float(d.get("end_time", 0)), 2))
        fb = feedback_by_range.get(key)
        entry = {
            "start_time": d.get("start_time"),
            "end_time": d.get("end_time"),
            "duration": round(
                float(d.get("end_time", 0)) - float(d.get("start_time", 0)), 1
            ),
            "title": d.get("title"),
            "summary": d.get("summary"),
            "reasoning": d.get("reasoning"),
            "approved": bool(d.get("approved", False)),
            "user_verdict": fb["user_verdict"] if fb else None,
            "user_note": fb["user_note"] if fb else None,
        }
        (approved if entry["approved"] else rejected).append(entry)

    return {
        "episode_id": job.episode_id,
        "available": True,
        "approved": approved,
        "rejected": rejected,
        "counts": {"approved": len(approved), "rejected": len(rejected)},
    }


@router.get("/episodes/{episode_number}/identify/status")
async def identify_status(episode_number: int, user: User = Depends(require_auth)):
    """Has the user already labeled speakers for this episode?

    UI calls this before kicking off processing to decide whether to
    show the speaker-identification modal or proceed straight to
    rendering with the locked mapping.
    """
    from packages.clips.audio.identification import load_labels
    folder = _episode_folder_for(episode_number)
    if folder is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    labels = load_labels(folder)
    return {
        "labeled": labels is not None and not labels.get("_skipped"),
        "skipped": bool(labels and labels.get("_skipped")),
        "labels": labels,
    }


@router.post("/episodes/{episode_number}/identify/prepare")
async def identify_prepare(episode_number: int, user: User = Depends(require_auth)):
    """Run the preflight: detect face thumbnails + extract per-speaker
    audio samples. Returns a manifest with face/speaker IDs the UI
    needs to populate the modal.

    Synchronous on purpose — the modal blocks waiting for this. Costs
    ~20-40 s on a 30 min episode (30 sampled frames + MTCNN + N short
    ffmpeg cuts for audio samples).
    """
    from packages.clips.audio.identification import (
        prepare_identification, load_labels,
    )
    folder = _episode_folder_for(episode_number)
    if folder is None:
        raise HTTPException(status_code=404, detail="Episode not found")

    # Pull speaker segments from whichever transcript exists. Supabase
    # transcripts already store speaker labels (A→SPEAKER_00 etc.);
    # local transcripts get them from ECAPA via _try_diarize.
    transcript_path = folder / "transcript.json"
    segments: list[dict] = []
    if transcript_path.exists():
        try:
            data = json.loads(transcript_path.read_text())
            for s in data.get("segments", []):
                if s.get("speaker"):
                    segments.append({
                        "start": float(s["start"]),
                        "end": float(s["end"]),
                        "speaker": s["speaker"],
                    })
        except Exception as e:
            print(f"[identify] could not parse transcript: {e}")

    try:
        manifest = prepare_identification(folder, segments)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Preflight failed: {e}")

    return {
        "episode_id": f"EP{episode_number:03d}",
        "faces": manifest["faces"],
        "speakers": manifest["speakers"],
        "existing_labels": load_labels(folder),
    }


@router.get("/episodes/{episode_number}/identify/face/{face_id}.jpg")
async def identify_face_thumb(
    episode_number: int, face_id: str, user: User = Depends(require_auth),
):
    """Serve the cropped face thumbnail for one identity."""
    folder = _episode_folder_for(episode_number)
    if folder is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    safe = (folder / ".identification").resolve()
    target = (safe / f"{face_id}.jpg").resolve()
    if not target.is_relative_to(safe) or not target.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(target, media_type="image/jpeg")


@router.get("/episodes/{episode_number}/identify/audio/{speaker_id}.wav")
async def identify_audio_sample(
    episode_number: int, speaker_id: str, user: User = Depends(require_auth),
):
    """Serve the speaker's audio sample (6-7 s WAV)."""
    folder = _episode_folder_for(episode_number)
    if folder is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    safe = (folder / ".identification").resolve()
    target = (safe / f"{speaker_id}.wav").resolve()
    if not target.is_relative_to(safe) or not target.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(target, media_type="audio/wav")


@router.post("/episodes/{episode_number}/identify/labels")
async def identify_save_labels(
    episode_number: int,
    payload: dict,
    user: User = Depends(require_auth),
):
    """Persist the user's speaker↔face mapping.

    Payload shape:
        {
          "skipped": false,
          "labels": {
            "SPEAKER_00": {"name": "Juan Pablo", "face_id": "FACE_01"},
            "SPEAKER_01": {"name": "Santiago Cortés", "face_id": "FACE_00"}
          }
        }

    `skipped=true` short-circuits L3 and tells the pipeline to use L2
    (episode-level auto mapping) for this episode.
    """
    from packages.clips.audio.identification import save_labels
    folder = _episode_folder_for(episode_number)
    if folder is None:
        raise HTTPException(status_code=404, detail="Episode not found")

    if payload.get("skipped"):
        save_labels(folder, {"_skipped": True})
        return {"status": "skipped"}

    labels = payload.get("labels") or {}
    if not isinstance(labels, dict) or not labels:
        raise HTTPException(status_code=400, detail="labels must be a non-empty dict")

    # Normalize each entry to {name, face_ids: [...]}.
    # Backward compat: accept legacy single face_id by lifting into face_ids.
    normalized: dict = {}
    for spk, info in labels.items():
        if not isinstance(info, dict):
            raise HTTPException(status_code=400, detail=f"{spk} is not an object")
        name = (info.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail=f"{spk} missing name")
        face_ids = info.get("face_ids")
        if face_ids is None:
            single = info.get("face_id")
            face_ids = [single] if single else []
        face_ids = [f for f in (face_ids or []) if f]
        if not face_ids:
            raise HTTPException(
                status_code=400, detail=f"{spk} must have at least one face_id"
            )
        normalized[spk] = {"name": name, "face_ids": face_ids}

    save_labels(folder, normalized)
    return {"status": "saved", "count": len(normalized)}


@router.delete("/episodes/{episode_number}/identify/labels")
async def identify_clear_labels(
    episode_number: int, user: User = Depends(require_auth),
):
    """Wipe the saved labels so the modal shows again on next process."""
    folder = _episode_folder_for(episode_number)
    if folder is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    path = folder / "speaker_face_labels.json"
    if path.exists():
        path.unlink()
    return {"status": "cleared"}


@router.get("/critic-learnings")
async def get_critic_learnings(user: User = Depends(require_auth)):
    """Return the Critic's current long-term learnings.

    These are distilled rules built up over time from the user's feedback
    notes (via the LearningSynthesizer). Shown in the UI so the user can
    see what the Critic has internalized; injected into the Critic's
    system prompt on every run as persistent guidance.
    """
    learnings = store.get_critic_learnings()
    return {"count": len(learnings), "learnings": learnings}


@router.post("/critic-feedback")
async def save_critic_feedback(payload: dict, user: User = Depends(require_auth)):
    """Save the user's verdict on a Critic rejection (or approval).

    Payload:
        {
          "episode_id":  "EP021",
          "start_time":   45.0,
          "end_time":     72.0,
          "title":        "...",      # optional, for display
          "summary":      "...",      # optional, for display
          "critic_reasoning": "...",  # what the Critic said
          "user_verdict": "agree" | "disagree" | "neutral",
          "user_note":    "explica por qué"  # central signal, captured for
                                              # both agree and disagree
        }
    Re-submitting for the same (episode, start, end) overwrites the
    previous row. Phase B will read this table to inject examples into
    the Critic system prompt on the next run.
    """
    required = ("episode_id", "start_time", "end_time", "user_verdict")
    missing = [k for k in required if k not in payload]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required fields: {', '.join(missing)}",
        )
    verdict = payload["user_verdict"]
    if verdict not in ("agree", "disagree", "neutral"):
        raise HTTPException(
            status_code=400,
            detail="user_verdict must be one of: agree, disagree, neutral",
        )

    row_id = store.save_critic_feedback(
        episode_id=payload["episode_id"],
        start_time=float(payload["start_time"]),
        end_time=float(payload["end_time"]),
        title=payload.get("title"),
        summary=payload.get("summary"),
        critic_reasoning=payload.get("critic_reasoning"),
        user_verdict=verdict,
        user_note=payload.get("user_note"),
    )
    return {"status": "saved", "id": row_id}


@router.get("/clips/{job_id}/rejected")
async def list_rejected_clips(job_id: str, user: User = Depends(require_auth)):
    """List all rejected clips for a job, with age info."""
    import time
    job = store.get_job(job_id)
    clips_dir = (
        _resolve_clips_dir(job_id, job.episode_id if job else None) / "rejected"
    ).resolve()
    
    if not clips_dir.exists():
        return []
    
    now = time.time()
    results = []
    for f in sorted(clips_dir.glob("*.mp4")):
        if f.name.startswith("._"):
            continue
        age_seconds = now - f.stat().st_mtime
        days_remaining = max(0, 30 - int(age_seconds / 86400))
        dur = _get_video_duration(f)
        results.append({
            "filename": f.name,
            "rejected_at": f.stat().st_mtime,
            "days_remaining": days_remaining,
            "duration": round(dur, 1),
            "download_url": f"/api/clips/{job_id}/{f.name}"
        })
    
    return results

@router.get("/clips/{job_id}/{filename}")
async def get_clip(job_id: str, filename: str, user: User = Depends(require_auth)):
    """Serve a generated clip."""
    job = store.get_job(job_id)
    safe_dir = _resolve_clips_dir(job_id, job.episode_id if job else None).resolve()
    
    # Check approved folder
    path_approved = (safe_dir / "approved" / filename).resolve()
    if not path_approved.is_relative_to(safe_dir):
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    if path_approved.exists():
        return FileResponse(path_approved)
        
    # Check review folder
    path_review = (safe_dir / "review" / filename).resolve()
    if not path_review.is_relative_to(safe_dir):
        raise HTTPException(status_code=400, detail="Invalid filename")
        
    if path_review.exists():
        return FileResponse(path_review)
        
    # Check rejected folder
    path_rejected = (safe_dir / "rejected" / filename).resolve()
    if not path_rejected.is_relative_to(safe_dir):
        raise HTTPException(status_code=400, detail="Invalid filename")
        
    if path_rejected.exists():
        return FileResponse(path_rejected)
        
    raise HTTPException(status_code=404, detail="Clip not found")

@router.post("/clips/{job_id}/{filename}/open")
async def open_clip_location(job_id: str, filename: str, user: User = Depends(require_auth)):
    """Open the local folder containing the clip (macOS)."""
    import subprocess
    job = store.get_job(job_id)
    safe_dir = _resolve_clips_dir(job_id, job.episode_id if job else None).resolve()
    
    path_approved = (safe_dir / "approved" / filename).resolve()
    path_review = (safe_dir / "review" / filename).resolve()
    
    target_path = None
    if path_approved.exists():
        target_path = path_approved
    elif path_review.exists():
        target_path = path_review
        
    if not target_path:
        raise HTTPException(status_code=404, detail="Clip not found locally")
        
    try:
        # -R flag selects the file in Finder
        subprocess.run(["open", "-R", str(target_path)])
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/clips/{job_id}/{filename}/approve")
async def approve_clip(job_id: str, filename: str, user: User = Depends(require_auth)):
    """Approve a clip: move it from review/ to approved/."""
    import shutil
    job = store.get_job(job_id)
    clips_dir = _resolve_clips_dir(job_id, job.episode_id if job else None).resolve()
    
    source = clips_dir / "review" / filename
    dest = clips_dir / "approved" / filename
    
    if not source.exists():
        # Already in approved or doesn't exist
        if dest.exists():
            return {"status": "already_approved"}
        raise HTTPException(status_code=404, detail="Clip not found in review folder")
    
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(dest))
    
    # Also move the caption file if it exists
    caption_source = clips_dir / "review" / filename.replace(".mp4", "_caption.txt")
    if caption_source.exists():
        caption_dest = clips_dir / "approved" / filename.replace(".mp4", "_caption.txt")
        shutil.move(str(caption_source), str(caption_dest))
    
    return {"status": "approved", "filename": filename}

@router.post("/clips/{job_id}/{filename}/reject")
async def reject_clip(job_id: str, filename: str, user: User = Depends(require_auth)):
    """Reject a clip: move it to rejected/ (auto-deleted after 30 days)."""
    import shutil
    job = store.get_job(job_id)
    clips_dir = _resolve_clips_dir(job_id, job.episode_id if job else None).resolve()
    rejected_dir = clips_dir / "rejected"
    rejected_dir.mkdir(parents=True, exist_ok=True)
    
    # Find the clip in approved or review
    source = None
    for folder in ["approved", "review"]:
        candidate = clips_dir / folder / filename
        if candidate.exists():
            source = candidate
            break
    
    if not source:
        raise HTTPException(status_code=404, detail="Clip not found")
    
    dest = rejected_dir / filename
    shutil.move(str(source), str(dest))
    
    # Also move the caption file
    caption_name = filename.replace(".mp4", "_caption.txt")
    for folder in ["approved", "review"]:
        caption = clips_dir / folder / caption_name
        if caption.exists():
            shutil.move(str(caption), str(rejected_dir / caption_name))
            break
    
    return {"status": "rejected", "filename": filename}
@router.post("/clips/{job_id}/{filename}/restore")
async def restore_clip(job_id: str, filename: str, user: User = Depends(require_auth)):
    """Restore a rejected clip back to the review folder."""
    import shutil
    job = store.get_job(job_id)
    clips_dir = _resolve_clips_dir(job_id, job.episode_id if job else None).resolve()
    source = clips_dir / "rejected" / filename
    
    if not source.exists():
        raise HTTPException(status_code=404, detail="Clip not found in rejected folder")
    
    dest_dir = clips_dir / "review"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    shutil.move(str(source), str(dest))
    
    # Also restore caption if exists
    caption_name = filename.replace(".mp4", "_caption.txt")
    caption_source = clips_dir / "rejected" / caption_name
    if caption_source.exists():
        shutil.move(str(caption_source), str(dest_dir / caption_name))
    
    return {"status": "restored", "filename": filename}


# ─── Job control: cancel / pause / resume ───────────────────────────────


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, user: User = Depends(require_auth)):
    """Cancel a running job and wipe its workspace.

    Library jobs (id starts with EPNNN-): we kill in-flight ffmpeg, drop the
    JobStore row and clear curation.json so the next "Process" starts fresh.
    We do NOT delete the clips already rendered to the user's drive — those
    are theirs to keep (use the "Reset / start fresh" button for full wipe).

    Upload jobs (UUID id): full wipe — kill ffmpeg + delete the job folder
    under DATA_DIR + drop the JobStore row. "As if nothing happened."
    """
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("processing", "pending", "paused", "resuming"):
        raise HTTPException(status_code=400, detail=f"Job is not running (status: {job.status})")

    # 1. Tell the pipeline to stop at the next checkpoint.
    if not store.cancel_job(job_id):
        raise HTTPException(status_code=400, detail="Could not cancel job")

    # 2. Set the abort_event so the pipeline returns at the next clip boundary.
    try:
        from server.dependencies import get_abort_event
        get_abort_event(job_id).set()
    except Exception:
        pass

    # 3. Kill any in-flight ffmpeg subprocesses immediately. The pipeline's
    #    per-clip try/except absorbs the CalledProcessError; abort_event then
    #    short-circuits the next iteration. Killed in ~0.5 s, not ~60 s.
    killed = 0
    try:
        from packages.core.process_registry import kill_job_subprocesses
        killed = kill_job_subprocesses(job_id)
    except Exception:
        pass

    # 4. Wipe workspace. Upload jobs: nuke DATA_DIR/{job_id}. Library jobs:
    #    only nuke curation.json so the next run starts fresh (we never touch
    #    clips the user already rendered to their own drive).
    is_library_job = job_id.upper().startswith("EP") and "-" in job_id
    workspace = DATA_DIR / job_id
    try:
        if is_library_job:
            curation = workspace / "curation.json"
            if curation.exists():
                curation.unlink()
        else:
            if workspace.exists():
                shutil.rmtree(workspace, ignore_errors=True)
    except Exception:
        pass

    # 5. Drop the row — UI treats this as "no active job", goes back to upload.
    try:
        store.delete_job(job_id)
    except Exception:
        pass

    return {
        "status": "cancelled",
        "job_id": job_id,
        "killed_subprocesses": killed,
        "workspace_removed": not is_library_job,
    }


@router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str, user: User = Depends(require_auth)):
    """Pause a running job INSTANTLY.

    SIGTERMs every ffmpeg subprocess registered to the job (typically the
    in-flight clip render), so the pipeline returns within ~0.5 s instead of
    waiting for the current clip to finish (~60 s previously). Resume
    re-renders the in-flight clip from scratch; already-checkpointed clips
    are skipped via start_from_clip.
    """
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "processing":
        raise HTTPException(status_code=400, detail=f"Job is not processing (status: {job.status})")
    if not store.pause_job(job_id):
        raise HTTPException(status_code=400, detail="Could not pause job")
    try:
        from server.dependencies import get_abort_event
        get_abort_event(job_id).set()
    except Exception:
        pass
    killed = 0
    try:
        from packages.core.process_registry import kill_job_subprocesses
        killed = kill_job_subprocesses(job_id)
    except Exception:
        pass
    return {
        "status": "paused",
        "job_id": job_id,
        "killed_subprocesses": killed,
    }


@router.post("/jobs/{job_id}/resume")
async def resume_job_endpoint(
    job_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_auth),
):
    """Resume a paused job from the last successful clip checkpoint.

    Library episodes (id starts with EP###) re-enter via BatchProcessor with
    start_from_clip — the same path /episodes/{n}/process uses, so curation.json
    is picked up and only the unfinished clips are rendered. Upload jobs go
    through the worker queue (legacy path).
    """
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "paused":
        raise HTTPException(status_code=400, detail=f"Job is not paused (status: {job.status})")

    # Race-condition guard. /pause now SIGTERMs ffmpeg synchronously, so the
    # old 60 s wait is gone. Whisper / MLX inference is not a killable
    # subprocess, but per-clip Whisper runs are short (<5 s on MLX) and
    # finish before the worker thread returns. We accept the rare double-
    # load risk in exchange for a snappy resume — pressing Resume right
    # after Pause feels broken with any guard at all.

    # Clear stale abort_event before re-arming the pipeline
    try:
        from server.dependencies import clear_abort_event
        clear_abort_event(job_id)
    except Exception:
        pass

    saved_req = store.get_config(job_id) or {}
    ep_id = job.episode_id or ""

    store.resume_job(job_id)
    try:
        from server.dependencies import clear_abort_event
        clear_abort_event(job_id)
    except Exception:
        pass

    # Library episode (EPNNN) → mirror the first-launch path: BatchProcessor
    # in a background task, with start_from_clip = checkpoint.
    if ep_id.startswith("EP"):
        try:
            ep_num = int(ep_id[2:])
        except ValueError:
            ep_num = None

        if ep_num is not None:
            from server.processor import BatchProcessor

            t_url = saved_req.get("supabase_url") or settings.transcript_supabase_url or None
            t_key = saved_req.get("supabase_key") or settings.transcript_supabase_key or None
            transcription_source = saved_req.get("transcription_source", "local_whisper")
            effective_source = transcription_source
            if t_url and t_key and transcription_source == "local_whisper":
                effective_source = "supabase_custom"
            use_sb = effective_source == "supabase_custom"

            transcription_config = {
                "source_type": effective_source,
                "assemblyai_api_key": saved_req.get("assemblyai_key"),
                "supabase_url": t_url,
                "supabase_key": t_key,
            }

            def run_resume_task(jid, num, start_clip):
                try:
                    # Surface every setup step. Without these messages the UI
                    # sits frozen at "Resuming…" for 5-15 s while we re-init
                    # the BatchProcessor, scan episodes, re-load transcript
                    # and curation, and skip already-rendered clips.
                    paused_pct = max(5, (start_clip / max(1, start_clip + 1)) * 70)
                    store.update_progress(
                        jid,
                        int(paused_pct),
                        f"Reanudando desde clip {start_clip + 1}…",
                    )
                    processor = BatchProcessor(
                        external_drive_path=settings.podcast_dir,
                        min_duration=saved_req.get("min_duration", 30),
                        max_duration=saved_req.get("max_duration", 90),
                        min_score=saved_req.get("min_score", 70),
                        use_supabase=use_sb,
                        transcription_config=transcription_config,
                    )
                    store.update_progress(jid, int(paused_pct), "Buscando episodio…")
                    eps = processor.discover_episodes(start=num, end=num)
                    if not eps:
                        raise Exception(f"Episode {num} not found at {settings.podcast_dir}")
                    store.update_progress(
                        jid,
                        int(paused_pct),
                        f"Reanudando clip {start_clip + 1} (transcript + curación en caché)…",
                    )
                    clips_count = processor.process_episode(
                        eps[0], job_id=jid, start_from_clip=start_clip
                    )
                    # Honor pause/cancel that may have happened during resume
                    current = store.get_job(jid)
                    if current and current.status in ("paused", "cancelled"):
                        return
                    store.complete_job(jid, clips_count)
                except Exception as e:
                    store.fail_job(jid, str(e))

            background_tasks.add_task(run_resume_task, job_id, ep_num, job.last_clip_index)
            return {
                "status": "resuming",
                "job_id": job_id,
                "resuming_from_clip": job.last_clip_index,
            }

    # Fallback: non-EP job (upload) — keep the worker-queue path.
    payload = {
        "video_path": saved_req.get("video_path"),
        "episode_id": ep_id,
        "settings": {
            "min_duration": saved_req.get("min_duration", 30),
            "max_duration": saved_req.get("max_duration", 90),
            "min_score": saved_req.get("min_score", 70),
        },
        "transcription_config": {
            "source_type": saved_req.get("transcription_source", "local_whisper"),
            "supabase_url": saved_req.get("supabase_url") or settings.transcript_supabase_url or None,
            "supabase_key": saved_req.get("supabase_key") or settings.transcript_supabase_key or None,
        },
        "start_from_clip": job.last_clip_index,
        "user_id": "local",
    }
    asyncio.create_task(job_queue.enqueue(job_id=job_id, payload=payload))
    return {
        "status": "resuming",
        "job_id": job_id,
        "resuming_from_clip": job.last_clip_index,
    }


def cleanup_rejected_clips(max_age_days: int = 30):
    """Delete rejected clips older than max_age_days. Runs on server startup."""
    import time
    now = time.time()
    max_age_seconds = max_age_days * 86400
    deleted = 0
    
    if not DATA_DIR.exists():
        return
    
    for job_dir in DATA_DIR.iterdir():
        if not job_dir.is_dir():
            continue
        rejected_dir = job_dir / "clips" / "rejected"
        if not rejected_dir.exists():
            continue
        
        for f in rejected_dir.iterdir():
            age = now - f.stat().st_mtime
            if age > max_age_seconds:
                f.unlink()
                deleted += 1
        
        # Remove the rejected folder if empty
        if rejected_dir.exists() and not any(rejected_dir.iterdir()):
            rejected_dir.rmdir()
    
    if deleted > 0:
        print(f"🗑️ Cleaned up {deleted} rejected clips older than {max_age_days} days")

# Run cleanup on module load (i.e. server startup)
try:
    cleanup_rejected_clips()
except Exception as e:
    import logging
    logging.getLogger(__name__).error(f"[Startup] Failed to run cleanup_rejected_clips: {e}", exc_info=True)

# ─── Face Tracking ───────────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/extract-faces")
async def extract_faces(job_id: str, user: User = Depends(require_auth)):
    """Scan video to extract unique biometric face identities (MTCNN + FaceNet)."""
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    def run_extractor():
        tracker = FaceTracker()
        video_path = DATA_DIR / job_id / "source.mp4"
        output_dir = DATA_DIR / job_id / "faces"
        if not video_path.exists():
            return {}
        return tracker.extract_unique_faces(str(video_path), str(output_dir))
        
    faces = await asyncio.to_thread(run_extractor)
    
    # Save a JSON manifest for the GET endpoint
    with open(DATA_DIR / job_id / "faces.json", "w") as f:
        json.dump(faces, f)
        
    return {"status": "success", "faces": faces}

@router.get("/jobs/{job_id}/faces")
async def get_faces(job_id: str, user: User = Depends(require_auth)):
    """Returns the biometric face map {FACE_XX: filename} and role assignments if available."""
    json_path = DATA_DIR / job_id / "faces.json"
    if not json_path.exists():
        return {"status": "pending", "faces": {}}
    
    with open(json_path, "r") as f:
        faces = json.load(f)
    
    # Include role assignments if they exist
    roles_path = DATA_DIR / job_id / "roles.json"
    roles = {}
    if roles_path.exists():
        with open(roles_path, "r") as f:
            roles = json.load(f)
    
    return {"status": "success", "faces": faces, "roles": roles}

@router.get("/jobs/{job_id}/faces/{filename}")
async def get_face_image(job_id: str, filename: str, user: User = Depends(require_auth)):
    """Serves the actual thumbnail image of a face."""
    safe_dir = (DATA_DIR / job_id / "faces").resolve()
    path = (safe_dir / filename).resolve()
    
    # Path traversal protection
    if not path.is_relative_to(safe_dir) or not path.exists():
        raise HTTPException(status_code=404, detail="Face not found")
        
    return FileResponse(path)

@router.post("/jobs/{job_id}/assign-roles")
async def assign_roles(job_id: str, role_map: dict, user: User = Depends(require_auth)):
    """
    Assign semantic roles to biometric face IDs.
    
    Body: {"FACE_00": "Host", "FACE_01": "Guest"}
    
    These roles are used by the reframer to determine which face to 
    follow based on speaker diarization (e.g., follow the Host).
    """
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Validate that referenced face IDs exist
    faces_path = DATA_DIR / job_id / "faces.json"
    if faces_path.exists():
        with open(faces_path, "r") as f:
            known_faces = json.load(f)
        
        unknown = [fid for fid in role_map if fid not in known_faces]
        if unknown:
            raise HTTPException(
                status_code=400, 
                detail=f"Unknown face IDs: {unknown}. Known: {list(known_faces.keys())}"
            )
    
    # Save role assignments
    roles_path = DATA_DIR / job_id / "roles.json"
    with open(roles_path, "w") as f:
        json.dump(role_map, f)
    
    return {"status": "success", "roles": role_map}


# ─── Episodes (Local Library) ───────────────────────────────────────────────

@router.get("/episodes", response_model=List[EpisodeResponse])
async def list_episodes(user: User = Depends(require_auth)):
    """List episodes from configured podcast directory."""
    try:
        if not settings.podcast_dir.exists():
            return []
        from server.processor import BatchProcessor
        processor = BatchProcessor(external_drive_path=settings.podcast_dir)

        episodes = processor.discover_episodes(start=1, end=9999)

        # Cross-reference with JobStore so "Done" reflects an actually
        # completed job, not just the presence of a half-rendered folder
        # left over from an in-flight or aborted run.
        latest_jobs = store.get_latest_jobs_per_episode()

        out: list[EpisodeResponse] = []
        for ep in episodes:
            ep_id = f"EP{ep.episode_number:03d}"
            job = latest_jobs.get(ep_id)
            has_clips_folder = (ep.clips_folder / "approved").exists() or (
                ep.clips_folder / "review"
            ).exists()

            if job is not None:
                # A run exists for this episode — trust JobStore.
                is_done = job.status == "completed"
                job_status = job.status
                job_progress = job.progress
            else:
                # No run on record — fall back to disk so legacy episodes
                # processed before JobStore tracking still surface as done.
                is_done = has_clips_folder
                job_status = None
                job_progress = None

            out.append(
                EpisodeResponse(
                    id=ep_id,
                    number=ep.episode_number,
                    title=ep.episode_folder.name,
                    has_video=ep.video_path.exists(),
                    has_transcript=True if ep.transcript_path else False,
                    is_processed=is_done,
                    path=str(ep.episode_folder),
                    job_status=job_status,
                    job_progress=job_progress,
                )
            )
        return out
    except Exception as e:
        print(f"Error listing episodes: {e}")
        return []

@router.post("/episodes/{episode_number}/process", response_model=JobResponse)
async def process_episode_endpoint(
    episode_number: int,
    background_tasks: BackgroundTasks,
    req: ProcessRequest,
    user: User = Depends(require_auth)
):
    """Trigger processing for a specific episode from the library."""
    from server.processor import BatchProcessor
    
    # Create Job ID
    # Create Stable Job ID for library episodes
    job_id = f"EP{episode_number:03d}-process"
    
    # If job is already running, just return it
    existing = store.get_job(job_id)
    if existing and existing.status in ["processing", "pending", "resuming"]:
        return JobResponse(
            id=existing.job_id,
            status=JobStatus(existing.status),
            filename=f"EP{episode_number:03d}",
            created_at=existing.created_at,
            progress=existing.progress,
            message=existing.message
        )

    # Re-process: wipe the cached curation + clip files so the pipeline
    # doesn't short-circuit on existing artifacts. Without this, every
    # clip's "skip if final already exists" check hits and we return
    # clips_generated=0 instantly — UI shows "Done" without re-rendering.
    if req.force_reset:
        ep_folder = _episode_folder_for(episode_number)
        if ep_folder is not None:
            removed = []
            curation = ep_folder / "curation.json"
            if curation.exists():
                curation.unlink()
                removed.append("curation.json")
            clips_root = ep_folder / "clips"
            for sub in ("approved", "review"):
                d = clips_root / sub
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)
                    removed.append(f"clips/{sub}")
            if removed:
                print(f"[force_reset] EP{episode_number:03d} → removed: {removed}")
        # Drop the old DB row too so the resolver picks a fresh job_status
        try:
            store.delete_job(job_id)
        except Exception:
            pass

    # Initialize Job
    store.create_job(
        job_id=job_id,
        episode_id=f"EP{episode_number:03d}",
        config=req.dict(),
        user_id=user.id,
    )
    
    # Prepare batch processor for single episode
    # Respect user-owned Supabase if configured (either per-request or in settings)
    t_url_ep = req.supabase_url or settings.transcript_supabase_url or None
    t_key_ep = req.supabase_key or settings.transcript_supabase_key or None
    eff_source_ep = req.transcription_source
    if t_url_ep and t_key_ep and req.transcription_source == "local_whisper":
        eff_source_ep = "supabase_custom"
    use_sb = eff_source_ep == "supabase_custom"

    def run_batch_task(job_id, ep_num):
        try:
            store.update_progress(job_id, 5, "Initializing batch processor...")
            processor = BatchProcessor(
                external_drive_path=settings.podcast_dir,
                min_duration=req.min_duration,
                max_duration=req.max_duration,
                min_score=req.min_score,
                use_supabase=use_sb,
                transcription_config={
                    "source_type": eff_source_ep,
                    "assemblyai_api_key": getattr(req, "assemblyai_key", None),
                    "supabase_url": t_url_ep,
                    "supabase_key": t_key_ep,
                },
            )
            
            # Find the episode config
            episodes = processor.discover_episodes(start=ep_num, end=ep_num)
            if not episodes:
                raise Exception(f"Episode {ep_num} not found")
                
            ep = episodes[0]
            
            # Run processing
            clips_count = processor.process_episode(ep, job_id=job_id)
            
            store.complete_job(job_id, clips_count)
            
        except Exception as e:
            store.fail_job(job_id, str(e))

    background_tasks.add_task(run_batch_task, job_id, episode_number)
    
    return JobResponse(
        id=job_id,
        status=JobStatus.PENDING,
        filename=f"EP{episode_number:03d}",
        created_at=datetime.now(),
        message="Queued for processing"
    )

@router.post("/episodes/{episode_number}/upload-transcript")
async def upload_transcript_endpoint(episode_number: int, user: User = Depends(require_auth)):
    """Upload an episode's local transcript to the user's own Supabase project.

    Requires TRANSCRIPT_SUPABASE_URL and TRANSCRIPT_SUPABASE_KEY configured in
    Settings → Integrations. Returns 412 if not configured.
    """
    if not (settings.transcript_supabase_url and settings.transcript_supabase_key):
        raise HTTPException(
            status_code=412,
            detail="Configure your own Supabase URL and key in Settings → Integrations first.",
        )
    from server.sources.supabase_transcripts import upload_transcript
    from packages.clips.transcription.transcriber import Transcript
    from server.processor import BatchProcessor
    
    try:
        # Find episode
        processor = BatchProcessor(external_drive_path=settings.podcast_dir, dry_run=True)
        episodes = processor.discover_episodes(start=episode_number, end=episode_number)
        
        if not episodes:
            raise HTTPException(status_code=404, detail=f"Episode {episode_number} not found")
            
        ep = episodes[0]
        
        if not ep.transcript_path or not ep.transcript_path.exists():
            raise HTTPException(status_code=404, detail="Transcript file not found for this episode")
            
        # Load and upload
        transcript = Transcript.load(ep.transcript_path)
        episode_id = f"EP{episode_number:03d}"
        
        success = upload_transcript(
            transcript=transcript,
            episode_id=episode_id,
            episode_title=ep.episode_folder.name
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to upload to Supabase")
            
        return {"status": "success", "message": f"Uploaded {episode_id} to Supabase"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── WebSocket Progress Stream ──────────────────────────────────────────────

@router.websocket("/ws/jobs/{job_id}")
async def websocket_job_status(websocket: WebSocket, job_id: str, token: str = ""):
    """
    Tethers a WebSocket connection to stream real-time progress.
    Auth via ?token= query param (WebSockets can't send Authorization headers).
    """
    await websocket.accept()
    # Local-first MVP: no real auth — server binds to 127.0.0.1.
    # The `token` query param is kept for API compatibility but not validated.
    
    try:
        while True:
            job = store.get_job(job_id)
            if not job:
                await websocket.send_json({"event": "error", "data": {"error": "Job not found"}})
                await asyncio.sleep(2)
                continue
            
            if job.status in ["completed"]:
                await websocket.send_json({
                    "event": "completed",
                    "data": {"progress": 100, "message": job.message, "status": job.status}
                })
                break
            elif job.status in ["failed", "error", "cancelled"]:
                await websocket.send_json({
                    "event": "error",
                    "data": {"error": job.message or "Processing failed"}
                })
                break
            else:
                await websocket.send_json({
                    "event": "progress",
                    "data": {
                        "progress": job.progress,
                        "message": job.message,
                        "status": job.status
                    }
                })
                
            # Stream every 1.5s
            await asyncio.sleep(1.5)
            
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket Error on {job_id}: {e}")
        
    try:
        await websocket.close()
    except Exception:
        pass
