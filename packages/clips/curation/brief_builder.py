"""
Brief builder — constructs and persists brief sessions from curation artifacts.

Reads the JSON the curation pipeline already writes (`curation.json` and
`critic_decisions.json`) and assembles a `BriefSession` for the human-in-the-loop
review gate. No LLM, no network — pure filesystem + scoring.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from packages.clips.curation.brief_models import BriefCandidate, BriefSession
from packages.clips.curation.models import ViralityScore

SESSION_FILENAME = "brief_session.json"


def _score_of(clip: dict) -> float:
    """Total virality score (sum of the 10 dimensions).

    `ViralityScore.total` is a computed property, so it is NOT present in the
    serialized `curation.json`; we reconstruct it from the stored dimensions.
    """
    vs = clip.get("virality_score") or {}
    return float(ViralityScore(**vs).total)


def _dedup_key(start: float, end: float) -> tuple:
    return (round(float(start), 2), round(float(end), 2))


def _clip_texter(job_dir: Path):
    """Return a fn (start, end) -> transcript text for that window, or '' if no
    transcript.json is available. Lets the brief card show the clip's words."""
    tpath = job_dir / "transcript.json"
    if not tpath.exists():
        return lambda start, end: ""
    try:
        from packages.clips.transcription.transcriber import Transcript
        transcript = Transcript.load(tpath)
        segments = transcript.segments
    except Exception:
        return lambda start, end: ""

    def text_for(start: float, end: float) -> str:
        parts = [
            getattr(s, "text", "") or ""
            for s in segments
            if getattr(s, "end", 0) >= start and getattr(s, "start", 0) <= end
        ]
        return " ".join(p.strip() for p in parts if p).strip()

    return text_for


def build_session(
    job_dir: Path,
    episode_id: str,
    min_score: float = 70,
    *,
    hook_enabled: bool = False,
    hook_duration_s: float = 0.0,
) -> BriefSession:
    """Build a brief session from the curation artifacts in ``job_dir``.

    - ``curation.json`` → critic-approved candidates (with virality scores).
      ``above_threshold`` / ``selected`` follow ``score >= min_score``.
    - ``critic_decisions.json`` → critic-REJECTED candidates (``approved == False``),
      surfaced as rescuable (``selected=False``, ``origin="rescued"``), deduped
      against the curation set by (start, end).

    Candidates are sorted by score descending and assigned stable 1-based ids.
    """
    job_dir = Path(job_dir)
    candidates: list[BriefCandidate] = []
    seen: set[tuple] = set()
    clip_text = _clip_texter(job_dir)

    curation_path = job_dir / "curation.json"
    if curation_path.exists():
        clips = json.loads(curation_path.read_text())
        for clip in clips:
            score = _score_of(clip)
            above = score >= min_score
            key = _dedup_key(clip["start_time"], clip["end_time"])
            seen.add(key)
            candidates.append(
                BriefCandidate(
                    id=0,  # assigned after sort
                    start_time=float(clip["start_time"]),
                    end_time=float(clip["end_time"]),
                    title=clip.get("title", ""),
                    hook_text=clip.get("title", ""),  # default = title; user may override
                    summary=clip.get("summary", ""),
                    reasoning=clip.get("reasoning", "") or "",
                    score=score,
                    critic_approved=True,
                    above_threshold=above,
                    selected=above,
                    origin="curation",
                    transcript=clip_text(clip["start_time"], clip["end_time"]),
                )
            )

    critic_path = job_dir / "critic_decisions.json"
    if critic_path.exists():
        decisions = json.loads(critic_path.read_text())
        for d in decisions:
            if d.get("approved", False):
                continue  # already represented in curation.json
            key = _dedup_key(d["start_time"], d["end_time"])
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                BriefCandidate(
                    id=0,
                    start_time=float(d["start_time"]),
                    end_time=float(d["end_time"]),
                    title=d.get("title", ""),
                    hook_text=d.get("title", ""),  # default = title; user may override
                    summary=d.get("summary", ""),
                    reasoning=d.get("reasoning", "") or "",
                    score=0.0,
                    critic_approved=False,
                    above_threshold=False,
                    selected=False,
                    origin="rescued",
                    transcript=clip_text(d["start_time"], d["end_time"]),
                )
            )

    candidates.sort(key=lambda c: c.score, reverse=True)
    for i, c in enumerate(candidates, start=1):
        c.id = i

    now = datetime.utcnow().isoformat()
    return BriefSession(
        job_id=job_dir.name,
        episode_id=episode_id,
        status="open",
        candidates=candidates,
        messages=[],
        created_at=now,
        updated_at=now,
        hook_enabled=hook_enabled,
        hook_duration_s=hook_duration_s,
    )


def save_session(job_dir: Path, session: BriefSession) -> None:
    """Persist a brief session to ``<job_dir>/brief_session.json``."""
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    session.updated_at = datetime.utcnow().isoformat()
    path = job_dir / SESSION_FILENAME
    path.write_text(json.dumps(session.to_dict(), indent=2, ensure_ascii=False))


def load_session(job_dir: Path) -> Optional[BriefSession]:
    """Load a brief session, or ``None`` if it does not exist."""
    path = Path(job_dir) / SESSION_FILENAME
    if not path.exists():
        return None
    return BriefSession.from_dict(json.loads(path.read_text()))
