"""
Tests for the brief endpoints (T5): GET /brief, POST /brief/message, POST /brief/approve.

The LLM (BriefAgent) and the background render are patched; store + _brief_dir are
monkeypatched so no real DB / podcast drive is touched.
"""
import json
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from server.app import app
from server.middleware.auth import require_auth
import server.routes.clips as clips
from packages.clips.curation.brief_builder import build_session, save_session
from packages.clips.curation.brief_models import BriefAction

FIX = Path(__file__).parent / "fixtures" / "brief"


@pytest.fixture
def client():
    app.dependency_overrides[require_auth] = lambda: types.SimpleNamespace(id="local")
    yield TestClient(app)
    app.dependency_overrides.pop(require_auth, None)


@pytest.fixture
def brief_dir(tmp_path):
    d = tmp_path / "EP001"
    d.mkdir()
    (d / "curation.json").write_text((FIX / "curation.json").read_text())
    (d / "critic_decisions.json").write_text((FIX / "critic_decisions.json").read_text())
    session = build_session(d, "EP001", min_score=70)
    session.job_id = "job1"
    save_session(d, session)
    return d


def _wire(monkeypatch, brief_dir, status="awaiting_brief"):
    job = types.SimpleNamespace(job_id="job1", episode_id="EP001", status=status)
    fake_store = MagicMock()
    fake_store.get_job.return_value = job
    monkeypatch.setattr(clips, "store", fake_store)
    monkeypatch.setattr(clips, "_brief_dir", lambda job_id, episode_id=None: brief_dir)
    return fake_store


# ── GET /brief ───────────────────────────────────────────────────────────────

def test_get_brief_returns_candidates_and_counts(client, brief_dir, monkeypatch):
    _wire(monkeypatch, brief_dir)
    r = client.get("/api/jobs/job1/brief")
    assert r.status_code == 200
    body = r.json()
    assert body["episode_id"] == "EP001"
    assert len(body["candidates"]) == 5  # 3 curation + 2 critic-rejected
    assert body["counts"]["selected"] == 2  # scores 85 and 70 are above threshold
    assert body["counts"]["total"] == 5


def test_get_brief_409_when_not_awaiting(client, brief_dir, monkeypatch):
    _wire(monkeypatch, brief_dir, status="processing")
    r = client.get("/api/jobs/job1/brief")
    assert r.status_code == 409


def test_get_brief_404_when_no_job(client, brief_dir, monkeypatch):
    fake_store = MagicMock()
    fake_store.get_job.return_value = None
    monkeypatch.setattr(clips, "store", fake_store)
    r = client.get("/api/jobs/job1/brief")
    assert r.status_code == 404


# ── POST /brief/message ──────────────────────────────────────────────────────

def test_post_message_applies_action_and_persists(client, brief_dir, monkeypatch):
    _wire(monkeypatch, brief_dir)
    # Patch the agent to deterministically return a drop of candidate #1
    fake_agent = MagicMock()
    fake_agent.interpret.return_value = [BriefAction(type="drop", targets=[1])]
    monkeypatch.setattr(clips, "BriefAgent", lambda *a, **k: fake_agent)

    r = client.post("/api/jobs/job1/brief/message", json={"message": "quita el #1"})
    assert r.status_code == 200
    body = r.json()
    assert "change_summary" in body and "reply" in body
    c1 = next(c for c in body["candidates"] if c["id"] == 1)
    assert c1["selected"] is False
    # persisted
    saved = json.loads((brief_dir / "brief_session.json").read_text())
    assert any(m["role"] == "user" for m in saved["messages"])


def test_post_message_empty_400(client, brief_dir, monkeypatch):
    _wire(monkeypatch, brief_dir)
    r = client.post("/api/jobs/job1/brief/message", json={"message": "   "})
    assert r.status_code == 400


def test_post_message_llm_failure_502_session_intact(client, brief_dir, monkeypatch):
    _wire(monkeypatch, brief_dir)
    fake_agent = MagicMock()
    fake_agent.interpret.side_effect = RuntimeError("LLM down")
    monkeypatch.setattr(clips, "BriefAgent", lambda *a, **k: fake_agent)

    r = client.post("/api/jobs/job1/brief/message", json={"message": "haz algo"})
    assert r.status_code == 502
    # session not corrupted: still 5 candidates, no messages appended
    saved = json.loads((brief_dir / "brief_session.json").read_text())
    assert len(saved["candidates"]) == 5
    assert saved["messages"] == []


# ── POST /brief/approve ──────────────────────────────────────────────────────

def test_approve_resumes_render_and_records_learning(client, brief_dir, monkeypatch):
    fake_store = _wire(monkeypatch, brief_dir)
    render_spy = MagicMock()
    monkeypatch.setattr(clips, "_render_approved", render_spy)

    # select candidates 1, 2 (approved) and 4 (a rescued critic-reject)
    r = client.post("/api/jobs/job1/brief/approve", json={"selected_ids": [1, 2, 4]})
    assert r.status_code == 202
    assert r.json()["approved_count"] == 3
    render_spy.assert_called_once()
    # learning: the rescued critic-reject (#4) recorded as a 'disagree' with the Critic
    verdicts = [c.kwargs.get("user_verdict") for c in fake_store.save_critic_feedback.call_args_list]
    assert "disagree" in verdicts
    # session marked approved
    saved = json.loads((brief_dir / "brief_session.json").read_text())
    assert saved["status"] == "approved"


def test_approve_zero_selected_returns_400(client, brief_dir, monkeypatch):
    _wire(monkeypatch, brief_dir)
    monkeypatch.setattr(clips, "_render_approved", MagicMock())
    r = client.post("/api/jobs/job1/brief/approve", json={"selected_ids": []})
    assert r.status_code == 400
    assert "NO_CLIPS_SELECTED" in r.text
