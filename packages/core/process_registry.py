"""Per-job subprocess registry for instant pause/cancel.

The pipeline spawns ffmpeg/ffprobe subprocesses during clip rendering. Without
tracking them, /pause and /cancel could only set a flag that the pipeline
checks between clips — meaning a single clip render in flight (~30-60 s) had to
finish before the pipeline noticed. With this registry, /pause and /cancel
SIGTERM every running subprocess for the job immediately; the pipeline's
per-clip try/except absorbs the resulting CalledProcessError and the next
iteration's abort check returns cleanly.

Usage:
    # Worker thread, at the top of process_episode:
    with active_job(job_id):
        ...heavy work that spawns subprocesses via run_ffmpeg or
           subprocess.Popen wrapped with register/unregister...

    # /pause and /cancel endpoints:
    kill_job_subprocesses(job_id)

Subprocesses spawned without an active_job context (e.g. from the CLI) are
not registered and behave like before.
"""

from __future__ import annotations

import subprocess
import threading
import time
from contextlib import contextmanager
from typing import Dict, Set

_registry: Dict[str, Set[subprocess.Popen]] = {}
_active_job = threading.local()
_lock = threading.Lock()


def get_active_job() -> str | None:
    return getattr(_active_job, "job_id", None)


def set_active_job(job_id: str | None) -> None:
    """Mark the current thread as belonging to job_id (or clear with None).

    Subprocesses spawned via `register(proc)` after this call (in the same
    thread) will be killable through `kill_job_subprocesses(job_id)`.
    Prefer the `active_job(job_id)` context manager when possible; this
    direct setter exists for long functions where wrapping the body in a
    `with` block would be awkward.
    """
    _active_job.job_id = job_id


@contextmanager
def active_job(job_id: str | None):
    """Mark the current thread as belonging to job_id while inside the block."""
    previous = get_active_job()
    set_active_job(job_id)
    try:
        yield
    finally:
        set_active_job(previous)


def register(proc: subprocess.Popen) -> None:
    """Register a subprocess against the active job. No-op outside a job."""
    job_id = get_active_job()
    if not job_id:
        return
    with _lock:
        _registry.setdefault(job_id, set()).add(proc)


def unregister(proc: subprocess.Popen) -> None:
    """Remove a finished subprocess from the registry."""
    job_id = get_active_job()
    if not job_id:
        return
    with _lock:
        bucket = _registry.get(job_id)
        if bucket is not None:
            bucket.discard(proc)
            if not bucket:
                _registry.pop(job_id, None)


def kill_job_subprocesses(job_id: str, grace_seconds: float = 0.5) -> int:
    """Kill every subprocess registered to a job.

    Sends SIGTERM, waits `grace_seconds` for clean exit, then SIGKILL the
    survivors. Returns the count of processes that were alive at call time.
    """
    with _lock:
        procs = list(_registry.get(job_id, set()))
    if not procs:
        return 0
    killed = 0
    for p in procs:
        try:
            if p.poll() is None:
                p.terminate()
                killed += 1
        except Exception:
            pass
    if killed:
        time.sleep(grace_seconds)
        for p in procs:
            try:
                if p.poll() is None:
                    p.kill()
            except Exception:
                pass
    with _lock:
        _registry.pop(job_id, None)
    return killed


def run_tracked(
    cmd: list[str],
    *,
    timeout: int | None = None,
    capture_output: bool = True,
    text: bool = True,
    check: bool = False,
) -> subprocess.CompletedProcess:
    """Drop-in replacement for subprocess.run() that registers the process so
    /pause and /cancel can kill it instantly.

    When the registry kills the process, `.communicate()` returns with a
    non-zero return code; if `check=True` we raise CalledProcessError so the
    pipeline's per-clip try/except can absorb it.
    """
    stdout = subprocess.PIPE if capture_output else None
    stderr = subprocess.PIPE if capture_output else None
    proc = subprocess.Popen(cmd, stdout=stdout, stderr=stderr, text=text)
    register(proc)
    try:
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise
    finally:
        unregister(proc)
    result = subprocess.CompletedProcess(cmd, proc.returncode, out, err)
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, cmd, out, err
        )
    return result
