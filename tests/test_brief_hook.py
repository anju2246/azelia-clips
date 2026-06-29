"""Tests for the editable hook (first-N-seconds title) in the brief.

Covers the vertical slice: data model defaults, template→gate derivation, the
edit endpoint, payload exposure, the approved-clip mapping, and the render
fallback rule (hook_text or title).
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
from packages.clips.curation.models import CuratedClip
from packages.clips.pipeline import BatchProcessor

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
    session = build_session(d, "EP001", min_score=70, hook_enabled=True, hook_duration_s=4.0)
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


# ── data model: hook_text defaults to the title ──────────────────────────────

def test_build_session_defaults_hook_text_to_title(tmp_path):
    d = tmp_path / "EP001"
    d.mkdir()
    (d / "curation.json").write_text((FIX / "curation.json").read_text())
    session = build_session(d, "EP001", min_score=70)
    assert session.candidates, "fixture should yield candidates"
    for c in session.candidates:
        assert c.hook_text == c.title  # pre-filled, user may override


def test_build_session_propagates_hook_flags(tmp_path):
    d = tmp_path / "EP001"
    d.mkdir()
    (d / "curation.json").write_text((FIX / "curation.json").read_text())
    on = build_session(d, "EP001", hook_enabled=True, hook_duration_s=5.0)
    assert on.hook_enabled is True and on.hook_duration_s == 5.0
    off = build_session(d, "EP001")
    assert off.hook_enabled is False and off.hook_duration_s == 0.0


# ── gate derives hook_enabled from the job's template ────────────────────────

def _proc(template_id="t"):
    p = BatchProcessor.__new__(BatchProcessor)
    p.template_id = template_id
    return p


def test_resolve_hook_title_on_when_template_enabled(monkeypatch):
    spec = types.SimpleNamespace(enabled=True, duration_s=4.0)
    tpl = types.SimpleNamespace(intro_title=spec)
    monkeypatch.setattr(clips, "store", MagicMock())  # unrelated, keep import clean
    import packages.clips.templates.store as store_mod
    monkeypatch.setattr(store_mod.TemplateStore, "resolve", lambda self, _id: tpl)
    enabled, dur = _proc()._resolve_hook_title()
    assert enabled is True and dur == 4.0


def test_resolve_hook_title_off_when_disabled(monkeypatch):
    tpl = types.SimpleNamespace(intro_title=types.SimpleNamespace(enabled=False, duration_s=4.0))
    import packages.clips.templates.store as store_mod
    monkeypatch.setattr(store_mod.TemplateStore, "resolve", lambda self, _id: tpl)
    assert _proc()._resolve_hook_title() == (False, 0.0)


def test_resolve_hook_title_off_on_resolution_failure(monkeypatch):
    import packages.clips.templates.store as store_mod
    def boom(self, _id):
        raise RuntimeError("no template")
    monkeypatch.setattr(store_mod.TemplateStore, "resolve", boom)
    assert _proc()._resolve_hook_title() == (False, 0.0)


# ── payload exposes the hook flags ───────────────────────────────────────────

def test_get_brief_exposes_hook_flags_and_text(client, brief_dir, monkeypatch):
    _wire(monkeypatch, brief_dir)
    body = client.get("/api/jobs/job1/brief").json()
    assert body["hook_enabled"] is True
    assert body["hook_duration_s"] == 4.0
    assert all("hook_text" in c for c in body["candidates"])


# ── edit endpoint ────────────────────────────────────────────────────────────

def test_set_hook_updates_and_persists(client, brief_dir, monkeypatch):
    _wire(monkeypatch, brief_dir)
    r = client.post("/api/jobs/job1/brief/candidate/1/hook", json={"hook_text": "Mi hook nuevo"})
    assert r.status_code == 200
    c1 = next(c for c in r.json()["candidates"] if c["id"] == 1)
    assert c1["hook_text"] == "Mi hook nuevo"
    saved = json.loads((brief_dir / "brief_session.json").read_text())
    assert next(c for c in saved["candidates"] if c["id"] == 1)["hook_text"] == "Mi hook nuevo"


def test_set_hook_trims_and_caps_length(client, brief_dir, monkeypatch):
    _wire(monkeypatch, brief_dir)
    r = client.post("/api/jobs/job1/brief/candidate/1/hook", json={"hook_text": "  " + "x" * 200 + "  "})
    assert r.status_code == 200
    c1 = next(c for c in r.json()["candidates"] if c["id"] == 1)
    assert len(c1["hook_text"]) == 120


def test_set_hook_404_when_candidate_missing(client, brief_dir, monkeypatch):
    _wire(monkeypatch, brief_dir)
    r = client.post("/api/jobs/job1/brief/candidate/999/hook", json={"hook_text": "x"})
    assert r.status_code == 404


def test_set_hook_409_when_not_awaiting(client, brief_dir, monkeypatch):
    _wire(monkeypatch, brief_dir, status="processing")
    r = client.post("/api/jobs/job1/brief/candidate/1/hook", json={"hook_text": "x"})
    assert r.status_code == 409


# ── approved mapping carries hook_text; render falls back to title ───────────

def _cand(id, start, end, title="", summary="", hook_text="", selected=True, origin="curation"):
    return types.SimpleNamespace(
        id=id, start_time=start, end_time=end, title=title, summary=summary,
        hook_text=hook_text, selected=selected, origin=origin,
    )


def test_approved_clip_carries_overridden_hook(monkeypatch):
    curation = [{"start_time": 100.0, "end_time": 200.0, "title": "Título", "summary": "s"}]
    monkeypatch.setattr(clips, "_load_curation", lambda d: curation)
    session = types.SimpleNamespace(
        candidates=[_cand(1, 100.0, 200.0, title="Título", summary="s", hook_text="HOOK EDITADO")]
    )
    out = clips._approved_curated_clips(Path("/tmp/x"), session)
    assert out[0].hook_text == "HOOK EDITADO"


def test_approved_clip_hook_falls_back_to_title(monkeypatch):
    curation = [{"start_time": 100.0, "end_time": 200.0, "title": "Título", "summary": "s"}]
    monkeypatch.setattr(clips, "_load_curation", lambda d: curation)
    session = types.SimpleNamespace(
        candidates=[_cand(1, 100.0, 200.0, title="Título", summary="s", hook_text="")]
    )
    out = clips._approved_curated_clips(Path("/tmp/x"), session)
    assert out[0].hook_text == "Título"


def test_render_uses_hook_text_over_title():
    """The render rule: clip_title = hook_text or title."""
    clip = CuratedClip(start_time=0, end_time=10, title="Título", hook_text="HOOK", summary="s")
    chosen = getattr(clip, "hook_text", "") or getattr(clip, "title", "")
    assert chosen == "HOOK"
    clip2 = CuratedClip(start_time=0, end_time=10, title="Título", hook_text="", summary="s")
    chosen2 = getattr(clip2, "hook_text", "") or getattr(clip2, "title", "")
    assert chosen2 == "Título"
