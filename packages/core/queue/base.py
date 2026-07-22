from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine, Dict, Optional


class BaseJobQueue(ABC):
    """
    Abstract Interface for the Hybrid Job Queue system.
    Ensures that both SQLiteJobQueue (Local/Community) and RedisJobQueue (Pro/Cloud)
    adhere to the same contract for enqueuing and processing heavy video tasks.
    """

    @abstractmethod
    async def enqueue(self, job_id: str, payload: Dict[str, Any]) -> str:
        """Adds a new job to the queue and returns its ID."""
        pass

    @abstractmethod
    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves the current status and progress of a job."""
        pass

    @abstractmethod
    async def update_job_progress(self, job_id: str, progress: int, status: str, message: str = ""):
        """Updates the state of a job (used by the worker)."""
        pass

    @abstractmethod
    async def mark_job_failed(self, job_id: str, error_message: str):
        """Marks a job as failed and saves the error message."""
        pass

    @abstractmethod
    def register_worker(self, task_func: Callable[[str, Dict[str, Any]], Coroutine]):
        """
        Registers the main processing function that the queue will invoke
        when a job is popped from the queue.
        """
        pass

    @abstractmethod
    async def start_workers(self, num_workers: int = 1):
        """Starts the background workers to process the queue."""
        pass

    @abstractmethod
    async def stop_workers(self):
        """Gracefully shuts down the background workers."""
        pass
