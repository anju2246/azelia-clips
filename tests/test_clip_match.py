"""T5 — Vínculo clip↔video: scoring, suggest, confirm/reject + endpoints."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server.routes.analytics as analytics
from packages.core.services import clip_match as cm

CURATION_FIXTURE = Path(__file__).parent / "fixtures" / "brief" / "curation.json"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(analytics, "YT_DB_PATH", tmp_path / "youtube_shorts.db")
    c = analytics._get_yt_db()
    yield c
    c.close()


def _insert_short(conn, video_id, title, dur):
    conn.execute(
        "INSERT INTO youtube_shorts (video_id, user_id, title, duration_seconds, view_count) "
        "VALUES (?, 'local', ?, ?, 0)",
        (video_id, title, dur),
    )
    conn.commit()


# ── scoring puro ─────────────────────────────────────────────────────────────

def test_title_similarity_and_duration_scoring():
    assert cm.title_similarity("Why AI Will Replace Jobs", "Why AI Will Replace Jobs") == 1.0
    assert cm.title_similarity("totally different", "Why AI replace") < 0.5
    # proximidad de duración
    assert cm.duration_proximity(48, 48) == 1.0
    assert cm.duration_proximity(48, 49) == 1.0          # dentro de tolerancia
    assert cm.duration_proximity(48, 200) == 0.0         # muy lejos
    assert 0.0 < cm.duration_proximity(48, 60) < 1.0     # intermedio


def test_combined_score_and_method():
    clip = {"title": "Why AI Will Replace Most Jobs", "social_caption": "🤖 future", "start_time": 0, "end_time": 48}
    short = {"title": "Why AI Will Replace Most Jobs", "duration_seconds": 48}
    score, method = cm.combined_score(clip, short)
    assert score > 0.9
    assert method == "combined"


# ── suggest ──────────────────────────────────────────────────────────────────

def test_suggest_orders_by_confidence(conn):
    clips = json.load(open(CURATION_FIXTURE))  # 3 clips reales
    # shorts: uno casi idéntico al primer clip, otro distinto
    _insert_short(conn, "vidA", clips[0]["title"], clips[0]["end_time"] - clips[0]["start_time"])
    _insert_short(conn, "vidB", "Algo totalmente distinto sin relación", 9)
    shorts = [
        {"video_id": "vidA", "title": clips[0]["title"], "duration_seconds": clips[0]["end_time"] - clips[0]["start_time"]},
        {"video_id": "vidB", "title": "Algo totalmente distinto sin relación", "duration_seconds": 9},
    ]
    out = cm.suggest_links(conn, clips, shorts, episode_id="ep1")
    assert len(out) >= 1
    # ordenado desc por confianza
    confs = [r["match_confidence"] for r in out]
    assert confs == sorted(confs, reverse=True)
    # el mejor match es vidA con el primer clip
    assert out[0]["video_id"] == "vidA"
    assert out[0]["status"] == "suggested"
    # persistió en clip_links
    n = conn.execute("SELECT COUNT(*) FROM clip_links WHERE status='suggested'").fetchone()[0]
    assert n >= 1


def test_confirm_sets_video_and_attrs(conn):
    clips = json.load(open(CURATION_FIXTURE))
    short = {"video_id": "vidA", "title": clips[0]["title"], "duration_seconds": clips[0]["end_time"] - clips[0]["start_time"]}
    cm.suggest_links(conn, [clips[0]], [short], episode_id="ep1")
    link_id = conn.execute("SELECT id FROM clip_links LIMIT 1").fetchone()[0]
    res = cm.confirm_link(conn, link_id, video_id="vidA")
    assert res["status"] == "confirmed"
    assert res["video_id"] == "vidA"
    attrs = conn.execute("SELECT clip_attrs_json FROM clip_links WHERE id=?", (link_id,)).fetchone()[0]
    assert "category" in attrs


def test_reassign_reopens_previous(conn):
    # dos clips distintos confirmados contra el MISMO video → el previo se reabre
    clipA = {"title": "Clip A", "start_time": 0, "end_time": 30}
    clipB = {"title": "Clip B", "start_time": 40, "end_time": 70}
    short = {"video_id": "vidX", "title": "algo", "duration_seconds": 30}
    cm.suggest_links(conn, [clipA, clipB], [short], episode_id="ep1")
    ids = [r[0] for r in conn.execute("SELECT id FROM clip_links ORDER BY id").fetchall()]
    cm.confirm_link(conn, ids[0], video_id="vidX")
    cm.confirm_link(conn, ids[1], video_id="vidX")  # reasigna el mismo video
    st0 = conn.execute("SELECT status FROM clip_links WHERE id=?", (ids[0],)).fetchone()[0]
    st1 = conn.execute("SELECT status FROM clip_links WHERE id=?", (ids[1],)).fetchone()[0]
    assert st1 == "confirmed"
    assert st0 == "suggested"  # el previo se reabrió


def test_reject(conn):
    cm.suggest_links(conn, [{"title": "X", "start_time": 0, "end_time": 30}],
                     [{"video_id": "v", "title": "X", "duration_seconds": 30}], episode_id="ep1")
    link_id = conn.execute("SELECT id FROM clip_links LIMIT 1").fetchone()[0]
    assert cm.reject_link(conn, link_id) is True
    st = conn.execute("SELECT status FROM clip_links WHERE id=?", (link_id,)).fetchone()[0]
    assert st == "rejected"


# ── endpoints ────────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(analytics, "YT_DB_PATH", tmp_path / "youtube_shorts.db")
    from packages.core.config import settings
    data_dir = tmp_path / "data"
    (data_dir / "jobs" / "ep1").mkdir(parents=True)
    monkeypatch.setattr(settings, "data_dir", data_dir, raising=False)
    # curation.json real en el episodio
    clips = json.load(open(CURATION_FIXTURE))
    (data_dir / "jobs" / "ep1" / "curation.json").write_text(json.dumps(clips))
    # shorts que matcheen
    c = analytics._get_yt_db()
    _insert_short(c, "vidA", clips[0]["title"], clips[0]["end_time"] - clips[0]["start_time"])
    c.close()
    from server.app import app
    return TestClient(app)


def test_endpoint_suggest_list_confirm(client):
    r = client.post("/api/analytics/clip-links/suggest", json={"episode_id": "ep1"})
    assert r.status_code == 200, r.text
    assert r.json()["count"] >= 1

    r2 = client.get("/api/analytics/clip-links?status=suggested")
    assert r2.status_code == 200
    links = r2.json()["links"]
    assert len(links) >= 1
    link_id = links[0]["id"]

    r3 = client.post(f"/api/analytics/clip-links/{link_id}", json={"action": "confirm", "video_id": "vidA"})
    assert r3.status_code == 200
    assert r3.json()["status"] == "confirmed"


def test_endpoint_unknown_episode_404(client):
    r = client.post("/api/analytics/clip-links/suggest", json={"episode_id": "no_existe"})
    assert r.status_code == 404


def test_endpoint_invalid_action_422(client):
    client.post("/api/analytics/clip-links/suggest", json={"episode_id": "ep1"})
    link_id = client.get("/api/analytics/clip-links").json()["links"][0]["id"]
    r = client.post(f"/api/analytics/clip-links/{link_id}", json={"action": "bogus"})
    assert r.status_code == 422


def test_endpoint_path_traversal_rejected(client):
    r = client.post("/api/analytics/clip-links/suggest", json={"episode_id": "../etc"})
    assert r.status_code == 422
