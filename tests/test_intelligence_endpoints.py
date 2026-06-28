"""T7 — Orquestación: POST /analytics/intelligence/refresh."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server.routes.analytics as analytics
from packages.core.services.niche_import import import_niche_signals

SIGNALS = Path(__file__).parent / "fixtures" / "niche" / "ic_signals_slice.json"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(analytics, "YT_DB_PATH", tmp_path / "youtube_shorts.db")
    conn = analytics._get_yt_db()
    import_niche_signals(conn, SIGNALS)
    # un short con retención
    conn.execute(
        "INSERT INTO youtube_shorts (video_id, user_id, hook_type, duration_seconds, "
        "average_view_percentage, view_count, like_count, comment_count) "
        "VALUES ('v1','local','question',20,72.0,100,10,2)"
    )
    conn.commit()
    conn.close()
    from server.app import app
    return TestClient(app)


def test_refresh_runs_and_summarizes(client):
    r = client.post("/api/analytics/intelligence/refresh", json={"confirmed": True})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "refreshed"
    assert data["shorts"] == 1
    assert data["with_retention"] == 1
    assert data["niche_signals"] >= 10
    assert data["creator_self_written"] >= 1
    assert "links_suggested" in data


def test_refresh_blocked_by_active_job_409(client, monkeypatch):
    import server.services.jobs_guard as guard
    monkeypatch.setattr(guard, "has_active_jobs", lambda: (True, ["job_abc"]))
    r = client.post("/api/analytics/intelligence/refresh", json={"confirmed": True})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ACTIVE_JOBS"
    assert "job_abc" in r.json()["detail"]["job_ids"]
