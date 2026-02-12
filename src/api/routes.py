import shutil
import uuid
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException, Form, Header
from fastapi.responses import FileResponse
from src.api.models import JobResponse, JobStatus, ProcessRequest, Clip
from src.api.processor import SingleVideoProcessor
from src.job_store import get_job_store

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
            use_supabase=False,
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
