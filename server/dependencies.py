"""Background workers for the FastAPI server.

Local-first MVP: no remote DB sync, no telemetry, no Supabase.
Job state is tracked in `data/jobs.db` (SQLite) via JobStore.
"""

import asyncio
import threading
import traceback
from pathlib import Path
from typing import Any, Dict

from packages.core.queue.sqlite_queue import SQLiteJobQueue
from server.processor import SingleVideoProcessor
from server.workers.job_store import get_job_store

# Global job queue (singleton)
job_queue = SQLiteJobQueue()

# Per-job abort events for graceful pause/cancel.
_abort_events: Dict[str, threading.Event] = {}
_abort_events_lock = threading.Lock()


def get_abort_event(job_id: str) -> threading.Event:
    """Get-or-create the abort event for a job. Pipeline checks it between clips."""
    with _abort_events_lock:
        if job_id not in _abort_events:
            _abort_events[job_id] = threading.Event()
        return _abort_events[job_id]


def clear_abort_event(job_id: str) -> None:
    """Remove the event after a job terminates (success/fail/cancel)."""
    with _abort_events_lock:
        _abort_events.pop(job_id, None)


async def processing_worker(job_id: str, payload: Dict[str, Any]):
    """Background worker that runs the heavy video pipeline."""
    store = get_job_store()

    try:
        store.update_progress(job_id, 0, "Starting processing worker…", status="processing")

        video_path_str = payload.get("video_path")
        settings_dict = payload.get("settings", {})
        transcription_config = payload.get("transcription_config", {})
        start_from_clip = int(payload.get("start_from_clip", 0) or 0)

        file_path = Path(video_path_str)

        processor = SingleVideoProcessor(
            output_dir=file_path.parent,
            min_duration=settings_dict.get("min_duration", 30),
            max_duration=settings_dict.get("max_duration", 90),
            min_score=settings_dict.get("min_score", 70),
            transcription_config=transcription_config,
            template_id=settings_dict.get("template_id"),
        )

        def run_processing():
            return processor.process_single(
                file_path, job_id=job_id, start_from_clip=start_from_clip
            )

        clips_count = await asyncio.to_thread(run_processing)

        # Don't clobber paused/cancelled/awaiting_* state with 'completed'
        # when the pipeline returned early (pause/cancel signal, or brief gate).
        current = store.get_job(job_id)
        if current and current.status in ("paused", "cancelled", "awaiting_brief", "awaiting_framing"):
            store.update_progress(
                job_id,
                current.progress,
                f"⏸️ {current.status} ({clips_count} clips so far)",
                status=current.status,
            )
        else:
            store.complete_job(job_id, clips_count)

    except Exception as e:  # noqa: BLE001 — top-level worker safety net
        traceback.print_exc()
        store.fail_job(job_id, str(e))
    finally:
        try:
            from server.dependencies import clear_abort_event
            clear_abort_event(job_id)
        except Exception:
            pass


# Register worker to listen for queue jobs
job_queue.register_worker(processing_worker)
