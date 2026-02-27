import traceback
from pathlib import Path
from packages.core.queue.sqlite_queue import SQLiteJobQueue
from server.processor import SingleVideoProcessor
from server.workers.job_store import get_job_store
from typing import Dict, Any
from packages.core.db.engine import engine
from sqlmodel import Session
from packages.core.db.models import Episode

# Instancia global de la Job Queue para el backend de FastAPI
job_queue = SQLiteJobQueue()

async def processing_worker(job_id: str, payload: Dict[str, Any]):
    """
    Background worker function that runs the heavy video pipeline.
    It encapsulates the logic that used to block FastAPI's thread.
    """
    store = get_job_store()
    
    try:
        store.update_progress(job_id, 0, "Iniciando Worker de procesamiento...", status="processing")
        
        # Load variables
        video_path_str = payload.get("video_path")
        settings_dict = payload.get("settings", {})
        transcription_config = payload.get("transcription_config", {})
        auth_token = payload.get("auth_token")
        episode_id = payload.get("episode_id")
        
        file_path = Path(video_path_str)
        
        # Initialize processor
        # Output will be in data/jobs/{job_id}/clips
        processor = SingleVideoProcessor(
            output_dir=file_path.parent,
            min_duration=settings_dict.get("min_duration", 30),
            max_duration=settings_dict.get("max_duration", 90),
            min_score=settings_dict.get("min_score", 70),
            use_supabase=(transcription_config.get("source_type") == "supabase_custom"),
            auth_token=auth_token,
            transcription_config=transcription_config
        )
        
        import asyncio
        
        # Run processing IN A SEPARATE THREAD to prevent blocking the FastAPI event loop
        def run_processing():
            return processor.process_single(file_path, job_id=job_id)
            
        clips_count = await asyncio.to_thread(run_processing)
        
        # Sync to Local Database
        with Session(engine) as session:
            episode = session.get(Episode, episode_id)
            if episode:
                episode.status = "completed"
                episode.progress_percent = 100
                session.add(episode)
                session.commit()
                
        # Legacy store sync (for UI compatibility)
        store.complete_job(job_id, clips_count)
        
    except Exception as e:
        traceback.print_exc()
        # Fail the job in local DB
        episode_id = payload.get("episode_id")
        if episode_id:
            with Session(engine) as session:
                episode = session.get(Episode, episode_id)
                if episode:
                    episode.status = "failed"
                    episode.error_message = str(e)
                    session.add(episode)
                    session.commit()
        # Legacy store fail
        store.fail_job(job_id, str(e))

# Register worker to listen for Queue jobs
job_queue.register_worker(processing_worker)
