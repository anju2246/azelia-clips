"""Job status persistence using SQLite.

Solves the problem of losing processing state when the server restarts.
Jobs can be paused, resumed, and recovered after crashes.
"""

import json
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

# Default database path
DB_PATH = Path(__file__).parent.parent / "data" / "jobs.db"


@dataclass
class JobStatus:
    """Processing job status with pause/resume support."""
    job_id: str
    episode_id: str
    status: str  # pending, processing, paused, completed, error, cancelled
    progress: int  # 0-100
    message: str
    clips_generated: int
    created_at: str
    updated_at: str
    error: Optional[str] = None
    # Pause/resume fields
    last_clip_index: int = 0  # Last successfully processed clip (0-indexed)
    total_clips: int = 0  # Total clips to process
    config_json: Optional[str] = None  # Serialized processing config for resume
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @property
    def can_resume(self) -> bool:
        """Check if job can be resumed."""
        return self.status == "paused" and self.last_clip_index < self.total_clips


class JobStore:
    """SQLite-backed job status storage with pause/resume support.
    
    Usage:
        store = JobStore()
        store.create_job("job123", "EP097", total_clips=5, config={...})
        store.update_clip_progress("job123", clip_index=2)
        store.pause_job("job123")
        # Later...
        job = store.get_paused_jobs()[0]
        store.resume_job(job.job_id)
    """
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Create tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    episode_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    progress INTEGER DEFAULT 0,
                    message TEXT DEFAULT '',
                    clips_generated INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error TEXT,
                    last_clip_index INTEGER DEFAULT 0,
                    total_clips INTEGER DEFAULT 0,
                    config_json TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_jobs_episode 
                ON jobs(episode_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_jobs_status 
                ON jobs(status)
            """)
            conn.commit()
            
            # Migration: Add new columns if they don't exist
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN last_clip_index INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # Column exists
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN total_clips INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN config_json TEXT")
            except sqlite3.OperationalError:
                pass
    
    def create_job(
        self, 
        job_id: str, 
        episode_id: str,
        total_clips: int = 0,
        config: dict = None,
    ) -> JobStatus:
        """Create a new job with optional resume config."""
        now = datetime.utcnow().isoformat()
        config_json = json.dumps(config) if config else None
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO jobs 
                (job_id, episode_id, status, progress, message, clips_generated, 
                 created_at, updated_at, last_clip_index, total_clips, config_json)
                VALUES (?, ?, 'pending', 0, 'Iniciando...', 0, ?, ?, 0, ?, ?)
            """, (job_id, episode_id, now, now, total_clips, config_json))
            conn.commit()
        
        return JobStatus(
            job_id=job_id,
            episode_id=episode_id,
            status="pending",
            progress=0,
            message="Iniciando...",
            clips_generated=0,
            created_at=now,
            updated_at=now,
            total_clips=total_clips,
            config_json=config_json,
        )
    
    def update_progress(
        self,
        job_id: str,
        progress: int,
        message: str,
        status: str = "processing",
    ):
        """Update job progress."""
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE jobs SET 
                    progress = ?,
                    message = ?,
                    status = ?,
                    updated_at = ?
                WHERE job_id = ?
            """, (progress, message, status, now, job_id))
            conn.commit()
    
    def update_clip_progress(
        self,
        job_id: str,
        clip_index: int,
        clips_generated: int,
        message: str = "",
    ):
        """Update progress after completing a clip (for resume support)."""
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            # Get total clips to calculate percentage
            row = conn.execute(
                "SELECT total_clips FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            total = row[0] if row else 1
            progress = int((clip_index + 1) / max(total, 1) * 100)
            
            conn.execute("""
                UPDATE jobs SET 
                    last_clip_index = ?,
                    clips_generated = ?,
                    progress = ?,
                    message = ?,
                    updated_at = ?
                WHERE job_id = ?
            """, (clip_index, clips_generated, progress, message or f"Procesando clip {clip_index + 1}/{total}", now, job_id))
            conn.commit()
    
    def pause_job(self, job_id: str) -> bool:
        """Pause a running job. Returns True if successful."""
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            result = conn.execute("""
                UPDATE jobs SET 
                    status = 'paused',
                    message = '⏸️ Pausado - click Continuar para reanudar',
                    updated_at = ?
                WHERE job_id = ? AND status = 'processing'
            """, (now, job_id))
            conn.commit()
            return result.rowcount > 0
    
    def resume_job(self, job_id: str) -> bool:
        """Mark a paused job as ready to resume. Returns True if successful."""
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            result = conn.execute("""
                UPDATE jobs SET 
                    status = 'resuming',
                    message = '▶️ Reanudando...',
                    updated_at = ?
                WHERE job_id = ? AND status = 'paused'
            """, (now, job_id))
            conn.commit()
            return result.rowcount > 0
    
    def set_total_clips(self, job_id: str, total_clips: int):
        """Set total clips count (called after curation)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE jobs SET total_clips = ? WHERE job_id = ?",
                (total_clips, job_id)
            )
            conn.commit()
    
    def save_config(self, job_id: str, config: dict):
        """Save processing config for resume."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE jobs SET config_json = ? WHERE job_id = ?",
                (json.dumps(config), job_id)
            )
            conn.commit()
    
    def get_config(self, job_id: str) -> Optional[dict]:
        """Get saved config for resume."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT config_json FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row and row[0]:
                return json.loads(row[0])
            return None
    
    def complete_job(self, job_id: str, clips_generated: int, message: str = ""):
        """Mark job as completed."""
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE jobs SET 
                    status = 'completed',
                    progress = 100,
                    message = ?,
                    clips_generated = ?,
                    updated_at = ?
                WHERE job_id = ?
            """, (message or f"✓ {clips_generated} clips generados", clips_generated, now, job_id))
            conn.commit()
    
    def fail_job(self, job_id: str, error: str):
        """Mark job as failed."""
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE jobs SET 
                    status = 'error',
                    message = ?,
                    error = ?,
                    updated_at = ?
                WHERE job_id = ?
            """, (f"Error: {error[:100]}", error, now, job_id))
            conn.commit()
    
    def get_job(self, job_id: str) -> Optional[JobStatus]:
        """Get job by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            
            if not row:
                return None
            
            return JobStatus(**dict(row))
    
    def get_episode_jobs(self, episode_id: str) -> list[JobStatus]:
        """Get all jobs for an episode."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM jobs WHERE episode_id = ? ORDER BY created_at DESC",
                (episode_id,)
            ).fetchall()
            
            return [JobStatus(**dict(row)) for row in rows]

    def get_latest_jobs_per_episode(self) -> dict[str, JobStatus]:
        """Fetch the most recent job for each episode in one query."""
        query = """
            SELECT * FROM jobs 
            WHERE (episode_id, created_at) IN (
                SELECT episode_id, MAX(created_at)
                FROM jobs
                GROUP BY episode_id
            )
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(query).fetchall()
                return {row["episode_id"]: JobStatus(**dict(row)) for row in rows}
        except Exception:
            return {}
    
    def get_active_jobs(self) -> list[JobStatus]:
        """Get all processing jobs."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = 'processing' ORDER BY created_at"
            ).fetchall()
            
            return [JobStatus(**dict(row)) for row in rows]
    
    def get_paused_jobs(self) -> list[JobStatus]:
        """Get all paused jobs that can be resumed."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = 'paused' ORDER BY updated_at DESC"
            ).fetchall()
            
            return [JobStatus(**dict(row)) for row in rows]
    
    def get_resumable_jobs(self) -> list[JobStatus]:
        """Get jobs that are paused or resuming."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status IN ('paused', 'resuming') ORDER BY updated_at DESC"
            ).fetchall()
            
            return [JobStatus(**dict(row)) for row in rows]
    
    def cleanup_stale_jobs(self, max_age_hours: int = 24):
        """Mark old 'processing' jobs as failed (likely crashed)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            stale = conn.execute("""
                SELECT job_id FROM jobs 
                WHERE status = 'processing' 
                AND datetime(updated_at) < datetime('now', ?)
            """, (f"-{max_age_hours} hours",)).fetchall()
            
            for row in stale:
                self.fail_job(row["job_id"], "Job timed out (stale)")
            
            return len(stale)


# Singleton instance
_store: Optional[JobStore] = None


def get_job_store() -> JobStore:
    """Get or create the singleton JobStore instance."""
    global _store
    if _store is None:
        _store = JobStore()
    return _store


class TqdmJobProgress:
    """
    Context manager that wraps tqdm to report progress to JobStore.
    
    Usage:
        with TqdmJobProgress(job_id, "Transcribiendo...") as progress:
            # tqdm will automatically report to JobStore
            for item in tqdm(items):
                process(item)
    """
    
    def __init__(
        self, 
        job_id: str, 
        stage_name: str = "Processing",
        progress_offset: int = 0,
        progress_scale: float = 100,
    ):
        self.job_id = job_id
        self.stage_name = stage_name
        self.progress_offset = progress_offset  # Add to calculated progress
        self.progress_scale = progress_scale    # Scale (e.g., 30 = use 30% of progress bar)
        self._original_tqdm = None
        self._store = get_job_store()
    
    def __enter__(self):
        # Monkey-patch tqdm to report to JobStore
        import tqdm as tqdm_module
        self._original_tqdm = tqdm_module.tqdm
        
        job_id = self.job_id
        stage_name = self.stage_name
        offset = self.progress_offset
        scale = self.progress_scale
        store = self._store
        
        class JobProgressTqdm(self._original_tqdm):
            """Custom tqdm that reports to JobStore."""
            
            def __init__(this, *args, **kwargs):
                kwargs.setdefault('mininterval', 1.0)  # Don't update too often
                super().__init__(*args, **kwargs)
            
            def update(this, n=1):
                result = super().update(n)
                if this.total:
                    pct = (this.n / this.total) * scale
                    total_progress = min(100, int(offset + pct))
                    store.update_progress(
                        job_id,
                        total_progress,
                        f"{stage_name}: {this.n}/{this.total} ({int(pct)}%)",
                    )
                return result
        
        tqdm_module.tqdm = JobProgressTqdm
        return self
    
    def __exit__(self, *args):
        # Restore original tqdm
        import tqdm as tqdm_module
        if self._original_tqdm:
            tqdm_module.tqdm = self._original_tqdm


def job_progress_callback(job_id: str, stage: str, offset: int = 0, scale: float = 100):
    """
    Create a progress callback for Whisper transcription.
    
    Args:
        job_id: Job ID to update
        stage: Stage name (e.g., "Transcribiendo")
        offset: Progress offset (e.g., 10 means start at 10%)
        scale: Scale factor (e.g., 20 means use 20% of progress bar)
    
    Returns:
        Context manager that patches tqdm
    """
    return TqdmJobProgress(
        job_id, 
        stage_name=stage, 
        progress_offset=offset, 
        progress_scale=scale
    )
