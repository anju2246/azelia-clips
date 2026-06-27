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


def test_get_installed_fonts_returns_list(client):
    r = client.get("/api/templates/fonts")
    assert r.status_code == 200
    installed = r.json()["installed"]
    assert isinstance(installed, list)
    assert all(isinstance(f, str) for f in installed)


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


# ── import / export (T7) ─────────────────────────────────────────────────────

import io
import json


def test_export_import_roundtrip_creates_equivalent_template(client, monkeypatch):
    import server.routes.templates as tr

    monkeypatch.setattr(tr, "_font_installed", lambda name: True)

    # Export a builtin as .azt
    exp = client.get("/api/templates/splitscreen/export")
    assert exp.status_code == 200
    azt = exp.content

    # Re-import it
    r = client.post(
        "/api/templates/import",
        files={"file": ("splitscreen.azt", io.BytesIO(azt), "application/json")},
    )
    assert r.status_code == 201
    body = r.json()
    imported = body["template"]
    assert imported["is_builtin"] is False  # forced custom
    assert imported["subtitles"]["margin_v"] == 620  # style preserved
    assert body["warnings"] == []


def test_import_unknown_schema_version_returns_422(client):
    bad = json.dumps({"schema_version": 99, "id": "x", "name": "X"}).encode()
    r = client.post(
        "/api/templates/import",
        files={"file": ("x.azt", io.BytesIO(bad), "application/json")},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "IMPORT_VERSION_UNSUPPORTED"


def test_import_non_json_returns_422(client):
    r = client.post(
        "/api/templates/import",
        files={"file": ("x.azt", io.BytesIO(b"not json{{"), "application/json")},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "IMPORT_PARSE_ERROR"


def test_import_missing_font_returns_warning_not_error(client, monkeypatch):
    import server.routes.templates as tr

    monkeypatch.setattr(tr, "_font_installed", lambda name: False)

    azt = client.get("/api/templates/podcast/export").content
    r = client.post(
        "/api/templates/import",
        files={"file": ("podcast.azt", io.BytesIO(azt), "application/json")},
    )
    assert r.status_code == 201
    assert "FONT_NOT_INSTALLED" in r.json()["warnings"]


def test_create_and_get_roundtrips_intro_title(client):
    """T13 — intro_title persists through create and reads back."""
    body = {
        "name": "Hook Tmpl",
        "intro_title": {
            "enabled": True,
            "duration_s": 4.0,
            "font_name": "",
            "font_size": 90,
            "color": "&H00FFFFFF",
            "outline_color": "&H00000000",
            "position": "top",
            "box": True,
            "delay_captions": True,
        },
    }
    created = client.post("/api/templates", json=body)
    assert created.status_code == 201, created.text
    tid = created.json()["id"]
    got = client.get(f"/api/templates/{tid}").json()
    assert got["intro_title"]["enabled"] is True
    assert got["intro_title"]["font_size"] == 90
    assert got["intro_title"]["position"] == "top"
    # And it can be disabled via PUT (null).
    put = client.put(
        f"/api/templates/{tid}",
        json={"name": "Hook Tmpl", "intro_title": None},
    )
    assert put.status_code == 200
    assert put.json()["intro_title"] is None
