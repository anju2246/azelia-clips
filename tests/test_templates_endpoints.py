"""Tests for the clip-template CRUD HTTP endpoints (T2).

A tmp_path is used as AZELIA_HOME and settings.data_dir is redirected there, so
the real ~/.azelia is never touched and templates persist under <tmp>/templates.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AZELIA_HOME", str(tmp_path))
    from packages.core.config import settings

    active_dir = tmp_path / "active"
    active_dir.mkdir()
    monkeypatch.setattr(settings, "data_dir", active_dir, raising=False)

    from server.app import app

    return TestClient(app)


# ── list ─────────────────────────────────────────────────────────────────────


def test_get_templates_includes_builtins_and_custom(client):
    r = client.get("/api/templates")
    assert r.status_code == 200
    templates = r.json()["templates"]
    by_id = {t["id"]: t for t in templates}
    for slug in ("hormozi", "mrbeast", "minimal", "podcast", "splitscreen"):
        assert slug in by_id
        assert by_id[slug]["is_builtin"] is True


# ── create ─────────────────────────────────────────────────────────────────


def test_post_template_creates_custom(client):
    r = client.post("/api/templates", json={"name": "My Brand"})
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == "my-brand"
    assert body["is_builtin"] is False

    # Now listed
    ids = {t["id"] for t in client.get("/api/templates").json()["templates"]}
    assert "my-brand" in ids


def test_post_invalid_body_returns_422(client):
    r = client.post(
        "/api/templates",
        json={"name": "Bad", "subtitles": {"font_size": 5}},
    )
    assert r.status_code == 422


# ── clone ──────────────────────────────────────────────────────────────────


def test_clone_builtin_creates_editable_copy(client):
    r = client.post("/api/templates/splitscreen/clone", json={"name": "My Split"})
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == "my-split"
    assert body["is_builtin"] is False
    # Subtitle style carried over from the builtin.
    assert body["subtitles"]["margin_v"] == 620


# ── read / delete ────────────────────────────────────────────────────────────


def test_get_one_and_delete_roundtrip(client):
    client.post("/api/templates", json={"name": "Temp One"})
    assert client.get("/api/templates/temp-one").status_code == 200

    d = client.delete("/api/templates/temp-one")
    assert d.status_code in (200, 204)
    assert client.get("/api/templates/temp-one").status_code == 404


# ── read-only / not-found ────────────────────────────────────────────────────


def test_put_builtin_returns_409_readonly(client):
    r = client.put(
        "/api/templates/splitscreen",
        json={"name": "Hacked Splitscreen"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["error_code"] == "TEMPLATE_READONLY"


def test_delete_missing_returns_404(client):
    r = client.delete("/api/templates/does-not-exist")
    assert r.status_code == 404
