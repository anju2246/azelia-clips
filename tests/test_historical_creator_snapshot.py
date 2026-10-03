"""Sync histórico del canal propio: captions, Parakeet y snapshot creator_self.

Las métricas de los tests son fijas de fixture. No son números del canal.
"""
import asyncio
import json
from pathlib import Path

import pytest

import packages.core.services.nvidia_asr as nvidia_asr
import packages.core.services.youtube_historical as yh
import server.routes.analytics as analytics
from packages.core.services.creator_self import (
    parse_core_topics,
    refresh_creator_self_snapshot,
)
from packages.core.services.youtube_historical import (
    pending_label_ids,
    upsert_short_performance,
)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    db_path = tmp_path / "youtube_shorts.db"
    monkeypatch.setattr(analytics, "YT_DB_PATH", db_path)
    monkeypatch.setattr(yh.YouTubeHistoricalExtractor, "YT_DB_PATH", str(db_path))
    c = analytics._get_yt_db()
    yield c
    c.close()


def test_historical_module_does_not_use_mlx_whisper():
    src = Path(yh.__file__).read_text()
    assert "mlx-community/whisper-tiny" not in src
    assert "mlx_whisper" not in src
    assert nvidia_asr.NVIDIA_MODEL_ID == "nvidia/parakeet-tdt-0.6b-v3"
    assert nvidia_asr.ONNX_MODEL_NAME == "nemo-parakeet-tdt-0.6b-v3"
    assert nvidia_asr.DEFAULT_QUANTIZATION == "int8"


def test_transcribe_wav_strips_model_text(monkeypatch):
    class _Model:
        def recognize(self, path):
            assert path.endswith(".wav")
            return "  hola desde parakeet  "

    monkeypatch.setattr(nvidia_asr, "_get_model", lambda: _Model())
    assert nvidia_asr.transcribe_wav("/tmp/short.wav") == "hola desde parakeet"


def test_parse_core_topics_accepts_json_and_csv():
    assert parse_core_topics('["startups", "dinero"]') == ["startups", "dinero"]
    assert parse_core_topics("startups, dinero") == ["startups", "dinero"]
    assert parse_core_topics("") == []
    assert parse_core_topics(None) == []


def test_missing_analytics_does_not_invent_retention(conn):
    upsert_short_performance(conn, "local", {
        "video_id": "v1",
        "title": "Sin retención",
        "duration_seconds": 20,
        "views": 100,
        "likes": 4,
        "comments": 1,
        "analytics": {},
    })
    conn.commit()
    stored = conn.execute(
        "SELECT average_view_percentage, view_count FROM youtube_shorts WHERE video_id='v1'"
    ).fetchone()
    assert stored[0] is None
    assert stored[1] == 100
    snap = refresh_creator_self_snapshot(conn, "local")
    assert snap["median_retention"] is None
    assert snap["shorts_with_retention"] == 0


def test_refresh_keeps_real_retention_and_updates_views(conn):
    upsert_short_performance(conn, "local", {
        "video_id": "v1",
        "title": "Con retención",
        "duration_seconds": 28,
        "privacy_status": "public",
        "views": 100,
        "likes": 10,
        "comments": 2,
        "analytics": {"averageViewPercentage": 64.5, "averageViewDuration": 18.0},
    })
    conn.commit()
    upsert_short_performance(conn, "local", {
        "video_id": "v1",
        "title": "Con retención",
        "duration_seconds": 28,
        "views": 250,
        "likes": 20,
        "comments": 3,
        "analytics": {},
    })
    conn.commit()
    stored = conn.execute(
        "SELECT view_count, average_view_percentage FROM youtube_shorts WHERE video_id='v1'"
    ).fetchone()
    assert stored[0] == 250
    assert stored[1] == pytest.approx(64.5)


def test_json_topics_cross_real_retention(conn, tmp_path):
    conn.execute(
        "INSERT INTO youtube_shorts (video_id, user_id, hook_type, duration_seconds, "
        "average_view_percentage, view_count, like_count, comment_count, core_topics, privacy_status) "
        "VALUES ('old','local','question',24,71.0,500,40,6,'[\"startups\", \"dinero\"]','public')"
    )
    conn.commit()
    path = tmp_path / "creator_self.local.json"
    snap = refresh_creator_self_snapshot(conn, "local", snapshot_path=str(path))
    topics = {row["topic_tag"]: row["avg_retention_pct"] for row in snap["signals"] if row["topic_tag"]}
    assert topics["startups"] == pytest.approx(71.0)
    assert topics["dinero"] == pytest.approx(71.0)
    assert snap["median_retention"] == pytest.approx(71.0)
    on_disk = json.loads(path.read_text())
    assert on_disk["signal_type"] == "creator_self"
    assert on_disk["shorts_with_retention"] == 1


class _Exec:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _Call:
    def __init__(self, payload):
        self.payload = payload

    def list(self, **kwargs):
        return _Exec(self.payload)


class _YouTube:
    def channels(self):
        return _Call({
            "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]
        })

    def playlistItems(self):
        return _Call({
            "items": [{"contentDetails": {"videoId": "vid1"}}]
        })

    def videos(self):
        return _Call({
            "items": [{
                "id": "vid1",
                "snippet": {"title": "Short real", "publishedAt": "2026-05-02T00:00:00Z"},
                "contentDetails": {"duration": "PT30S"},
                "statistics": {"viewCount": "1000", "likeCount": "40", "commentCount": "5"},
                "status": {"privacyStatus": "public"},
            }]
        })


def test_process_labels_and_refreshes_snapshot_from_real_metrics(conn, monkeypatch):
    monkeypatch.setattr(yh, "get_llm", lambda: object())
    monkeypatch.setattr(yh.googleapiclient.discovery, "build", lambda *a, **k: _YouTube())

    async def _analytics(self, creds, channel_id, video_ids):
        assert video_ids == ["vid1"]
        return {"vid1": {"averageViewPercentage": 64.5, "averageViewDuration": 18.0, "shares": 2}}

    async def _curve(self, creds, channel_id, video_id):
        return []

    async def _analyze(self, video):
        assert video["metrics"]["views"] == 1000
        assert video["analytics"]["averageViewPercentage"] == 64.5
        return {
            "analysis": {
                "hook_type": "question",
                "emotional_charge": "educational",
                "core_topics": ["startups", "dinero"],
                "retention_analysis": "retuvo",
                "growth_driver": "ganó suscriptores",
            },
            "performance": video["metrics"],
            "analytics": video["analytics"],
        }

    monkeypatch.setattr(yh.YouTubeHistoricalExtractor, "fetch_youtube_analytics", _analytics)
    monkeypatch.setattr(yh.YouTubeHistoricalExtractor, "fetch_retention_curve", _curve)
    monkeypatch.setattr(yh.YouTubeHistoricalExtractor, "analyze_video", _analyze)
    monkeypatch.setattr(yh, "labeling_available", lambda: (True, ""))

    ext = yh.YouTubeHistoricalExtractor(None)
    result = asyncio.run(ext.process_historical_shorts("local", "UC1", "token", max_videos=5))

    assert result["processed"] == 1
    assert result["metrics_refreshed"] == 1
    assert result["creator_self"]["shorts_with_retention"] == 1
    assert result["creator_self"]["median_retention"] == pytest.approx(64.5)
    hooks = [row for row in result["creator_self"]["signals"] if row["hook_type"] == "question"]
    assert hooks[0]["avg_retention_pct"] == pytest.approx(64.5)
    row = conn.execute(
        "SELECT view_count, average_view_percentage, hook_type, core_topics, privacy_status "
        "FROM youtube_shorts WHERE video_id='vid1'"
    ).fetchone()
    assert row == (1000, 64.5, "question", "startups,dinero", "public")
    assert pending_label_ids(conn, "local", ["vid1"]) == []


def test_rerun_refreshes_views_without_relabeling(conn, monkeypatch):
    conn.execute(
        "INSERT INTO youtube_shorts (video_id, user_id, title, duration_seconds, view_count, "
        "like_count, comment_count, average_view_percentage, hook_type, llm_analysis, privacy_status) "
        "VALUES ('vid1','local','Short real',30,100,1,0,40.0,'story','{\"hook_type\":\"story\"}','public')"
    )
    conn.commit()
    monkeypatch.setattr(yh.googleapiclient.discovery, "build", lambda *a, **k: _YouTube())

    async def _analytics(self, creds, channel_id, video_ids):
        return {"vid1": {"averageViewPercentage": 64.5}}

    calls = {"n": 0}

    async def _analyze(self, video):
        calls["n"] += 1
        return None

    async def _curve(self, creds, channel_id, video_id):
        return []

    monkeypatch.setattr(yh.YouTubeHistoricalExtractor, "fetch_youtube_analytics", _analytics)
    monkeypatch.setattr(yh.YouTubeHistoricalExtractor, "fetch_retention_curve", _curve)
    monkeypatch.setattr(yh.YouTubeHistoricalExtractor, "analyze_video", _analyze)
    monkeypatch.setattr(yh, "labeling_available", lambda: (True, ""))

    ext = yh.YouTubeHistoricalExtractor(None)
    result = asyncio.run(ext.process_historical_shorts("local", "UC1", "token"))
    assert calls["n"] == 0
    assert result["processed"] == 0
    assert result["metrics_refreshed"] == 1
    stored = conn.execute(
        "SELECT view_count, average_view_percentage, hook_type FROM youtube_shorts WHERE video_id='vid1'"
    ).fetchone()
    assert stored == (1000, 64.5, "story")
    assert result["creator_self"]["median_retention"] == pytest.approx(64.5)


def test_captions_are_tried_before_parakeet(monkeypatch):
    class _Snippet:
        text = "caption real"

    class _Api:
        def fetch(self, video_id, languages=None):
            assert video_id == "abc"
            return [_Snippet()]

    monkeypatch.setattr(yh, "YouTubeTranscriptApi", _Api)
    called = {"n": 0}

    async def _fallback(self, video_id):
        called["n"] += 1
        return "no deberia"

    monkeypatch.setattr(yh.YouTubeHistoricalExtractor, "_transcribe_fallback", _fallback)
    ext = yh.YouTubeHistoricalExtractor(None)
    text, source = asyncio.run(ext.fetch_transcript("abc"))
    assert text == "caption real"
    assert source == "youtube_api"
    assert called["n"] == 0


def test_caption_failure_uses_nvidia_source(monkeypatch):
    class _Api:
        def fetch(self, video_id, languages=None):
            raise RuntimeError("no captions")

    monkeypatch.setattr(yh, "YouTubeTranscriptApi", _Api)

    async def _fallback(self, video_id):
        assert video_id == "abc"
        return "texto parakeet"

    monkeypatch.setattr(yh.YouTubeHistoricalExtractor, "_transcribe_fallback", _fallback)
    ext = yh.YouTubeHistoricalExtractor(None)
    text, source = asyncio.run(ext.fetch_transcript("abc"))
    assert text == "texto parakeet"
    assert source == "nvidia_parakeet"
