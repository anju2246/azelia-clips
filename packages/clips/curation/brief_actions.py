"""
Deterministic applier for brief actions (T2).

The LLM only PROPOSES BriefActions; this module applies them with validation.
No LLM and no network here: `find_new` / `recurate_focus` receive their heavy
dependencies (finder, ranker) through `BriefContext`, so the whole module is
unit-testable with fakes.
"""
from dataclasses import dataclass
from typing import Callable, Optional

from packages.clips.curation.brief_models import (
    BriefAction,
    BriefCandidate,
    BriefSession,
    ChangeResult,
)


class BriefActionError(ValueError):
    """Raised when an action is invalid (bad ids, out-of-range times, ...)."""


@dataclass
class BriefContext:
    """Injected dependencies for actions that need transcript/agents."""
    episode_duration: float = 0.0
    # find_new(window_start, window_end, hint) -> list[dict] of candidate fields
    finder: Optional[Callable[[float, float, Optional[str]], list]] = None
    # recurate(candidates, focus) -> dict[id -> new_score]
    ranker: Optional[Callable[[list, str], dict]] = None


def _index_by_id(session: BriefSession) -> dict:
    return {c.id: c for c in session.candidates}


def _require_ids(session: BriefSession, ids) -> list:
    by_id = _index_by_id(session)
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise BriefActionError(f"Unknown candidate id(s): {missing}")
    return [by_id[i] for i in ids]


def _next_id(session: BriefSession) -> int:
    return max((c.id for c in session.candidates), default=0) + 1


def apply(session: BriefSession, action: BriefAction, ctx: BriefContext) -> ChangeResult:
    """Apply one action to `session` in place and return a ChangeResult."""
    t = action.type
    handler = _HANDLERS.get(t)
    if handler is None:
        raise BriefActionError(f"Unknown action type: {t!r}")
    return handler(session, action, ctx)


def _drop(session, action, ctx) -> ChangeResult:
    for c in _require_ids(session, action.targets):
        c.selected = False
    return ChangeResult(ok=True, change_summary=f"Descarté {action.targets}.")


def _rescue(session, action, ctx) -> ChangeResult:
    for c in _require_ids(session, action.targets):
        c.selected = True
    return ChangeResult(ok=True, change_summary=f"Reactivé {action.targets} → a procesar.")


def _reorder(session, action, ctx) -> ChangeResult:
    if action.order is not None:
        ordered = _require_ids(session, action.order)
        # any candidate not named keeps its relative order at the end
        named = set(action.order)
        rest = [c for c in session.candidates if c.id not in named]
        session.candidates = ordered + rest
        return ChangeResult(ok=True, change_summary=f"Reordené a {action.order}.")
    key = action.by or "score"
    if key == "score":
        session.candidates.sort(key=lambda c: c.score, reverse=True)
    else:
        # Unknown sort key → stable no-op order; report it rather than crash.
        return ChangeResult(ok=True, change_summary=f"No sé ordenar por '{key}'; dejé el orden igual.")
    return ChangeResult(ok=True, change_summary=f"Reordené por {key}.")


def _adjust_times(session, action, ctx) -> ChangeResult:
    if action.id is None:
        raise BriefActionError("adjust_times requires an id")
    (c,) = _require_ids(session, [action.id])
    start = action.start_time if action.start_time is not None else c.start_time
    end = action.end_time if action.end_time is not None else c.end_time
    if start < 0 or end <= start:
        raise BriefActionError(f"Invalid window: start={start}, end={end}")
    if ctx.episode_duration and end > ctx.episode_duration:
        raise BriefActionError(
            f"end={end} exceeds episode duration {ctx.episode_duration}"
        )
    c.start_time, c.end_time = start, end
    return ChangeResult(ok=True, change_summary=f"Ajusté #{c.id} a {start:.0f}s–{end:.0f}s.")


def _recurate_focus(session, action, ctx) -> ChangeResult:
    if ctx.ranker is None:
        raise BriefActionError("recurate_focus needs a ranker in context")
    new_scores = ctx.ranker(session.candidates, action.focus or "")
    for c in session.candidates:
        if c.id in new_scores:
            c.score = float(new_scores[c.id])
    session.candidates.sort(key=lambda c: c.score, reverse=True)
    return ChangeResult(ok=True, change_summary=f"Re-rankée por enfoque '{action.focus}'.")


def _find_new(session, action, ctx) -> ChangeResult:
    ws, we = action.window_start, action.window_end
    if ws is None or we is None or we <= ws:
        return ChangeResult(
            ok=True,
            change_summary="No identifiqué una ventana clara; ¿en qué minuto aprox busco?",
        )
    if ctx.finder is None:
        raise BriefActionError("find_new needs a finder in context")
    found = ctx.finder(ws, we, action.hint) or []
    added = 0
    for f in found:
        session.candidates.append(
            BriefCandidate(
                id=_next_id(session),
                start_time=float(f["start_time"]),
                end_time=float(f["end_time"]),
                title=f.get("title", ""),
                summary=f.get("summary", ""),
                reasoning=f.get("reasoning", "") or "",
                score=float(f.get("score", 0.0)),
                critic_approved=False,
                above_threshold=False,
                selected=False,  # user must rescue it explicitly
                origin="found",
            )
        )
        added += 1
    if not added:
        return ChangeResult(ok=True, change_summary=f"Escaneé {ws:.0f}s–{we:.0f}s, sin candidatos nuevos.")
    return ChangeResult(ok=True, change_summary=f"Encontré {added} candidato(s) en {ws:.0f}s–{we:.0f}s.")


def _noop(session, action, ctx) -> ChangeResult:
    return ChangeResult(ok=True, change_summary=action.reason or "Sin cambios.")


_HANDLERS = {
    "drop": _drop,
    "rescue": _rescue,
    "reorder": _reorder,
    "adjust_times": _adjust_times,
    "recurate_focus": _recurate_focus,
    "find_new": _find_new,
    "noop": _noop,
}
