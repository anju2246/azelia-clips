import shutil
import uuid
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException, Form, Header
from fastapi.responses import FileResponse
from src.api.models import (
    JobResponse, JobStatus, ProcessRequest, Clip,
    SettingsResponse, UpdateSettingsRequest, EpisodeResponse
)
from src.api.processor import SingleVideoProcessor
from src.job_store import get_job_store
from src.config import settings
from src.batch_processor import BatchProcessor
from typing import List

router = APIRouter()
store = get_job_store()

# Base directory for job data
DATA_DIR = Path("data/jobs")
DATA_DIR.mkdir(parents=True, exist_ok=True)

def run_processing_task(job_id: str, file_path: Path, settings: ProcessRequest, authorization: str = None, transcription_config: dict = None):
    """Background task to run the processing pipeline."""
    try:
        # Update status to processing
        store.update_progress(job_id, 0, "Starting processing...", status="processing")
        
        # Initialize processor
        # Output will be in data/jobs/{job_id}/clips
        processor = SingleVideoProcessor(
            output_dir=file_path.parent,
            min_duration=settings.min_duration,
            max_duration=settings.max_duration,
            min_score=settings.min_score,
            use_supabase=(transcription_config.get("source_type") == "supabase_custom"),
            auth_token=authorization,
            transcription_config=transcription_config
        )
        
        # Run processing
        # This blocks until finished (which is fine for a background thread)
        clips_count = processor.process_single(file_path, job_id=job_id)
        
        # Mark complete
        store.complete_job(job_id, clips_count)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        store.fail_job(job_id, str(e))

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
    authorization: str | None = Header(default=None)
):
    """Upload a video and start processing."""
    
    # Validate file type
    if not file.filename.lower().endswith(('.mp4', '.mov', '.mkv')):
        raise HTTPException(status_code=400, detail="Invalid file type. Only MP4, MOV, MKV supported.")
    
    # Create Job ID
    job_id = str(uuid.uuid4())
    job_dir = DATA_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    
    # Clean token
    auth_token = None
    if authorization:
        auth_token = authorization.replace("Bearer ", "").strip()
    
    # Save file
    file_path = job_dir / "source.mp4"
    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")
    
    # Create Job config
    settings = ProcessRequest(
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
    
    # Initialize Job in Store
    store.create_job(
        job_id=job_id,
        episode_id=f"UPLOAD-{job_id[:8]}", # Dummy episode ID
        config=settings.dict()
    )
    
    # Start Background Task
    background_tasks.add_task(run_processing_task, job_id, file_path, settings, authorization, transcription_config)
    
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

@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str):
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
                # Basic info from filename/metadata would be better, but for now scan files
                clips.append(Clip(
                    id=i+1,
                    filename=clip_file.name,
                    start_time=0, 
                    end_time=0,
                    duration=0, # TODO: Read real metadata
                    virality_score=85, # Mock score if not persisted
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
    path = DATA_DIR / job_id / "clips" / "approved" / filename
    if not path.exists():
        # Check review folder
        path = DATA_DIR / job_id / "clips" / "review" / filename
    
    if not path.exists():
        raise HTTPException(status_code=404, detail="Clip not found")
        
    return FileResponse(path)

# --- Local Mode Endpoints ---

@router.get("/settings", response_model=SettingsResponse)
async def get_settings():
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
        # Update runtime setting
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

@router.get("/episodes", response_model=List[EpisodeResponse])
async def list_episodes():
    """List episodes from configured podcast directory."""
    try:
        processor = BatchProcessor(external_drive_path=settings.podcast_dir, dry_run=True)
        # Note: discover_episodes might fail if dir doesn't exist
        if not settings.podcast_dir.exists():
             return []
             
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
                # We can add auth token here if needed
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
    from src.sources.supabase_transcripts import upload_transcript
    from src.asr.transcriber import Transcript
    
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

def mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return ""
    return f"{key[:4]}...{key[-4:]}"
