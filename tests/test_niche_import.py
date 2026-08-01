"""T2 — Importador de señales niche (resultados de PodFinder → DB local)."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server.routes.analytics as analytics
from packages.core.services.niche_import import import_niche_signals

FIXT = Path(__file__).parent / "fixtures" / "niche"
SIGNALS = FIXT / "ic_signals_synthetic.json"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(analytics, "YT_DB_PATH", tmp_path / "youtube_shorts.db")
    c = analytics._get_yt_db()
    yield c
    c.close()


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_import_loads_signals_and_baselines(conn):
    res = import_niche_signals(conn, SIGNALS)
    n_sig = len(json.load(open(SIGNALS)))
    assert res["signals_imported"] == n_sig
    assert res["baselines_imported"] == 4
    assert _count(conn, "niche_signals") == n_sig
    assert _count(conn, "niche_baselines") == 4

    # pattern → pattern_json, campos mapeados
    row = conn.execute(
        "SELECT pattern_json, performance_premium, source_type, metric_type "
        "FROM niche_signals WHERE signal_type='clip_hook' LIMIT 1"
    ).fetchone()
    assert row is not None
    assert "hook_type" in row[0]  # pattern_json contiene el dict serializado
    assert row[1] is not None
    assert row[2] == "podintel_public"
    assert row[3] in ("views", "engagement_rate")


def test_import_idempotent_no_duplicates(conn):
    import_niche_signals(conn, SIGNALS)
    n1 = _count(conn, "niche_signals")
    b1 = _count(conn, "niche_baselines")
    import_niche_signals(conn, SIGNALS)  # otra vez
    assert _count(conn, "niche_signals") == n1
    assert _count(conn, "niche_baselines") == b1


def test_malformed_record_skipped(conn, tmp_path):
    bad = tmp_path / "ic_signals_bad.json"
    json.dump(
        [
            {"signal_type": "clip_hook", "language": "es", "pattern": {"hook_type": "x"},
             "metric_type": "views", "metric_value": 1.0, "performance_premium": 1.1,
             "sample_size": 5, "confidence": 0.5, "source_type": "podintel_public"},
            "no soy un dict",
            {"no_signal_type": True},
        ],
        open(bad, "w"),
    )
    res = import_niche_signals(conn, bad)
    assert res["signals_imported"] == 1
    assert res["skipped"] >= 2


def test_missing_path_errors(conn, tmp_path):
    with pytest.raises(FileNotFoundError):
        import_niche_signals(conn, tmp_path / "no_existe.json")


def test_endpoint_imports_and_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(analytics, "YT_DB_PATH", tmp_path / "youtube_shorts.db")
    from server.app import app

    client = TestClient(app)
    r = client.post("/api/analytics/niche/import", json={"path": str(SIGNALS)})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["signals_imported"] >= 10
    assert data["baselines_imported"] == 4
    assert "skipped" in data


def test_endpoint_missing_path_404(tmp_path, monkeypatch):
    monkeypatch.setattr(analytics, "YT_DB_PATH", tmp_path / "youtube_shorts.db")
    from server.app import app

    client = TestClient(app)
    r = client.post(
        "/api/analytics/niche/import", json={"path": str(tmp_path / "nope.json")}
    )
    assert r.status_code == 404
