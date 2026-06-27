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


def test_import_v1_azt_endpoint_migrates_to_current(client):
    """Regression (found in /verify): the import ENDPOINT — not just the store —
    must accept a v1 .azt and migrate it forward, not reject it as unsupported."""
    v1 = {
        "schema_version": 1,
        "id": "legacy",
        "name": "Legacy v1",
        "description": "",
        "author": "",
        "is_builtin": False,
        "created_at": "2025-01-01T00:00:00",
        "updated_at": "2025-01-01T00:00:00",
        "subtitles": {
            "font_name": "Arial", "font_size": 52,
            "primary_color": "&H00FFFFFF", "secondary_color": "&H0000FFFF",
            "outline_color": "&H00000000", "back_color": "&H80000000",
            "bold": True, "outline": 3, "shadow": 2, "alignment": 2,
            "margin_v": 50, "animation": "cumulative", "words_per_line": 5,
        },
        "layout": {
            "type": "split", "output_width": 1080, "output_height": 1920,
            "wide_height_ratio": 0.3167,
        },
    }
    r = client.post(
        "/api/templates/import",
        files={"file": ("legacy.azt", io.BytesIO(json.dumps(v1).encode()), "application/json")},
    )
    assert r.status_code == 201, r.text
    t = r.json()["template"]
    assert t["schema_version"] == 2
    assert t["is_builtin"] is False
    assert t["intro_title"] is None


def test_branding_roundtrip_and_logo_upload(client):
    """T10 — upload a logo, then create a template referencing it; it persists."""
    # 1×1 PNG (smallest valid-ish header is enough; endpoint checks type/size)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    up = client.post(
        "/api/templates/branding/logo",
        files={"file": ("My Brand!.png", io.BytesIO(png), "image/png")},
    )
    assert up.status_code == 200, up.text
    rel = up.json()["logo_path"]
    assert rel.startswith("branding/") and rel.endswith(".png")

    created = client.post(
        "/api/templates",
        json={"name": "Branded", "branding": {"logo_path": rel, "position": "bottom-right", "scale": 0.12}},
    )
    assert created.status_code == 201, created.text
    got = client.get(f"/api/templates/{created.json()['id']}").json()
    assert got["branding"]["logo_path"] == rel
    assert got["branding"]["position"] == "bottom-right"


def test_branding_logo_rejects_non_image(client):
    r = client.post(
        "/api/templates/branding/logo",
        files={"file": ("x.txt", io.BytesIO(b"nope"), "text/plain")},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "IMAGE_INVALID"


def test_create_branding_rejects_absolute_path(client):
    r = client.post(
        "/api/templates",
        json={"name": "Bad Brand", "branding": {"logo_path": "/etc/passwd"}},
    )
    assert r.status_code == 422


def test_bumpers_roundtrip_and_upload(client):
    """T12 — upload a bumper, reference it in a template; it persists."""
    up = client.post(
        "/api/templates/bumpers/upload",
        files={"file": ("Intro Clip.mp4", io.BytesIO(b"\x00" * 64), "video/mp4")},
    )
    assert up.status_code == 200, up.text
    rel = up.json()["path"]
    assert rel.startswith("bumpers/") and rel.endswith(".mp4")

    created = client.post(
        "/api/templates",
        json={"name": "Bumped", "bumpers": {"intro_path": rel}},
    )
    assert created.status_code == 201, created.text
    got = client.get(f"/api/templates/{created.json()['id']}").json()
    assert got["bumpers"]["intro_path"] == rel


def test_bumper_upload_rejects_non_video(client):
    r = client.post(
        "/api/templates/bumpers/upload",
        files={"file": ("x.txt", io.BytesIO(b"nope"), "text/plain")},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "VIDEO_INVALID"


def test_create_bumpers_rejects_absolute_path(client):
    r = client.post(
        "/api/templates",
        json={"name": "Bad Bump", "bumpers": {"intro_path": "/etc/passwd"}},
    )
    assert r.status_code == 422


def test_asset_endpoint_serves_logo_and_blocks_traversal(client):
    """Editor preview fetches the real logo; only branding/bumpers files served."""
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    rel = client.post(
        "/api/templates/branding/logo",
        files={"file": ("l.png", io.BytesIO(png), "image/png")},
    ).json()["logo_path"]
    ok = client.get(f"/api/templates/asset?path={rel}")
    assert ok.status_code == 200
    assert ok.content.startswith(b"\x89PNG")
    # traversal / arbitrary paths are rejected
    assert client.get("/api/templates/asset?path=../secrets.env").status_code == 404
    assert client.get("/api/templates/asset?path=/etc/passwd").status_code == 404
    assert client.get("/api/templates/asset?path=templates/foo.azt").status_code == 404
