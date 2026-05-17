"""Simple in-memory async job queue backed by JobStore for persistence.

MVP-simple: single worker, FIFO, asyncio.Queue. Restart-safety comes from
JobStore — pending jobs at startup are re-enqueued from disk.
"""

import asyncio
from typing import Any, Callable, Coroutine, Dict, Optional

from packages.core.queue.base import BaseJobQueue
from server.workers.job_store import get_job_store


class SQLiteJobQueue(BaseJobQueue):
    """Asyncio-based job queue. Uses JobStore for persistence."""

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._processor: Optional[Callable[[str, Dict[str, Any]], Coroutine]] = None

    async def enqueue(self, job_id: str, payload: Dict[str, Any]) -> str:
        """Add a job to the queue. JobStore must already have the job created."""
        await self._queue.put((job_id, payload))
        return job_id

    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        store = get_job_store()
        job = store.get_job(job_id)
        if not job:
            return None
        return {
            "job_id": job_id,
            "status": job.status,
            "progress_percent": job.progress,
            "error_message": job.error,
        }

    async def update_job_progress(self, job_id: str, progress: int, status: str, message: str = ""):
        get_job_store().update_progress(job_id, progress, message, status=status)

    async def mark_job_failed(self, job_id: str, error_message: str):
        get_job_store().fail_job(job_id, error_message)

    def register_worker(self, task_func: Callable[[str, Dict[str, Any]], Coroutine]):
        self._processor = task_func

    async def start_workers(self, num_workers: int = 1):
        self._shutdown.clear()

        async def worker_loop():
            while not self._shutdown.is_set():
                try:
                    job_id, payload = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if self._processor is None:
                    continue
                try:
                    await self._processor(job_id, payload)
                except Exception as e:  # noqa: BLE001
                    await self.mark_job_failed(job_id, str(e))

        self._worker_task = asyncio.create_task(worker_loop())

    async def stop_workers(self):
        self._shutdown.set()
        if self._worker_task:
            try:
                await asyncio.wait_for(self._worker_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._worker_task.cancel()
