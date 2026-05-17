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
        # Check if clips actually exist before counting as processed
        clips_dir = DATA_DIR / job.job_id / "clips"
        has_approved = (clips_dir / "approved").exists() and any((clips_dir / "approved").iterdir())
        has_review = (clips_dir / "review").exists() and any((clips_dir / "review").iterdir())
        
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

@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, user: User = Depends(require_auth)):
    """Get job status."""
    job = store.get_job_for_user(job_id, user.id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Collect generated clips
    clips = []
    if job.status in ["processing", "completed"]:
        job_dir = DATA_DIR / job_id
        clips_dir = job_dir / "clips"
        
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
        
        # Scan approved folder
        if (clips_dir / "approved").exists():
            for i, clip_file in enumerate(sorted((clips_dir / "approved").glob("*.mp4"))):
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
        
        # Scan review folder
        if (clips_dir / "review").exists():
            base_id = len(clips)
            for i, clip_file in enumerate(sorted((clips_dir / "review").glob("*.mp4"))):
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

@router.get("/clips/{job_id}/rejected")
async def list_rejected_clips(job_id: str, user: User = Depends(require_auth)):
    """List all rejected clips for a job, with age info."""
    import time
    clips_dir = (DATA_DIR / job_id / "clips" / "rejected").resolve()
    
    if not clips_dir.exists():
        return []
    
    now = time.time()
    results = []
    for f in sorted(clips_dir.glob("*.mp4")):
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
    safe_dir = (DATA_DIR / job_id / "clips").resolve()
    
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
    safe_dir = (DATA_DIR / job_id / "clips").resolve()
    
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
    clips_dir = (DATA_DIR / job_id / "clips").resolve()
    
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
    clips_dir = (DATA_DIR / job_id / "clips").resolve()
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
    clips_dir = (DATA_DIR / job_id / "clips").resolve()
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
        
        return [
            EpisodeResponse(
                id=f"EP{ep.episode_number:03d}",
                number=ep.episode_number,
                title=ep.episode_folder.name,
                has_video=ep.video_path.exists(),
                has_transcript=True if ep.transcript_path else False,
                is_processed=((ep.clips_folder / "approved").exists() or (ep.clips_folder / "review").exists()),
                path=str(ep.episode_folder)
            ) for ep in episodes
        ]
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

    # Initialize Job
    store.create_job(
        job_id=job_id,
        episode_id=f"EP{episode_number:03d}",
        config=req.dict(),
        user_id=user.id,
    )
    
    # Prepare batch processor for single episode
    def run_batch_task(job_id, ep_num):
        try:
            store.update_progress(job_id, 5, "Initializing batch processor...")
            processor = BatchProcessor(
                external_drive_path=settings.podcast_dir,
                min_duration=req.min_duration,
                max_duration=req.max_duration,
                min_score=req.min_score,
                transcription_config={
                    "source_type": "local_whisper" if req.transcription_source == "supabase_custom" else req.transcription_source,
                    "assemblyai_api_key": getattr(req, "assemblyai_key", None),
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
