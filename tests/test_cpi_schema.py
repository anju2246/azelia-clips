"""T1 — Schema de Clip Performance Intelligence.

Verifica que `_get_yt_db()` crea idempotentemente las tablas nuevas
(niche_signals, niche_baselines, retention_curves, clip_links) y añade
`creator_signals.avg_retention_pct` sin perder data existente.
"""
import sqlite3

import pytest

import server.routes.analytics as analytics


@pytest.fixture
def yt_db(tmp_path, monkeypatch):
    """Apunta YT_DB_PATH a una DB temporal."""
    db_path = tmp_path / "youtube_shorts.db"
    monkeypatch.setattr(analytics, "YT_DB_PATH", db_path)
    return db_path


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _tables(conn):
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def test_new_tables_created(yt_db):
    conn = analytics._get_yt_db()
    tables = _tables(conn)
    for t in ("niche_signals", "niche_baselines", "retention_curves", "clip_links"):
        assert t in tables, f"falta tabla {t}"

    # Columnas clave de niche_signals
    cols = _columns(conn, "niche_signals")
    for c in (
        "signal_type", "region", "language", "category", "episode_format",
        "period", "duration_bucket", "pattern_json", "metric_type", "metric_value",
        "performance_premium", "adoption_rate", "saturation", "trend_direction",
        "trend_velocity", "sample_size", "confidence", "source_type", "imported_at",
    ):
        assert c in cols, f"niche_signals sin columna {c}"

    # niche_baselines
    bcols = _columns(conn, "niche_baselines")
    for c in ("region", "language", "category", "platform", "metric_type",
              "p25", "p50", "p75", "p90", "sample_size", "imported_at"):
        assert c in bcols, f"niche_baselines sin columna {c}"

    # retention_curves
    rcols = _columns(conn, "retention_curves")
    for c in ("video_id", "user_id", "curve_json", "drop_off_ratio", "fetched_at"):
        assert c in rcols, f"retention_curves sin columna {c}"

    # clip_links
    lcols = _columns(conn, "clip_links")
    for c in ("id", "user_id", "episode_id", "clip_title", "clip_caption",
              "clip_start", "clip_end", "clip_duration", "clip_attrs_json",
              "video_id", "match_confidence", "match_method", "status",
              "created_at", "updated_at"):
        assert c in lcols, f"clip_links sin columna {c}"
    conn.close()


def test_schema_idempotent(yt_db):
    # Correr dos veces no debe fallar
    c1 = analytics._get_yt_db()
    c1.close()
    c2 = analytics._get_yt_db()
    assert "niche_signals" in _tables(c2)
    c2.close()


def test_creator_signals_gets_retention_column(yt_db):
    conn = analytics._get_yt_db()
    assert "avg_retention_pct" in _columns(conn, "creator_signals")
    conn.close()


def test_niche_signals_dedupe_unique(yt_db):
    """La UNIQUE de niche_signals evita duplicados en re-import."""
    conn = analytics._get_yt_db()
    row = (
        "clip_hook", "Colombia", "es", "business", "interview", "2026-W24",
        None, '{"hook_type":"controversial_statement"}', "views", 1359.8,
        1.25, 0.45, "differentiating", None, None, 21, 0.4, "podintel_public",
        "2026-06-28T00:00:00Z",
    )
    cols = (
        "signal_type, region, language, category, episode_format, period, "
        "duration_bucket, pattern_json, metric_type, metric_value, "
        "performance_premium, adoption_rate, saturation, trend_direction, "
        "trend_velocity, sample_size, confidence, source_type, imported_at"
    )
    ph = ",".join(["?"] * 19)
    sql = f"INSERT OR REPLACE INTO niche_signals ({cols}) VALUES ({ph})"
    conn.execute(sql, row)
    conn.execute(sql, row)  # mismo registro
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM niche_signals").fetchone()[0]
    assert n == 1, f"esperaba 1 fila tras INSERT OR REPLACE duplicado, hay {n}"
    conn.close()
