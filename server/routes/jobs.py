import shutil
import uuid
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException, Form, Header, Body, Depends, WebSocket, WebSocketDisconnect
import asyncio
from fastapi.responses import FileResponse
from server.models import (
    JobResponse, JobStatus, ProcessRequest, Clip,
    SettingsResponse, UpdateSettingsRequest, EpisodeResponse
)
from server.models import (
    JobResponse, JobStatus, ProcessRequest, Clip,
    SettingsResponse, UpdateSettingsRequest, EpisodeResponse
)
from server.dependencies import job_queue
from server.workers.job_store import get_job_store
from packages.core.config import settings
from server.middleware.auth import require_auth
from sqlmodel import Session
from packages.core.db.engine import engine
from packages.core.db.models import Episode
from typing import List
import json
from packages.clips.vision.face_tracker import FaceTracker

router = APIRouter()
store = get_job_store()

# Base directory for job data
DATA_DIR = Path("data/jobs")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Removing legacy run_processing_task function. 
# The processing logic is now registered in the Queue worker inside server/dependencies.py


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
    
    # Initialize Job in Store (Legacy for UI compatibility)
    store.create_job(
        job_id=job_id,
        episode_id=file.filename,
        config=settings.dict()
    )
    
    # NEW: Create Episode in SQLite
    with Session(engine) as session:
        episode = Episode(
            user_id=user["sub"] if user else "anonymous",
            title=file.filename,
            video_path=str(file_path),
            status="queued"
        )
        session.add(episode)
        session.commit()
        session.refresh(episode)
    
    # Enqueue locally using the Hybrid Queue interface
    # Resolvendo "RuntimeWarning: coroutine was never awaited" enrutándolo a call via create_task 
    # ya que enqueue de SQLiteJobQueue no asume asyncio dentro de este endpoint sincrónico/mezclado
    payload = {
        "episode_id": episode.id,
        "video_path": str(file_path),
        "settings": settings.dict(),
        "transcription_config": transcription_config,
        "auth_token": auth_token
    }
    
    # Usamos enqueue como un background task si el router es async, pero router es async
    import asyncio
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

# --- Local Mode Endpoints ---

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
    from server.sources.supabase_transcripts import upload_transcript
    from packages.clips.transcription.transcriber import Transcript
    
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

@router.post("/connections/{platform}")
async def connect_platform_endpoint(platform: str, authorization: str = Header(None)):
    """Connect a social platform."""
    from server.services.analytics import AnalyticsSync
    
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
        
    token = authorization.replace("Bearer ", "").strip()
    analytics = AnalyticsSync(auth_token=token)
    
    if not analytics.Enabled:
        raise HTTPException(status_code=500, detail="Analytics service not enabled (check Supabase config)")
        
    # Mock metadata for now, or accept from body if needed
    success = analytics.connect_platform(platform)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to connect platform")
        
    return {"status": "connected", "platform": platform}

@router.post("/analytics/upload-csv")
async def upload_analytics_csv(
    file: UploadFile = File(...),
    authorization: str = Header(None)
):
    """Upload and process YouTube Analytics CSV."""
    from server.sources.youtube_analytics import YouTubeAnalyticsParser
    
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
        
    token = authorization.replace("Bearer ", "").strip()
    
    if not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="Invalid file type. Only CSV supported.")
        
    try:
        content = await file.read()
        parser = YouTubeAnalyticsParser(auth_token=token)
        
        if not parser.enabled:
             raise HTTPException(status_code=500, detail="Analytics service not enabled")
             
        stats = parser.parse_and_sync(content)
        return stats
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analytics/fetch-youtube")
async def fetch_youtube_analytics(
    provider_token: str = Form(...),
    authorization: str = Header(None)
):
    """
    Fetch real-time analytics from YouTube Data API using the user's Google Access Token.
    Updates 'user_connections' and matches videos to 'clips_metadata'.
    """
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from server.services.analytics import AnalyticsSync
    
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    
    # 1. Setup Supabase Client (to save results)
    token = authorization.replace("Bearer ", "").strip()
    analytics = AnalyticsSync(auth_token=token)
    if not analytics.Enabled:
         raise HTTPException(status_code=500, detail="Analytics service not enabled")

    try:
        # 2. Initialize YouTube Client
        creds = Credentials(token=provider_token)
        youtube = build('youtube', 'v3', credentials=creds)
        
        # 3. Get Channel Stats
        channel_resp = youtube.channels().list(mine=True, part='snippet,statistics').execute()
        if not channel_resp.get('items'):
             raise HTTPException(status_code=404, detail="No YouTube channel found for this user")
             
        channel = channel_resp['items'][0]
        channel_id = channel['id']
        channel_title = channel['snippet']['title']
        
        # 4. Update Connection Status
        analytics.connect_platform("youtube", metadata={
            "channel_id": channel_id,
            "title": channel_title,
            "thumbnails": channel['snippet']['thumbnails'],
            "statistics": channel['statistics'] # viewCount, subscriberCount, videoCount
        })
        
        # 5. Get Recent Videos (for analytics matching)
        # Note: 'myRating' is not analytics. We need 'uploads' playlist to get public stats.
        uploads_playlist_id = channel['contentDetails']['relatedPlaylists']['uploads']
        
        videos_resp = youtube.playlistItems().list(
            playlistId=uploads_playlist_id,
            part='snippet',
            maxResults=50 # Grab last 50 videos
        ).execute()
        
        video_ids = [item['snippet']['resourceId']['videoId'] for item in videos_resp.get('items', [])]
        
        # Get stats for these videos
        stats_resp = youtube.videos().list(
            id=','.join(video_ids),
            part='snippet,statistics'
        ).execute()
        
        matched_count = 0
        
        # 6. Sync Video Stats to Clips
        # Re-using the logic from YouTubeAnalyticsParser would be clean, but data shape is different.
        # Let's do a direct update here for now.
        
        for vid in stats_resp.get('items', []):
            title = vid['snippet']['title']
            stats = vid['statistics']
            
            # Map YouTube API stats to our schema
            metrics = {
                "platform": "youtube",
                "youtube_id": vid['id'],
                "views": int(stats.get('viewCount', 0)),
                "likes": int(stats.get('likeCount', 0)),
                "comments": int(stats.get('commentCount', 0)),
                "last_updated": "now()"
            }
            
            # Update Clip in Supabase
            # Matches by title
            res = analytics.client.table("clips_metadata")\
                .update({"performance_metrics": metrics})\
                .eq("video_title", title)\
                .execute()
                
            if res.data:
                matched_count += 1
                
        return {
            "status": "success", 
            "channel": channel_title, 
            "videos_scanned": len(video_ids),
            "clips_matched": matched_count
        }

    except Exception as e:
        print(f"YouTube Fetch Error: {e}")
        # Return error but don't crash 500 if it's just an API quota/permission issue
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/auth/youtube/authorize")
async def authorize_youtube(
    redirect_uri: str,
    authorization: str = Header(None)
):
    """
    Start OAuth flow for YouTube connection (resource-only).
    Returns the Google authorization URL.
    """
    from google_auth_oauthlib.flow import Flow
    
    # We need the client secrets. For now, assume they are in client_secret.json or env vars.
    # Ideally, load from Env Vars: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
    # Or Supabase config? Since user configured Supabase Auth, they likely have these.
    # Simplification: We ask user to put client_secret.json in root for this custom flow, 
    # OR we use the same credentials if we can extract them.
    # Let's assume a client_secrets.json file exists for now, or fallback to manual input.
    
    # Actually, for a local app, we can use the installed app flow.
    # But since we are a web app (FastAPI + React), we use Web Server flow.
    
    try:
        # Check if client_secrets.json exists
        import os
        secrets_file = "client_secrets.json"
        if not os.path.exists(secrets_file):
            raise HTTPException(status_code=500, detail="Missing client_secrets.json in server root. Please download from Google Cloud Console.")

        flow = Flow.from_client_secrets_file(
            secrets_file,
            scopes=['https://www.googleapis.com/auth/youtube.readonly'],
            redirect_uri=redirect_uri
        )
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            prompt='consent',
            include_granted_scopes='true'
        )
        
        return {"url": authorization_url}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auth/youtube/callback")
async def callback_youtube(
    code: str = Body(..., embed=True),
    redirect_uri: str = Body(..., embed=True),
    authorization: str = Header(None)
):
    """
    Exchange authorization code for tokens and link to current user.
    """
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    from server.services.analytics import AnalyticsSync
    
    if not authorization:
         raise HTTPException(status_code=401, detail="User must be logged in to link account")
         
    token = authorization.replace("Bearer ", "").strip()
    analytics = AnalyticsSync(auth_token=token)
    
    try:
        secrets_file = "client_secrets.json"
        flow = Flow.from_client_secrets_file(
            secrets_file,
            scopes=['https://www.googleapis.com/auth/youtube.readonly'],
            redirect_uri=redirect_uri
        )
        
        flow.fetch_token(code=code)
        creds = flow.credentials
        
        # Now we have credentials unrelated to the main user session!
        # Use them to get channel info
        youtube = build('youtube', 'v3', credentials=creds)
        
        channel_resp = youtube.channels().list(mine=True, part='snippet,statistics').execute()
        if not channel_resp.get('items'):
             raise HTTPException(status_code=404, detail="No YouTube channel found")
             
        channel = channel_resp['items'][0]
        
        # Save connection
        analytics.connect_platform("youtube", metadata={
            "channel_id": channel['id'],
            "title": channel['snippet']['title'],
            "thumbnails": channel['snippet']['thumbnails'],
            "statistics": channel['statistics'],
            "refresh_token": creds.refresh_token, # CRITICAL: Store this to refresh later
            "access_token": creds.token
        })
        
        # Initial Sync
        # ... (re-use sync logic or trigger background job)
        
        return {"status": "success", "channel": channel['snippet']['title']}
        
    except Exception as e:
        print(f"OAuth Callback Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.websocket("/ws/jobs/{job_id}")
async def websocket_job_status(websocket: WebSocket, job_id: str):
    """
    Tethers a WebSocket connection to stream real-time progress.
    Avoids heavy polling from the UI.
    """
    await websocket.accept()
    
    try:
        while True:
            job = store.get_job(job_id)
            if not job:
                await websocket.send_json({"error": "Job not found"})
                await asyncio.sleep(2)
                continue
                
            await websocket.send_json({
                "job_id": job.job_id,
                "status": job.status,
                "progress": job.progress,
                "message": job.message
            })
            
            # Close connection automatically if terminal state is reached
            if job.status in ["completed", "failed", "error", "cancelled"]:
                break
                
            # Stream every 1.5s
            await asyncio.sleep(1.5)
            
    except WebSocketDisconnect:
        # Client gracefully closed or lost connection
        pass
    except Exception as e:
        print(f"WebSocket Error on {job_id}: {e}")
        
    try:
        await websocket.close()
    except Exception:
        pass
