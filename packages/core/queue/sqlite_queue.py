import asyncio
import json
from typing import Dict, Any, Optional, Callable, Coroutine
from datetime import datetime
from sqlmodel import Session, select

from packages.core.db.engine import engine
from packages.core.db.models import Episode
from packages.core.queue.base import BaseJobQueue

class SQLiteJobQueue(BaseJobQueue):
    """
    Local implementation of the Job Queue for the Community Tier.
    Uses SQLite (via SQLModel's Episode table) to persist and recover jobs.
    Uses asyncio background tasks to process them without blocking FastAPI.
    """
    
    def __init__(self):
        self._worker_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._processor_func: Optional[Callable[[str, Dict[str, Any]], Coroutine]] = None
        self._sleep_interval = 2.0  # seconds between polls

    async def enqueue(self, job_id: str, payload: Dict[str, Any]) -> str:
        """
        In SQLModel, we assume the Episode row was created by the FastAPI endpoint.
        This simply sets its status to 'pending' to be picked up by the worker.
        """
        with Session(engine) as session:
            # We assume payload contains 'episode_id' representing the primary key
            ep_id = payload.get("episode_id")
            if not ep_id:
                raise ValueError("Payload must contain 'episode_id'")
                
            statement = select(Episode).where(Episode.id == ep_id)
            episode = session.exec(statement).first()
            if not episode:
                raise ValueError(f"Episode with id {ep_id} not found")
                
            # Assign job_id so worker can track it
            episode.job_id = job_id
            episode.status = "pending"
            episode.progress_percent = 0
            session.add(episode)
            session.commit()
            
        return job_id

    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        with Session(engine) as session:
            statement = select(Episode).where(Episode.job_id == job_id)
            episode = session.exec(statement).first()
            if not episode:
                return None
            return {
                "job_id": job_id,
                "status": episode.status,
                "progress_percent": episode.progress_percent,
                "error_message": episode.error_message
            }

    async def update_job_progress(self, job_id: str, progress: int, status: str, message: str = ""):
        with Session(engine) as session:
            statement = select(Episode).where(Episode.job_id == job_id)
            episode = session.exec(statement).first()
            if episode:
                episode.progress_percent = progress
                # Do not overwrite 'completed' or 'failed' with generic 'processing' randomly
                if episode.status not in ["completed", "failed"]:
                    episode.status = status
                session.add(episode)
                session.commit()

    async def mark_job_failed(self, job_id: str, error_message: str):
        with Session(engine) as session:
            statement = select(Episode).where(Episode.job_id == job_id)
            episode = session.exec(statement).first()
            if episode:
                episode.status = "failed"
                episode.error_message = error_message
                session.add(episode)
                session.commit()

    def register_worker(self, task_func: Callable[[str, Dict[str, Any]], Coroutine]):
        """Registers the async function that actually runs the heavy pipeline."""
        self._processor_func = task_func

    async def start_workers(self, num_workers: int = 1):
        """Starts a background poller that grabs 'pending' jobs one by one."""
        self._shutdown_event.clear()
        
        async def poll_loop():
            while not self._shutdown_event.is_set():
                if self._processor_func is None:
                    await asyncio.sleep(self._sleep_interval)
                    continue
                    
                job_to_process = None
                with Session(engine) as session:
                    # Find ONE pending job
                    statement = select(Episode).where(Episode.status == "pending").limit(1)
                    pending_ep = session.exec(statement).first()
                    
                    if pending_ep:
                        # Lock it so other workers don't grab it (if we had multiple)
                        pending_ep.status = "processing"
                        session.add(pending_ep)
                        session.commit()
                        
                        job_to_process = {
                            "job_id": pending_ep.job_id,
                            "payload": {
                                "episode_id": pending_ep.id,
                                "video_path": pending_ep.video_path
                            }
                        }
                
                if job_to_process:
                    # Run the designated heavy processor function
                    # It is awaited so it blocks this specific worker coroutine
                    try:
                        await self._processor_func(
                            job_to_process["job_id"], 
                            job_to_process["payload"]
                        )
                        # The processor_func should internally call update_job_progress(..., "completed")
                    except Exception as e:
                        await self.mark_job_failed(job_to_process["job_id"], str(e))
                else:
                    # Sleep if no jobs
                    await asyncio.sleep(self._sleep_interval)
                    
        self._worker_task = asyncio.create_task(poll_loop())

    async def stop_workers(self):
        self._shutdown_event.set()
        if self._worker_task:
            await self._worker_task
