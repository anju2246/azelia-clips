"""
Deterministic applier for brief actions (T2).

The LLM only PROPOSES BriefActions; this module applies them with validation.
No LLM and no network here: `find_new` / `recurate_focus` receive their heavy
dependencies (finder, ranker) through `BriefContext`, so the whole module is
unit-testable with fakes.
"""
import difflib
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


_FUZZY_MIN_RATIO = 0.6        # min fraction of query tokens a fuzzy window must cover
_ANCHOR_TOKENS = 5            # head/tail tokens used for exact anchoring
_MIN_LEN_FACTOR = 0.5         # exact-span length must be ≥ this × query length
_MAX_LEN_FACTOR = 2.0         # …and ≤ this × query length …
_MAX_LEN_PADDING = 5          # …plus this slack (tokens)
_FUZZY_WIN_TOLERANCE = 2      # fuzzy window sizes scanned: len(q) ± this
_EXACT_QUALITY = 2.0          # quality score for exact anchors (beats any fuzzy)
_EXACT_EDGE_BONUS = 2         # exact anchors align both edges by construction
_MAX_FUZZY_QUERY_TOKENS = 120  # beyond this, require exact anchors (DoS guard)
_FUZZY_RADIUS_S = 180.0       # fuzzy sweep stays within ±this of anchor_time
_MAX_KEEP_TEXT_CHARS = 10_000  # cap pasted-fragment size before tokenizing


def _exact_anchor_candidates(wt, n, q, lq):
    """All exact-anchor (quality, edge_bonus, len_penalty, i, j) spans for `q`.

    Gathers EVERY head/tail occurrence (not just the first) so a phrase repeated
    in the episode still yields each candidate span for proximity ranking later.
    """
    k = min(_ANCHOR_TOKENS, lq)
    head, tail = q[:k], q[-k:]
    head_starts = [i for i in range(0, n - k + 1) if wt[i:i + k] == head]
    if not head_starts:
        head_starts = [i for i in range(n) if wt[i] == q[0]]
    tail_ends = [j for j in range(k, n + 1) if wt[j - k:j] == tail]
    if not tail_ends:
        tail_ends = [j for j in range(1, n + 1) if wt[j - 1] == q[-1]]

    lo_len = max(1, int(_MIN_LEN_FACTOR * lq))
    hi_len = int(_MAX_LEN_FACTOR * lq) + _MAX_LEN_PADDING
    out = []
    for i in head_starts:
        for j in tail_ends:
            if j > i and lo_len <= (j - i) <= hi_len:
                out.append((_EXACT_QUALITY, _EXACT_EDGE_BONUS, 0, i, j))
    return out


def _fuzzy_candidates(norm, wt, n, q, lq, anchor_time):
    """Fuzzy (coverage, edge_bonus, len_penalty, i, j) spans via difflib.

    Bounded for performance: skipped for oversized queries, and (when an
    anchor_time is given) the sliding window only scans words within
    ``_FUZZY_RADIUS_S`` of the focused clip instead of the whole episode.
    """
    if lq > _MAX_FUZZY_QUERY_TOKENS:
        return []
    lo, hi = 0, n
    if anchor_time is not None:  # restrict the O(n·lq²) sweep to the clip's zone
        lo = next((idx for idx in range(n)
                   if norm[idx][2] >= anchor_time - _FUZZY_RADIUS_S), n)
        hi = next((idx for idx in range(n - 1, -1, -1)
                   if norm[idx][1] <= anchor_time + _FUZZY_RADIUS_S), -1) + 1
    out = []
    for size in range(max(1, lq - _FUZZY_WIN_TOLERANCE), lq + _FUZZY_WIN_TOLERANCE + 1):
        if size > n:
            continue
        for i in range(lo, hi - size + 1):
            window = wt[i:i + size]
            sm = difflib.SequenceMatcher(None, window, q)
            # coverage = fraction of QUERY tokens matched; don't reward dropping
            # query words just because a shorter window scores higher on
            # difflib's length-sensitive ratio().
            coverage = sum(b.size for b in sm.get_matching_blocks()) / lq
            if coverage < _FUZZY_MIN_RATIO:
                continue
            # prefer windows whose edges align with the query edges, so a match
            # isn't padded with unrelated filler at the start/end.
            edge_bonus = (window[0] == q[0]) + (window[-1] == q[-1])
            out.append((coverage, edge_bonus, abs(size - lq), i, i + size))
    return out


def match_text_span(
    words: List[Tuple[str, float, float]],
    keep_text: str,
    anchor_time: Optional[float] = None,
) -> Optional[Tuple[float, float]]:
    """Resolve a quoted passage to a (start, end) time span over timed words.

    `words` is a list of (word, start, end); matching is punctuation/case
    insensitive. Robust in two ways: exact head/tail anchors (gathering every
    occurrence), and a bounded ``difflib`` fuzzy fallback when no exact anchor
    survives — so a pasted fragment with small edge/middle differences still
    resolves. When ``anchor_time`` is given, equal-quality candidates are broken
    by proximity to it (the occurrence nearest the focused clip wins); when
    ``None`` the earliest wins (stable, back-compatible). ``None`` if unfound.
    """
    # Expand each timed word into its alphanumeric tokens, all sharing the
    # word's (start, end). For word-level transcripts this is one token each;
    # for the segment-level fallback it lets a whole sentence still be matched.
    norm: List[Tuple[str, float, float]] = []
    for tok, s, e in words:
        for piece in _tokens(tok):
            norm.append((piece, float(s), float(e)))
    q = _tokens((keep_text or "")[:_MAX_KEEP_TEXT_CHARS])
    if not q or not norm:
        return None
    wt = [t for t, _, _ in norm]
    n, lq = len(norm), len(q)

    candidates = _exact_anchor_candidates(wt, n, q, lq)
    if not candidates:
        candidates = _fuzzy_candidates(norm, wt, n, q, lq, anchor_time)
    if not candidates:
        return None

    def _rank(c):
        quality, edge_bonus, length_penalty, i, _j = c
        prox = abs(norm[i][1] - anchor_time) if anchor_time is not None else 0.0
        # best coverage, best edge alignment, length closest to the query, then
        # nearest to the focused clip, then earliest occurrence.
        return (-quality, -edge_bonus, length_penalty, prox, i)

    _q, _eb, _lp, bi, bj = min(candidates, key=_rank)
    return (norm[bi][1], norm[bj - 1][2])


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
    # Search the WHOLE episode (not just the clip's current window) so a pasted
    # fragment that falls outside the current [start,end] still resolves and can
    # move/extend the clip. A phrase repeated elsewhere is disambiguated by
    # proximity to the clip in focus (anchor_time=c.start_time).
    words = ctx.words_provider(0.0, ctx.episode_duration) or []
    span = match_text_span(words, text, anchor_time=c.start_time)
    if span is None:
        return ChangeResult(
            ok=True,
            change_summary=(
                f"No encontré ese fragmento en el episodio para #{c.id}; "
                f"pégalo un poco más largo o tal cual aparece en el transcript."
            ),
        )
    start, end = span
    # Clamp to valid episode bounds (defensive: match_text_span derives times
    # from words already inside the episode, but a malformed provider shouldn't
    # push a clip out of range). spec F3.4.
    if start < 0:
        start = 0.0
    if ctx.episode_duration and end > ctx.episode_duration:
        end = ctx.episode_duration
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
