"""T4 — Fix de bugs del camino histórico + parseo/almacenado de la curva de retención."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import server.routes.analytics as analytics
import packages.core.services.youtube_historical as yh
from packages.core.services.youtube_historical import (
    parse_retention_curve,
    derive_drop_off_ratio,
    store_retention_curve,
    RETENTION_DROP_THRESHOLD,
)

CURVE_JSON = Path(__file__).parent / "fixtures" / "youtube" / "retention_curve_real.json"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(analytics, "YT_DB_PATH", tmp_path / "youtube_shorts.db")
    c = analytics._get_yt_db()
    yield c
    c.close()


def test_extractor_instantiates_without_telemetry_or_jwt(monkeypatch):
    # __init__ llama get_llm(); lo neutralizamos para no requerir proveedor real.
    monkeypatch.setattr(yh, "get_llm", lambda: object())
    ext = yh.YouTubeHistoricalExtractor(None, anthropic_model="claude-haiku-4-5-20251001",
                                        output_language="Spanish")
    assert ext.anthropic_model == "claude-haiku-4-5-20251001"
    assert ext.output_language == "Spanish"


def test_run_historical_sync_has_no_bug_refs():
    """Regresión: el route ya no referencia telemetry_svc ni pasa user_jwt al extractor."""
    src = Path(analytics.__file__).read_text()
    # localizar el cuerpo de _run_historical_sync
    idx = src.index("_run_historical_sync")
    body = src[idx: idx + 1200]
    assert "telemetry_svc" not in body
    assert "user_jwt=" not in body


def test_parse_retention_curve_from_real_json():
    resp = json.load(open(CURVE_JSON))
    curve = parse_retention_curve(resp)
    assert len(curve) == 21
    # ordenada por ratio y con las 3 claves
    assert curve[0]["ratio"] == 0.0
    assert curve[-1]["ratio"] == 1.0
    assert all({"ratio", "audience_watch_ratio", "relative_retention"} <= set(p) for p in curve)
    # mapeo por nombre correcto pese al orden no-trivial de columnas
    assert curve[0]["audience_watch_ratio"] == pytest.approx(1.0, abs=0.01)


def test_drop_off_ratio_derivation():
    resp = json.load(open(CURVE_JSON))
    curve = parse_retention_curve(resp)
    drop = derive_drop_off_ratio(curve, threshold=RETENTION_DROP_THRESHOLD)
    assert drop == pytest.approx(0.55, abs=0.001)


def test_store_curve_idempotent(conn):
    resp = json.load(open(CURVE_JSON))
    curve = parse_retention_curve(resp)
    d1 = store_retention_curve(conn, "vid123", curve)
    d2 = store_retention_curve(conn, "vid123", curve)  # otra vez
    assert d1 == d2
    n = conn.execute(
        "SELECT COUNT(*) FROM retention_curves WHERE video_id='vid123'"
    ).fetchone()[0]
    assert n == 1
    stored = conn.execute(
        "SELECT curve_json, drop_off_ratio FROM retention_curves WHERE video_id='vid123'"
    ).fetchone()
    assert len(json.loads(stored[0])) == 21
    assert stored[1] == pytest.approx(0.55, abs=0.001)


def test_malformed_rows_skipped():
    resp = {
        "columnHeaders": [
            {"name": "elapsedVideoTimeRatio"},
            {"name": "audienceWatchRatio"},
            {"name": "relativeRetentionPerformance"},
        ],
        "rows": [
            [0.0, 1.0, 1.0],
            ["basura"],          # fila corta/ inválida
            [0.5, 0.6, 0.9],
        ],
    }
    curve = parse_retention_curve(resp)
    assert len(curve) == 2  # la fila basura se omitió


def test_fetch_retention_curve_uses_analytics_api(monkeypatch):
    """fetch_retention_curve mockea el cliente y devuelve la curva parseada."""
    import asyncio
    monkeypatch.setattr(yh, "get_llm", lambda: object())
    resp = json.load(open(CURVE_JSON))

    mock_client = MagicMock()
    mock_client.reports().query().execute.return_value = resp
    monkeypatch.setattr(yh.googleapiclient.discovery, "build", lambda *a, **k: mock_client)

    ext = yh.YouTubeHistoricalExtractor(None)
    creds = MagicMock()
    curve = asyncio.run(ext.fetch_retention_curve(creds, "channel1", "vid1"))
    assert len(curve) == 21


def test_one_video_failure_does_not_abort(monkeypatch):
    """Si la API falla para un video, fetch_retention_curve devuelve [] sin lanzar."""
    import asyncio
    monkeypatch.setattr(yh, "get_llm", lambda: object())

    def _boom(*a, **k):
        raise RuntimeError("quota")
    monkeypatch.setattr(yh.googleapiclient.discovery, "build", _boom)

    ext = yh.YouTubeHistoricalExtractor(None)
    curve = asyncio.run(ext.fetch_retention_curve(MagicMock(), "c", "v"))
    assert curve == []
