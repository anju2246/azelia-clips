"""
Server Routes — Clip Processing, Jobs, Faces, Episodes, WebSocket
"""

import shutil
import uuid
import json
import asyncio
from pathlib import Path
from datetime import datetime
from typing import List

from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException, Form, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlmodel import Session

from server.models import (
    JobResponse, JobStatus, ProcessRequest, ProcessLocalRequest, Clip,
    EpisodeResponse
)
from server.dependencies import job_queue
from server.workers.job_store import get_job_store
from packages.core.config import settings
from server.middleware.auth import require_auth
from packages.core.db.engine import engine
from packages.core.db.models import Episode
from packages.clips.vision.face_tracker import FaceTracker

router = APIRouter()
store = get_job_store()

# Base directory for job data
DATA_DIR = Path("data/jobs")
DATA_DIR.mkdir(parents=True, exist_ok=True)


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
    user: dict = Depends(require_auth)
):
    """Upload a video and start processing."""
    
    # Validate file type
    if not file.filename.lower().endswith(('.mp4', '.mov', '.mkv')):
        raise HTTPException(status_code=400, detail="Invalid file type. Only MP4, MOV, MKV supported.")
    
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
    
    # Create Transcription Config
    transcription_config = {
        "source_type": transcription_source,
        "assemblyai_api_key": assemblyai_key,
        "supabase_url": supabase_url,
        "supabase_key": supabase_key
    }
    
    # Initialize Job in Store (Legacy for UI compatibility)
    store.create_job(
        job_id=job_id,
        episode_id=file.filename,
        config=process_settings.dict()
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
        "auth_token": auth_token
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
    user: dict = Depends(require_auth)
):
    """Process a video directly from the local file system using the Server-Side Picker."""
    import os
    
    file_path_obj = Path(req.video_path)
    if not file_path_obj.exists() or not file_path_obj.is_file():
        raise HTTPException(status_code=400, detail="Local file does not exist")
        
    filename = file_path_obj.name
    if not filename.lower().endswith(('.mp4', '.mov', '.mkv')):
        raise HTTPException(status_code=400, detail="Invalid file type. Only MP4, MOV, MKV supported.")
        
    job_id = str(uuid.uuid4())
    job_dir = DATA_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    
    # Symlink the file instantly instead of copying gigabytes
    target_link = job_dir / "source.mp4"
    try:
        os.symlink(file_path_obj, target_link)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to link local file: {e}")
        
    transcription_config = {
        "source_type": req.transcription_source,
        "assemblyai_api_key": req.assemblyai_key,
        "supabase_url": req.supabase_url,
        "supabase_key": req.supabase_key
    }
    
    # Initialize Job in Store (Legacy for UI compatibility)
    store.create_job(
        job_id=job_id,
        episode_id=filename,
        config=req.dict()
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
        "auth_token": None
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

@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, user: dict = Depends(require_auth)):
    """Get job status."""
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Collect generated clips
    clips = []
    if job.status in ["processing", "completed"]:
        job_dir = DATA_DIR / job_id
        clips_dir = job_dir / "clips"
        
        # Scan approved folder
        if (clips_dir / "approved").exists():
            for i, clip_file in enumerate(sorted((clips_dir / "approved").glob("*.mp4"))):
                clips.append(Clip(
                    id=i+1,
                    filename=clip_file.name,
                    start_time=0, 
                    end_time=0,
                    duration=0,
                    virality_score=85,
                    title=f"Clip {i+1}",
                    summary="Generated clip",
                    status="approved",
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

@router.get("/clips/{job_id}/{filename}")
async def get_clip(job_id: str, filename: str):
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
        
    raise HTTPException(status_code=404, detail="Clip not found")


# ─── Face Tracking ───────────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/extract-faces")
async def extract_faces(job_id: str):
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
async def get_faces(job_id: str):
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
async def get_face_image(job_id: str, filename: str):
    """Serves the actual thumbnail image of a face."""
    safe_dir = (DATA_DIR / job_id / "faces").resolve()
    path = (safe_dir / filename).resolve()
    
    # Path traversal protection
    if not path.is_relative_to(safe_dir) or not path.exists():
        raise HTTPException(status_code=404, detail="Face not found")
        
    return FileResponse(path)

@router.post("/jobs/{job_id}/assign-roles")
async def assign_roles(job_id: str, role_map: dict):
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
async def list_episodes():
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
                is_processed=(ep.clips_folder / "approved").exists(),
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
    req: ProcessRequest
):
    """Trigger processing for a specific episode from the library."""
    from server.processor import BatchProcessor
    
    # Create Job ID
    job_id = str(uuid.uuid4())
    
    # Initialize Job
    store.create_job(
        job_id=job_id,
        episode_id=f"EP{episode_number:03d}",
        config=req.dict()
    )
    
    # Prepare batch processor for single episode
    def run_batch_task(job_id, ep_num):
        try:
            store.update_progress(job_id, 5, "Initializing batch processor...")
            processor = BatchProcessor(
                min_duration=req.min_duration,
                max_duration=req.max_duration,
                min_score=req.min_score,
                use_supabase=(req.transcription_source == "supabase_custom"),
                transcription_config={
                    "source_type": req.transcription_source,
                    "assemblyai_api_key": req.assemblyai_key,
                    "supabase_url": req.supabase_url,
                    "supabase_key": req.supabase_key
                }
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
async def upload_transcript_endpoint(episode_number: int):
    """Upload the transcript for a specific episode to Supabase."""
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
async def websocket_job_status(websocket: WebSocket, job_id: str):
    """
    Tethers a WebSocket connection to stream real-time progress.
    Sends events in {event, data} format matching the frontend LiveProcessingWidget.
    """
    await websocket.accept()
    
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
