"""Shared guard: is any job actively rendering right now?

Used to block operations that would orphan a running job — self-update and
profile switching (both restart the server). Returns the offending job IDs so
the caller can tell the user exactly what's running.
"""

from __future__ import annotations


def has_active_jobs() -> tuple[bool, list[str]]:
    """(active, ids). 'Active' = a job in `processing` state (a live render)."""
    try:
        from server.workers.job_store import get_job_store

        store = get_job_store()
        ids = [j.job_id for j in store.get_active_jobs()]
        return (len(ids) > 0, ids)
    except Exception:
        return (False, [])
