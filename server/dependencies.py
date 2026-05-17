"""Background workers for the FastAPI server.

Local-first MVP: no remote DB sync, no telemetry, no Supabase.
Job state is tracked in `data/jobs.db` (SQLite) via JobStore.
"""

import asyncio
import traceback
from pathlib import Path
from typing import Any, Dict

from packages.core.queue.sqlite_queue import SQLiteJobQueue
from server.processor import SingleVideoProcessor
from server.workers.job_store import get_job_store

# Global job queue (singleton)
job_queue = SQLiteJobQueue()


async def processing_worker(job_id: str, payload: Dict[str, Any]):
    """Background worker that runs the heavy video pipeline."""
    store = get_job_store()

    try:
        store.update_progress(job_id, 0, "Starting processing worker…", status="processing")

        video_path_str = payload.get("video_path")
        settings_dict = payload.get("settings", {})
        transcription_config = payload.get("transcription_config", {})

        file_path = Path(video_path_str)

        processor = SingleVideoProcessor(
            output_dir=file_path.parent,
            min_duration=settings_dict.get("min_duration", 30),
            max_duration=settings_dict.get("max_duration", 90),
            min_score=settings_dict.get("min_score", 70),
            transcription_config=transcription_config,
        )

        def run_processing():
            return processor.process_single(file_path, job_id=job_id)

        clips_count = await asyncio.to_thread(run_processing)
        store.complete_job(job_id, clips_count)

    except Exception as e:  # noqa: BLE001 — top-level worker safety net
        traceback.print_exc()
        store.fail_job(job_id, str(e))


# Register worker to listen for queue jobs
job_queue.register_worker(processing_worker)
