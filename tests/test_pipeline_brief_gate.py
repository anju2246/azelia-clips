"""
Tests for the brief gate + render refactor in BatchProcessor (T4).

We avoid the heavy BatchProcessor.__init__ (which builds a transcription driver
and requires the podcast dir) by constructing via __new__ and setting only the
attributes the tested methods touch. No transcription, no LLM, no rendering.
"""
import json
import types
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from packages.clips.pipeline import BatchProcessor, EpisodeConfig

FIX = Path(__file__).parent / "fixtures" / "brief"


def _proc(review_brief=None, min_score=70, user_id="local"):
    p = BatchProcessor.__new__(BatchProcessor)
    p.min_score = min_score
    p.user_id = user_id
    p.review_brief = review_brief
    p.abort_event = None
    p.target_clip_id = None
    return p


def _episode(tmp_path, num=1):
    folder = tmp_path / f"EP{num:03d}"
    folder.mkdir()
    (folder / "clips").mkdir()
    return EpisodeConfig(
        episode_number=num, episode_folder=folder, video_path=tmp_path / "v.mp4"
    )


def _fake_clip(score):
    return types.SimpleNamespace(
        virality_score=types.SimpleNamespace(total=score),
        start_time=0.0,
        end_time=40.0,
    )


# ── toggle ───────────────────────────────────────────────────────────────────

def test_brief_gate_enabled_default_true():
    p = _proc(review_brief=None)
    with patch("packages.core.config.settings.review_brief_before_processing", True):
        assert p._brief_gate_enabled() is True


def test_brief_gate_disabled_by_setting():
    p = _proc(review_brief=None)
    with patch("packages.core.config.settings.review_brief_before_processing", False):
        assert p._brief_gate_enabled() is False


def test_brief_gate_override_wins_over_setting():
    p_off = _proc(review_brief=False)
    with patch("packages.core.config.settings.review_brief_before_processing", True):
        assert p_off._brief_gate_enabled() is False
    p_on = _proc(review_brief=True)
    with patch("packages.core.config.settings.review_brief_before_processing", False):
        assert p_on._brief_gate_enabled() is True


# ── dispatch ─────────────────────────────────────────────────────────────────

def test_dispatch_gate_on_opens_brief_no_render(tmp_path):
    p = _proc()
    ep = _episode(tmp_path)
    p._brief_gate_open = MagicMock(return_value=True)
    p._open_brief_gate = MagicMock(return_value=0)
    p.process_clips = MagicMock(return_value=5)

    out = p._dispatch_after_curation(ep, [_fake_clip(85)], "job1", 0)

    p._open_brief_gate.assert_called_once()
    p.process_clips.assert_not_called()
    assert out == 0


def test_dispatch_gate_off_calls_process_clips_unchanged(tmp_path):
    p = _proc()
    ep = _episode(tmp_path)
    valid = [_fake_clip(85), _fake_clip(72)]
    p._brief_gate_open = MagicMock(return_value=False)
    p._open_brief_gate = MagicMock()
    p.process_clips = MagicMock(return_value=2)

    out = p._dispatch_after_curation(ep, valid, "job1", 0)

    p.process_clips.assert_called_once_with(ep, valid, job_id="job1", start_from_clip=0)
    p._open_brief_gate.assert_not_called()
    assert out == 2


# ── gate-open predicate ──────────────────────────────────────────────────────

def test_brief_gate_open_false_on_resume(tmp_path):
    p = _proc()
    ep = _episode(tmp_path)
    p._brief_gate_enabled = MagicMock(return_value=True)
    assert p._brief_gate_open("job1", 2, ep) is False  # start_from_clip > 0


def test_brief_gate_open_false_without_job(tmp_path):
    p = _proc()
    ep = _episode(tmp_path)
    p._brief_gate_enabled = MagicMock(return_value=True)
    assert p._brief_gate_open(None, 0, ep) is False


def test_brief_gate_open_false_when_already_approved(tmp_path):
    p = _proc()
    ep = _episode(tmp_path)
    p._brief_gate_enabled = MagicMock(return_value=True)
    session = {
        "job_id": "job1", "episode_id": "EP001", "status": "approved",
        "candidates": [], "messages": [],
        "created_at": "t", "updated_at": "t",
    }
    (ep.episode_folder / "brief_session.json").write_text(json.dumps(session))
    assert p._brief_gate_open("job1", 0, ep) is False


# ── open the gate ────────────────────────────────────────────────────────────

def test_open_brief_gate_creates_session_and_sets_status(tmp_path):
    p = _proc()
    ep = _episode(tmp_path)
    (ep.episode_folder / "curation.json").write_text((FIX / "curation.json").read_text())
    (ep.episode_folder / "critic_decisions.json").write_text(
        (FIX / "critic_decisions.json").read_text()
    )
    fake_store = MagicMock()
    with patch("server.workers.job_store.get_job_store", return_value=fake_store):
        out = p._open_brief_gate(ep, "job1")

    assert out == 0
    assert (ep.episode_folder / "brief_session.json").exists()
    # status flipped to awaiting_brief
    assert fake_store.update_progress.called
    _, kwargs = fake_store.update_progress.call_args
    assert kwargs.get("status") == "awaiting_brief"


# ── render loop operates only on the given list ──────────────────────────────

def test_process_clips_renders_only_given_list(tmp_path):
    p = _proc()
    ep = _episode(tmp_path)
    calls = []
    p._render_one_clip = lambda *a, **k: (calls.append(1), 1)[1]
    clips = [_fake_clip(85), _fake_clip(60)]

    out = p.process_clips(ep, clips, job_id=None, start_from_clip=0)

    assert len(calls) == 2, "should render exactly the 2 given clips"
    assert out == 2
