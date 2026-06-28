"""
Deterministic applier for brief actions (T2).

The LLM only PROPOSES BriefActions; this module applies them with validation.
No LLM and no network here: `find_new` / `recurate_focus` receive their heavy
dependencies (finder, ranker) through `BriefContext`, so the whole module is
unit-testable with fakes.
"""
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

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
    # words_provider(window_start, window_end) -> list[(word, start, end)] for trim_to_text
    words_provider: Optional[Callable[[float, float], list]] = None


def _tokens(text: str) -> List[str]:
    """Lowercased alphanumeric tokens (accents kept, punctuation dropped)."""
    return re.findall(r"\w+", (text or "").lower(), re.UNICODE)


def match_text_span(
    words: List[Tuple[str, float, float]], keep_text: str
) -> Optional[Tuple[float, float]]:
    """Resolve a quoted passage to a (start, end) time span over timed words.

    `words` is a list of (word, start, end); matching is punctuation/case
    insensitive. Anchors on the first/last few query tokens so small transcript
    differences in the middle don't break the match. Returns None if unfound.
    """
    norm: List[Tuple[str, float, float]] = []
    for tok, s, e in words:
        t = _tokens(tok)
        if t:
            norm.append((t[0], float(s), float(e)))
    q = _tokens(keep_text)
    if not q or not norm:
        return None
    wt = [n[0] for n in norm]
    n = len(norm)
    k = min(5, len(q))
    head, tail = q[:k], q[-k:]

    start_i = next((i for i in range(0, n - k + 1) if wt[i:i + k] == head), None)
    if start_i is None:
        start_i = next((i for i in range(n) if wt[i] == q[0]), None)
    end_j = next((j for j in range(n, k - 1, -1) if wt[j - k:j] == tail), None)
    if end_j is None:
        end_j = next((j for j in range(n, 0, -1) if wt[j - 1] == q[-1]), None)

    if start_i is None or end_j is None or end_j <= start_i:
        return None
    return (norm[start_i][1], norm[end_j - 1][2])


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
    new_text = _text_in_window(ctx, start, end)
    if new_text:
        c.transcript = new_text
    return ChangeResult(ok=True, change_summary=f"Ajusté #{c.id} a {start:.0f}s–{end:.0f}s.")


def _text_in_window(ctx, start: float, end: float) -> Optional[str]:
    """Rebuild readable transcript from the timed words inside [start, end]."""
    if ctx.words_provider is None:
        return None
    words = ctx.words_provider(start, end) or []
    toks = [str(w).strip() for (w, s, e) in words if e > start and s < end and str(w).strip()]
    text = " ".join(toks).strip()
    return text or None


def _trim_to_text(session, action, ctx) -> ChangeResult:
    if action.id is None:
        raise BriefActionError("trim_to_text requires an id")
    text = (action.keep_text or "").strip()
    if not text:
        raise BriefActionError("trim_to_text requires keep_text")
    (c,) = _require_ids(session, [action.id])
    if ctx.words_provider is None:
        raise BriefActionError("trim_to_text needs a transcript in context")
    # Search only inside the clip's current window so a phrase repeated elsewhere
    # in the episode can't pull the cut out of this clip.
    words = ctx.words_provider(c.start_time, c.end_time) or []
    span = match_text_span(words, text)
    if span is None:
        return ChangeResult(
            ok=True,
            change_summary=f"No ubiqué ese fragmento dentro de #{c.id}; pégalo tal cual aparece en el transcript.",
        )
    start, end = span
    if end <= start:
        return ChangeResult(ok=True, change_summary=f"El recorte de #{c.id} quedó vacío; revisa el texto.")
    c.start_time, c.end_time = start, end
    c.selected = True  # trimming a clip means you want to keep it
    new_text = _text_in_window(ctx, start, end)
    if new_text:
        c.transcript = new_text  # so the card shows exactly what survived the cut
    return ChangeResult(
        ok=True,
        change_summary=f"Recorté #{c.id} a {start:.0f}s–{end:.0f}s (solo el fragmento que pediste).",
    )


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
    "trim_to_text": _trim_to_text,
    "find_new": _find_new,
    "noop": _noop,
}
