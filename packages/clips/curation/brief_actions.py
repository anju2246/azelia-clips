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


_FUZZY_MIN_RATIO = 0.6  # difflib similarity floor for the fuzzy fallback


def match_text_span(
    words: List[Tuple[str, float, float]],
    keep_text: str,
    anchor_time: Optional[float] = None,
) -> Optional[Tuple[float, float]]:
    """Resolve a quoted passage to a (start, end) time span over timed words.

    `words` is a list of (word, start, end); matching is punctuation/case
    insensitive. The matcher is robust in two ways:

    1. **Exact anchors** on the first/last few query tokens, but it gathers ALL
       occurrences (not just the first), so a phrase repeated elsewhere in the
       episode still produces every candidate span.
    2. **Fuzzy fallback** (``difflib``) when no exact anchor pair survives, so a
       pasted fragment with small differences at the edges or middle still
       resolves.

    When ``anchor_time`` is given, candidates of equal match quality are broken
    by proximity to it — i.e. the occurrence nearest the focused clip wins. When
    it is ``None`` the earliest candidate wins (stable, back-compatible).
    Returns ``None`` if nothing matches.
    """
    # Expand each timed word into its alphanumeric tokens, all sharing the
    # word's (start, end). For word-level transcripts this is one token each;
    # for the segment-level fallback it lets a whole sentence still be matched.
    norm: List[Tuple[str, float, float]] = []
    for tok, s, e in words:
        for piece in _tokens(tok):
            norm.append((piece, float(s), float(e)))
    q = _tokens(keep_text)
    if not q or not norm:
        return None
    wt = [t for t, _, _ in norm]
    n = len(norm)
    lq = len(q)
    k = min(5, lq)

    # (quality, edge_bonus, length_penalty, start_i, end_j[exclusive]).
    candidates: List[Tuple[float, int, int, int, int]] = []

    # ── exact-anchor candidates ──────────────────────────────────────────────
    head, tail = q[:k], q[-k:]
    head_starts = [i for i in range(0, n - k + 1) if wt[i:i + k] == head]
    if not head_starts:
        head_starts = [i for i in range(n) if wt[i] == q[0]]
    tail_ends = [j for j in range(k, n + 1) if wt[j - k:j] == tail]
    if not tail_ends:
        tail_ends = [j for j in range(1, n + 1) if wt[j - 1] == q[-1]]

    lo_len = max(1, int(0.5 * lq))
    hi_len = int(2.0 * lq) + 5
    for i in head_starts:
        for j in tail_ends:
            if j > i and lo_len <= (j - i) <= hi_len:
                # exact anchors (quality 2.0) beat any fuzzy match
                candidates.append((2.0, 2, 0, i, j))

    # ── fuzzy fallback (only if no exact-anchor pair survived) ───────────────
    if not candidates:
        for size in range(max(1, lq - 2), lq + 3):
            if size > n:
                continue
            for i in range(0, n - size + 1):
                window = wt[i:i + size]
                sm = difflib.SequenceMatcher(None, window, q)
                # coverage = fraction of QUERY tokens matched (don't reward
                # dropping query words just because a shorter window scores
                # higher on difflib's length-sensitive ratio).
                matched = sum(b.size for b in sm.get_matching_blocks())
                coverage = matched / lq
                if coverage < _FUZZY_MIN_RATIO:
                    continue
                # prefer windows whose edges align with the query edges, so a
                # match isn't padded with unrelated filler at the start/end.
                edge_bonus = (window[0] == q[0]) + (window[-1] == q[-1])
                candidates.append((coverage, edge_bonus, abs(size - lq), i, i + size))

    if not candidates:
        return None

    def _rank(c: Tuple[float, int, int, int, int]):
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
