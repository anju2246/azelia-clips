"""Tests for the profile + Claude HTTP endpoints (T5, F1–F7).

All tests are expected to FAIL until the GREEN-phase implementation lands.
A tmp_path is used as AZELIA_HOME and settings.data_dir is redirected there,
so the real ~/.azelia is never touched. The TestClient is built WITHOUT the
lifespan context manager on purpose (so boot-time migration / workers don't run).
job_store and claude detection are monkeypatched.
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

    from packages.core.profiles import ProfileManager

    pm = ProfileManager(tmp_path)
    pm.create("Alpha")  # first → active + default
    pm.create("Beta")

    from server.app import app

    return TestClient(app)


# ── F1 list ────────────────────────────────────────────────────────────────


def test_list_profiles_includes_active_and_claude(client):
    r = client.get("/api/profiles")
    assert r.status_code == 200
    data = r.json()
    assert data["active_profile"] == "alpha"
    by_id = {p["id"]: p for p in data["profiles"]}
    assert by_id["alpha"]["active"] is True
    assert by_id["beta"]["active"] is False
    assert "claude_binary" in by_id["alpha"]


# ── F2 create ────────────────────────────────────────────────────────────────


def test_create_profile_201_does_not_switch(client):
    r = client.post("/api/profiles", json={"name": "Gamma"})
    assert r.status_code == 201
    assert r.json()["id"] == "gamma"
    assert client.get("/api/profiles").json()["active_profile"] == "alpha"


def test_create_invalid_name_422(client):
    r = client.post("/api/profiles", json={"name": ""})
    assert r.status_code == 422


# ── F3 patch ────────────────────────────────────────────────────────────────


def test_patch_rename_keeps_id_and_data_dir(client):
    before = {p["id"]: p for p in client.get("/api/profiles").json()["profiles"]}["beta"]
    r = client.patch("/api/profiles/beta", json={"name": "Beta Renamed"})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "beta"
    assert body["name"] == "Beta Renamed"
    assert body["data_dir"] == before["data_dir"]


# ── F4 delete ────────────────────────────────────────────────────────────────


def test_delete_active_409(client):
    assert client.delete("/api/profiles/alpha").status_code == 409


def test_delete_last_409(client):
    assert client.delete("/api/profiles/beta").status_code == 200
    assert client.delete("/api/profiles/alpha").status_code == 409


def test_delete_data_flag(client):
    from packages.core.config import _azelia_home

    client.post("/api/profiles", json={"name": "Gamma"})
    gdir = _azelia_home() / "profiles" / "gamma"
    assert gdir.is_dir()
    r = client.delete("/api/profiles/gamma?delete_data=true")
    assert r.status_code == 200
    assert not gdir.exists()


# ── F5 activate ──────────────────────────────────────────────────────────────


def test_activate_blocked_by_active_jobs_409_lists_ids(client, monkeypatch):
    import server.routes.profiles as prof

    monkeypatch.setattr(prof, "has_active_jobs", lambda: (True, ["job-1"]))
    r = client.post("/api/profiles/beta/activate")
    assert r.status_code == 409
    assert "job-1" in str(r.json())


def test_activate_writes_registry_then_touches_restart(client, monkeypatch):
    import server.routes.profiles as prof

    monkeypatch.setattr(prof, "has_active_jobs", lambda: (False, []))
    from packages.core.config import _azelia_home, settings
    from packages.core.profiles import ProfileManager

    r = client.post("/api/profiles/beta/activate")
    assert r.status_code == 200
    assert r.json()["status"] == "restarting"
    assert ProfileManager(_azelia_home()).active().id == "beta"
    assert (settings.data_dir / ".restart").exists()


def test_activate_same_profile_noop(client, monkeypatch):
    import server.routes.profiles as prof

    monkeypatch.setattr(prof, "has_active_jobs", lambda: (False, []))
    r = client.post("/api/profiles/alpha/activate")
    assert r.json()["status"] == "noop"


# ── F6/F7 Claude ─────────────────────────────────────────────────────────────


def test_claude_installations_lists_binaries_and_accounts(client, monkeypatch):
    import server.routes.profiles as prof

    monkeypatch.setattr(
        prof.claude_detect, "detect_installations",
        lambda: [{"path": "/x/claude", "realpath": "/x/claude", "source": "path", "version": "1", "valid": True}],
    )
    monkeypatch.setattr(
        prof.claude_detect, "detect_accounts",
        lambda extra_config_dirs=None: [{"email": "a@b.com", "config_dir": None, "display_name": "A", "plan": "pro", "logged_in": True}],
    )
    r = client.get("/api/claude/installations")
    assert r.status_code == 200
    data = r.json()
    assert data["installations"][0]["path"] == "/x/claude"
    assert data["accounts"][0]["email"] == "a@b.com"


def test_claude_validate_returns_email(client, monkeypatch):
    import server.routes.profiles as prof

    monkeypatch.setattr(
        prof.claude_detect, "validate",
        lambda path=None, config_dir=None: {"valid": True, "version": "1", "account": {"email": "a@b.com"}},
    )
    r = client.post("/api/claude/validate", json={"path": "/x/claude", "config_dir": None})
    assert r.status_code == 200
    assert r.json()["account"]["email"] == "a@b.com"
