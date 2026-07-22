"""
Tests for the framing gate: the pre-render stop that lets the user set how tight
the close-up crop is, for THIS episode, before committing to a full render.

The gate only exists for single-shot layouts — where the crop IS the whole frame.
Face detection, FFmpeg and the background render are patched; nothing touches the
real DB or the podcast drive.
"""
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import server.routes.clips as clips
from packages.clips.curation.brief_builder import build_session, save_session
from packages.clips.templates.layout import (
    DEFAULT_SAFE_ZONE_MULT,
    MAX_SAFE_ZONE_MULT,
    MIN_SAFE_ZONE_MULT,
    is_single_shot,
)
from packages.clips.templates.models import LayoutSpec, Region, RegionSource
from server.app import app
from server.middleware.auth import require_auth

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


def _wire(monkeypatch, brief_dir, status="awaiting_framing", config=None):
    job = types.SimpleNamespace(job_id="job1", episode_id="EP001", status=status)
    fake_store = MagicMock()
    fake_store.get_job.return_value = job
    fake_store.get_config.return_value = config if config is not None else {}
    monkeypatch.setattr(clips, "store", fake_store)
    monkeypatch.setattr(clips, "_brief_dir", lambda job_id, episode_id=None: brief_dir)
    return fake_store


# ── Which layouts get a gate ─────────────────────────────────────────────────

def _one(mode="active_speaker"):
    return [Region(x=0, y=0, w=1, h=1, source=RegionSource(mode=mode))]


def test_single_shot_detects_fullscreen_and_lone_region():
    assert is_single_shot(LayoutSpec(type="fullscreen")) is True
    assert is_single_shot(LayoutSpec(type="regions", regions=_one())) is True
    assert is_single_shot(LayoutSpec(type="regions", regions=_one("speaker"))) is True


def test_single_shot_excludes_multi_shot_layouts():
    two = _one() + [Region(x=0, y=0.5, w=1, h=0.5, source=RegionSource(mode="wide"))]
    assert is_single_shot(LayoutSpec(type="split")) is False
    assert is_single_shot(LayoutSpec(type="regions", regions=two)) is False


# ── Gate opening ─────────────────────────────────────────────────────────────

def _template(layout_type="fullscreen"):
    return types.SimpleNamespace(layout=LayoutSpec(type=layout_type))


def _patch_template(monkeypatch, layout_type="fullscreen"):
    store_cls = MagicMock()
    store_cls.return_value.resolve.return_value = _template(layout_type)
    monkeypatch.setattr("packages.clips.templates.store.TemplateStore", store_cls)


def test_gate_opens_for_single_shot_template(monkeypatch):
    _patch_template(monkeypatch, "fullscreen")
    assert clips._framing_gate_open("job1", "tpl", {}) is True


def test_gate_stays_shut_for_split_template(monkeypatch):
    _patch_template(monkeypatch, "split")
    assert clips._framing_gate_open("job1", "tpl", {}) is False


def test_gate_does_not_reopen_once_confirmed(monkeypatch):
    """The latch: without it, confirming would bounce straight back to the gate."""
    _patch_template(monkeypatch, "fullscreen")
    assert clips._framing_gate_open("job1", "tpl", {"framing_confirmed": True}) is False


def test_gate_stays_shut_when_template_cannot_be_resolved(monkeypatch):
    """A styling lookup must never strand a job in a gate nobody can answer."""
    boom = MagicMock()
    boom.return_value.resolve.side_effect = RuntimeError("no such template")
    monkeypatch.setattr("packages.clips.templates.store.TemplateStore", boom)
    assert clips._framing_gate_open("job1", "tpl", {}) is False


# ── GET /framing ─────────────────────────────────────────────────────────────

def test_get_framing_returns_current_choice_and_presets(client, brief_dir, monkeypatch):
    _wire(monkeypatch, brief_dir)
    r = client.get("/api/jobs/job1/framing")
    assert r.status_code == 200
    body = r.json()
    assert body["safe_zone_mult"] == DEFAULT_SAFE_ZONE_MULT
    assert body["approved_count"] == 2  # the fixture's above-threshold clips
    assert [p["id"] for p in body["presets"]] == ["cerrado", "normal", "abierto", "ambiente"]


def test_get_framing_echoes_a_previous_choice(client, brief_dir, monkeypatch):
    _wire(monkeypatch, brief_dir, config={"safe_zone_mult": 4.0})
    assert client.get("/api/jobs/job1/framing").json()["safe_zone_mult"] == 4.0


def test_framing_endpoints_409_when_job_is_not_at_the_gate(client, brief_dir, monkeypatch):
    _wire(monkeypatch, brief_dir, status="processing")
    assert client.get("/api/jobs/job1/framing").status_code == 409
    assert client.post("/api/jobs/job1/framing/confirm", json={}).status_code == 409


# ── POST /framing/confirm ────────────────────────────────────────────────────

def test_confirm_saves_framing_and_launches_the_render(client, brief_dir, monkeypatch):
    fake_store = _wire(monkeypatch, brief_dir)
    rendered = []
    monkeypatch.setattr(clips, "_render_approved", lambda *a: rendered.append(a))

    r = client.post("/api/jobs/job1/framing/confirm", json={"safe_zone_mult": 3.5})
    assert r.status_code == 202
    assert r.json()["safe_zone_mult"] == 3.5

    saved = fake_store.save_config.call_args[0][1]
    assert saved["safe_zone_mult"] == 3.5
    assert saved["framing_confirmed"] is True  # latch, so the gate does not reopen
    assert rendered == [("job1", 1)]


def test_confirm_clamps_out_of_range_framing(client, brief_dir, monkeypatch):
    fake_store = _wire(monkeypatch, brief_dir)
    monkeypatch.setattr(clips, "_render_approved", lambda *a: None)

    client.post("/api/jobs/job1/framing/confirm", json={"safe_zone_mult": 99})
    assert fake_store.save_config.call_args[0][1]["safe_zone_mult"] == MAX_SAFE_ZONE_MULT

    client.post("/api/jobs/job1/framing/confirm", json={"safe_zone_mult": 0.1})
    assert fake_store.save_config.call_args[0][1]["safe_zone_mult"] == MIN_SAFE_ZONE_MULT


def test_confirm_rejects_non_numeric_framing(client, brief_dir, monkeypatch):
    _wire(monkeypatch, brief_dir)
    monkeypatch.setattr(clips, "_render_approved", lambda *a: None)
    assert client.post(
        "/api/jobs/job1/framing/confirm", json={"safe_zone_mult": "muy cerrado"}
    ).status_code == 422


def test_confirm_defaults_when_framing_is_omitted(client, brief_dir, monkeypatch):
    fake_store = _wire(monkeypatch, brief_dir)
    monkeypatch.setattr(clips, "_render_approved", lambda *a: None)
    client.post("/api/jobs/job1/framing/confirm", json={})
    assert fake_store.save_config.call_args[0][1]["safe_zone_mult"] == DEFAULT_SAFE_ZONE_MULT


# ── Crop geometry ────────────────────────────────────────────────────────────

def test_looser_framing_crops_a_larger_area():
    """The whole point of the knob: a bigger multiplier must show more of the set."""
    from packages.clips.vision.face_tracker import FaceDetection
    from packages.clips.vision.framing_preview import compute_crop_rect

    faces = [FaceDetection(frame_idx=0, timestamp=0.0, x=800, y=400, width=300,
                           height=300, identity_id="FACE_00")]
    tight = compute_crop_rect(faces, 1920, 1080, safe_zone_mult=1.8)
    loose = compute_crop_rect(faces, 1920, 1080, safe_zone_mult=4.0)
    assert loose["h"] > tight["h"] and loose["w"] > tight["w"]


def test_crop_never_leaves_the_source_frame():
    """A face at the very edge must not produce a negative or overflowing crop."""
    from packages.clips.vision.face_tracker import FaceDetection
    from packages.clips.vision.framing_preview import compute_crop_rect

    edge = [FaceDetection(frame_idx=0, timestamp=0.0, x=0, y=0, width=200,
                          height=200, identity_id="FACE_00")]
    r = compute_crop_rect(edge, 1920, 1080, safe_zone_mult=4.0)
    assert r["x"] >= 0 and r["y"] >= 0
    assert r["x"] + r["w"] <= 1920 and r["y"] + r["h"] <= 1080


def test_offset_moves_the_crop_without_resizing_it():
    """The nudge is a pan, not a zoom: same window, different place."""
    from packages.clips.vision.face_tracker import FaceDetection
    from packages.clips.vision.framing_preview import compute_crop_rect

    faces = [FaceDetection(frame_idx=0, timestamp=0.0, x=800, y=400, width=300,
                           height=300, identity_id="FACE_00")]
    base = compute_crop_rect(faces, 1920, 1080, safe_zone_mult=2.0)
    right = compute_crop_rect(faces, 1920, 1080, safe_zone_mult=2.0, offset_x=0.2)
    down = compute_crop_rect(faces, 1920, 1080, safe_zone_mult=2.0, offset_y=0.2)

    assert right["w"] == base["w"] and right["h"] == base["h"]
    assert right["x"] > base["x"] and right["y"] == base["y"]
    assert down["y"] > base["y"] and down["x"] == base["x"]


def test_offset_cannot_push_the_crop_off_the_frame():
    from packages.clips.vision.face_tracker import FaceDetection
    from packages.clips.vision.framing_preview import compute_crop_rect

    faces = [FaceDetection(frame_idx=0, timestamp=0.0, x=1600, y=800, width=200,
                           height=200, identity_id="FACE_00")]
    r = compute_crop_rect(faces, 1920, 1080, safe_zone_mult=2.0,
                          offset_x=0.5, offset_y=0.5)
    assert r["x"] + r["w"] <= 1920 and r["y"] + r["h"] <= 1080
    assert r["x"] >= 0 and r["y"] >= 0


def test_render_offset_shifts_the_crop_expression():
    """The preview and the render must agree, so the reframer applies it too."""
    from packages.clips.vision.reframer import VideoReframer

    keys = [(0.0, 500)]
    centred = VideoReframer._build_crop_expr(keys, 200, 1920)
    shifted = VideoReframer._build_crop_expr([(0.0, 500 + 80)], 200, 1920)
    assert int(shifted) == int(centred) + 80


def test_confirm_persists_the_offset(client, brief_dir, monkeypatch):
    fake_store = _wire(monkeypatch, brief_dir)
    monkeypatch.setattr(clips, "_render_approved", lambda *a: None)

    r = client.post(
        "/api/jobs/job1/framing/confirm",
        json={"safe_zone_mult": 2.5, "offset_x": -0.15, "offset_y": 0.2},
    )
    assert r.status_code == 202
    saved = fake_store.save_config.call_args[0][1]
    assert saved["framing_offset_x"] == -0.15
    assert saved["framing_offset_y"] == 0.2


def test_confirm_clamps_an_extreme_offset(client, brief_dir, monkeypatch):
    from packages.clips.templates.layout import MAX_FRAMING_OFFSET

    fake_store = _wire(monkeypatch, brief_dir)
    monkeypatch.setattr(clips, "_render_approved", lambda *a: None)

    client.post("/api/jobs/job1/framing/confirm",
                json={"safe_zone_mult": 2.5, "offset_x": 9, "offset_y": -9})
    saved = fake_store.save_config.call_args[0][1]
    assert saved["framing_offset_x"] == MAX_FRAMING_OFFSET
    assert saved["framing_offset_y"] == -MAX_FRAMING_OFFSET


def test_get_framing_echoes_a_saved_offset(client, brief_dir, monkeypatch):
    _wire(monkeypatch, brief_dir,
          config={"framing_offset_x": -0.1, "framing_offset_y": 0.25})
    body = client.get("/api/jobs/job1/framing").json()
    assert body["offset_x"] == -0.1 and body["offset_y"] == 0.25


def test_crop_falls_back_to_centre_without_faces():
    from packages.clips.vision.framing_preview import compute_crop_rect

    r = compute_crop_rect([], 1920, 1080, safe_zone_mult=2.5)
    assert r["faces"] == 0
    assert r["x"] + r["w"] // 2 == pytest.approx(960, abs=2)
