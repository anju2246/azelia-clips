"""
Brief builder - constructs and persists brief sessions from curation artifacts.
STUB - Implementation pending.
"""
from pathlib import Path
from typing import Optional
from packages.clips.curation.brief_models import BriefSession


def build_session(job_dir: Path, episode_id: str, min_score: float = 70) -> BriefSession:
    """
    Build a brief session from curation artifacts.

    Loads:
    - curation.json (approved clips with virality scores)
    - critic_decisions.json (rejected clips)

    Returns a BriefSession with merged candidates.
    """
    raise NotImplementedError("build_session not implemented")


def save_session(job_dir: Path, session: BriefSession) -> None:
    """
    Save a brief session to <job_dir>/brief_session.json.
    """
    raise NotImplementedError("save_session not implemented")


def load_session(job_dir: Path) -> Optional[BriefSession]:
    """
    Load a brief session from <job_dir>/brief_session.json.
    Returns None if file doesn't exist.
    """
    raise NotImplementedError("load_session not implemented")
