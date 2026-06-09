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
from packages.clips.curation.brief_actions import apply, BriefContext, BriefActionError


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
