"""
Tests for the deterministic brief action applier (T2).

No real LLM: find_new / recurate_focus dependencies are injected as fakes via
BriefContext. These tests pin the acceptance criteria and FAIL until apply()
is implemented.
"""
import pytest

from packages.clips.curation.brief_models import (
    BriefAction,
    BriefCandidate,
    BriefSession,
)
from packages.clips.curation.brief_actions import (
    apply,
    BriefContext,
    BriefActionError,
    match_text_span,
)


def _candidate(id, score, selected=True, critic_approved=True, above=True, origin="curation"):
    return BriefCandidate(
        id=id,
        start_time=float(id * 100),
        end_time=float(id * 100 + 40),
        title=f"Clip {id}",
        summary=f"Summary {id}",
        reasoning="",
        score=float(score),
        critic_approved=critic_approved,
        above_threshold=above,
        selected=selected,
        origin=origin,
    )


@pytest.fixture
def session():
    return BriefSession(
        job_id="job_1",
        episode_id="EP001",
        status="open",
        candidates=[
            _candidate(1, 85, selected=True),
            _candidate(2, 70, selected=True),
            _candidate(3, 55, selected=False, critic_approved=False, above=False, origin="rescued"),
        ],
        messages=[],
        created_at="2026-06-08T00:00:00",
        updated_at="2026-06-08T00:00:00",
    )


@pytest.fixture
def ctx():
    return BriefContext(episode_duration=3600.0)


def _by_id(session, id):
    return next(c for c in session.candidates if c.id == id)


# ── drop / rescue ────────────────────────────────────────────────────────────

def test_drop_marks_unselected(session, ctx):
    res = apply(session, BriefAction(type="drop", targets=[1]), ctx)
    assert res.ok is True
    assert _by_id(session, 1).selected is False
    assert _by_id(session, 2).selected is True


def test_rescue_below_threshold(session, ctx):
    # #3 is critic-rejected, below threshold, not selected → rescue selects it
    res = apply(session, BriefAction(type="rescue", targets=[3]), ctx)
    assert res.ok is True
    assert _by_id(session, 3).selected is True


def test_drop_invalid_id_raises(session, ctx):
    with pytest.raises(BriefActionError):
        apply(session, BriefAction(type="drop", targets=[999]), ctx)


# ── reorder ──────────────────────────────────────────────────────────────────

def test_reorder_by_score(session, ctx):
    # shuffle then reorder by score desc
    session.candidates = [_by_id(session, 2), _by_id(session, 3), _by_id(session, 1)]
    apply(session, BriefAction(type="reorder", by="score"), ctx)
    assert [c.score for c in session.candidates] == [85, 70, 55]


def test_reorder_explicit_order(session, ctx):
    apply(session, BriefAction(type="reorder", order=[3, 1, 2]), ctx)
    assert [c.id for c in session.candidates] == [3, 1, 2]


def test_reorder_invalid_id_raises(session, ctx):
    with pytest.raises(BriefActionError):
        apply(session, BriefAction(type="reorder", order=[3, 1, 99]), ctx)


# ── adjust_times ─────────────────────────────────────────────────────────────

def test_adjust_times_valid(session, ctx):
    apply(session, BriefAction(type="adjust_times", id=1, start_time=110.0, end_time=150.0), ctx)
    c = _by_id(session, 1)
    assert c.start_time == 110.0 and c.end_time == 150.0


def test_adjust_times_out_of_range_raises(session, ctx):
    # end beyond episode_duration
    with pytest.raises(BriefActionError):
        apply(session, BriefAction(type="adjust_times", id=1, start_time=100.0, end_time=9999.0), ctx)


def test_adjust_times_start_after_end_raises(session, ctx):
    with pytest.raises(BriefActionError):
        apply(session, BriefAction(type="adjust_times", id=1, start_time=200.0, end_time=150.0), ctx)


# ── find_new (injected finder, no LLM) ───────────────────────────────────────

def test_find_new_appends_found_candidate(session, ctx):
    ctx.finder = lambda ws, we, hint: [
        {"start_time": 2410.0, "end_time": 2450.0, "title": "Dog anecdote",
         "summary": "...", "reasoning": "found in window", "score": 74.0}
    ]
    before = len(session.candidates)
    res = apply(session, BriefAction(type="find_new", window_start=2400.0, window_end=2460.0), ctx)
    assert res.ok is True
    assert len(session.candidates) == before + 1
    found = [c for c in session.candidates if c.origin == "found"]
    assert len(found) == 1
    assert found[0].title == "Dog anecdote"
    assert found[0].selected is False  # user must rescue it explicitly


def test_find_new_invalid_window_is_noop(session, ctx):
    ctx.finder = lambda ws, we, hint: []
    before = len(session.candidates)
    # window_end <= window_start → no scan, ok with no mutation
    res = apply(session, BriefAction(type="find_new", window_start=500.0, window_end=400.0), ctx)
    assert res.ok is True
    assert len(session.candidates) == before


# ── noop ─────────────────────────────────────────────────────────────────────

def test_noop_keeps_selection(session, ctx):
    selected_before = [c.selected for c in session.candidates]
    res = apply(session, BriefAction(type="noop", reason="¿de qué minuto aprox?"), ctx)
    assert res.ok is True
    assert [c.selected for c in session.candidates] == selected_before
    assert "minuto" in res.change_summary


# ── trim_to_text (clip-scoped recorte por texto citado) ──────────────────────

def _words(pairs):
    """pairs: list of (word, start, end) tuples."""
    return [(w, float(s), float(e)) for (w, s, e) in pairs]


def test_trim_to_text_sets_window_from_quote(session):
    words = _words([
        ("relleno", 100, 101), ("antes", 101, 102),
        ("esto", 102, 103), ("es", 103, 104), ("la", 104, 105),
        ("parte", 105, 106), ("buena", 106, 107),
        ("y", 107, 108), ("relleno", 108, 109), ("final", 109, 110),
    ])
    ctx = BriefContext(episode_duration=3600.0, words_provider=lambda s, e: words)
    res = apply(session, BriefAction(type="trim_to_text", id=1,
                                     keep_text="esto es la parte buena"), ctx)
    assert res.ok is True
    c1 = next(c for c in session.candidates if c.id == 1)
    assert c1.start_time == 102.0 and c1.end_time == 107.0
    assert c1.selected is True  # recortar implica conservar el clip
    # the card transcript is rebuilt to show only what survived the cut
    assert c1.transcript == "esto es la parte buena"
    assert "relleno" not in c1.transcript


def test_trim_to_text_matches_despite_punctuation_and_case(session):
    words = _words([
        ("Esto,", 102, 103), ("ES", 103, 104), ("la", 104, 105),
        ("Parte.", 105, 106), ("buena", 106, 107),
    ])
    ctx = BriefContext(episode_duration=3600.0, words_provider=lambda s, e: words)
    res = apply(session, BriefAction(type="trim_to_text", id=1,
                                     keep_text="esto es la parte buena"), ctx)
    c1 = next(c for c in session.candidates if c.id == 1)
    assert c1.start_time == 102.0 and c1.end_time == 107.0


def test_trim_to_text_unfound_is_graceful_no_mutation(session):
    ctx = BriefContext(episode_duration=3600.0, words_provider=lambda s, e: _words([
        ("hola", 100, 101), ("mundo", 101, 102)]))
    before = (session.candidates[0].start_time, session.candidates[0].end_time)
    res = apply(session, BriefAction(type="trim_to_text", id=1,
                                     keep_text="fragmento que no existe"), ctx)
    assert res.ok is True
    assert (session.candidates[0].start_time, session.candidates[0].end_time) == before


def test_trim_to_text_requires_id_and_keep_text(session, ctx):
    with pytest.raises(BriefActionError):
        apply(session, BriefAction(type="trim_to_text", keep_text="algo"), ctx)
    with pytest.raises(BriefActionError):
        apply(session, BriefAction(type="trim_to_text", id=1, keep_text="  "), ctx)


# ── match_text_span (T1: robust matcher + proximity bias) ────────────────────

def test_match_span_no_anchor_backcompat():
    """Without anchor_time, an exact quote resolves to the precise span (как antes)."""
    words = _words([
        ("esto", 102, 103), ("es", 103, 104), ("la", 104, 105),
        ("parte", 105, 106), ("buena", 106, 107),
    ])
    assert match_text_span(words, "esto es la parte buena") == (102.0, 107.0)


def test_match_span_fuzzy_tolerates_edge_differences():
    """Small transcription/paste differences at the edges still resolve the span."""
    words = _words([
        ("relleno", 100, 101),
        ("esto", 102, 103), ("es", 103, 104), ("la", 104, 105),
        ("parte", 105, 106), ("buena", 106, 107),
        ("relleno", 108, 109),
    ])
    # head "fue" vs "es", tail "bueno" vs "buena" — two edge differences
    span = match_text_span(words, "esto fue la parte bueno")
    assert span is not None
    s, e = span
    assert 101.5 <= s <= 102.5 and 106.5 <= e <= 107.5


def test_match_span_proximity_picks_nearest_occurrence():
    """A phrase repeated in the episode resolves to the occurrence nearest anchor_time."""
    words = _words([
        # occurrence #1 around 100s
        ("la", 100, 101), ("parte", 101, 102), ("buena", 102, 103),
        ("bla", 103, 104), ("bla", 104, 105),
        # occurrence #2 around 500s
        ("la", 500, 501), ("parte", 501, 502), ("buena", 502, 503),
    ])
    near = match_text_span(words, "la parte buena", anchor_time=490.0)
    assert near == (500.0, 503.0)
    near2 = match_text_span(words, "la parte buena", anchor_time=99.0)
    assert near2 == (100.0, 103.0)


def test_match_span_absent_returns_none():
    words = _words([("hola", 100, 101), ("mundo", 101, 102)])
    assert match_text_span(words, "fragmento que no existe en absoluto") is None


def test_match_span_caps_oversized_query_without_exact_anchor():
    """A pathologically long fragment with no exact anchor skips the fuzzy sweep
    (perf guard) and returns None instead of scanning O(n·lq²)."""
    words = _words([(f"w{i}", float(i), float(i) + 1) for i in range(50)])
    huge = " ".join(f"x{i}" for i in range(500))  # 500 tokens, none present
    assert match_text_span(words, huge) is None


def test_trim_clamps_span_to_episode_duration(session):
    """A resolved end beyond episode_duration is clamped (spec F3.4)."""
    ctx = BriefContext(
        episode_duration=150.0,
        words_provider=lambda s, e: _words([("alpha", 148, 152)]),  # ends past 150
    )
    res = apply(session, BriefAction(type="trim_to_text", id=1, keep_text="alpha"), ctx)
    c1 = next(c for c in session.candidates if c.id == 1)
    assert res.ok is True
    assert c1.end_time == 150.0  # clamped to episode duration


# ── trim_to_text whole-episode search (T2) ───────────────────────────────────

def test_trim_resolves_fragment_outside_current_window(session):
    """The fragment lives outside the clip's current [start,end]; trim moves the clip to it."""
    # clip #1 is at 100–140; the quoted fragment is at ~200s (outside the window).
    all_words = _words([
        ("antes", 100, 101), ("del", 101, 102), ("clip", 102, 103),
        ("la", 200, 201), ("parte", 201, 202), ("que", 202, 203),
        ("quiero", 203, 204), ("conservar", 204, 205),
    ])

    def window_provider(s, e):
        # honra la ventana pedida: el código viejo pide [100,140] y NO ve los 200s
        return [(w, ws, we) for (w, ws, we) in all_words if we >= s and ws <= e]

    ctx = BriefContext(episode_duration=3600.0, words_provider=window_provider)
    res = apply(session, BriefAction(type="trim_to_text", id=1,
                                     keep_text="la parte que quiero conservar"), ctx)
    assert res.ok is True
    c1 = next(c for c in session.candidates if c.id == 1)
    assert c1.start_time == 200.0 and c1.end_time == 205.0
    assert c1.selected is True


def test_trim_unfound_message_is_clear(session):
    ctx = BriefContext(episode_duration=3600.0, words_provider=lambda s, e: _words([
        ("hola", 100, 101), ("mundo", 101, 102)]))
    before = (session.candidates[0].start_time, session.candidates[0].end_time)
    res = apply(session, BriefAction(type="trim_to_text", id=1,
                                     keep_text="esto no aparece en ningun lado del episodio"), ctx)
    assert res.ok is True
    assert (session.candidates[0].start_time, session.candidates[0].end_time) == before
    assert "no encontr" in res.change_summary.lower()
