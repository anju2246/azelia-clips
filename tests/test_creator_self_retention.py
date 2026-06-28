"""T6 — CREATOR SELF retention-aware + atribución de clips confirmados."""
import json

import pytest

import server.routes.analytics as analytics
import packages.clips.curation.signal_hints as sh
from packages.core.services.creator_self import compute_creator_self_signals
from packages.clips.curation.signal_hints import build_signal_addendum
from packages.clips.curation.models import CurationConfig


@pytest.fixture
def conn(tmp_path, monkeypatch):
    db_path = tmp_path / "youtube_shorts.db"
    monkeypatch.setattr(analytics, "YT_DB_PATH", db_path)
    monkeypatch.setattr(sh, "YT_DB_PATH", str(db_path))
    c = analytics._get_yt_db()
    yield c, str(db_path)
    c.close()


def _short(conn, vid, hook, dur, retention, views=100, likes=10, comments=2):
    conn.execute(
        "INSERT INTO youtube_shorts (video_id, user_id, hook_type, duration_seconds, "
        "average_view_percentage, view_count, like_count, comment_count) "
        "VALUES (?, 'local', ?, ?, ?, ?, ?, ?)",
        (vid, hook, dur, retention, views, likes, comments),
    )
    conn.commit()


def _signal(conn, **w):
    q = "SELECT performance_premium, avg_retention_pct FROM creator_signals WHERE signal_type='creator_self'"
    cond = " AND " + " AND ".join(f"{k}=?" for k in w) if w else ""
    return conn.execute(q + cond, tuple(w.values())).fetchone()


def test_retention_weighted_premium(conn):
    c, _ = conn
    _short(c, "v1", "question", 20, 80.0)
    _short(c, "v2", "question", 22, 80.0)
    _short(c, "v3", "story", 20, 40.0)
    _short(c, "v4", "story", 25, 40.0)
    res = compute_creator_self_signals(c)
    assert res["written"] >= 2
    q = _signal(c, hook_type="question")
    s = _signal(c, hook_type="story")
    assert q[0] > 1.0          # question supera la mediana de retención
    assert s[0] < 1.0          # story por debajo
    assert q[1] == pytest.approx(80.0, abs=0.1)   # avg_retention_pct poblado


def test_falls_back_without_retention(conn):
    c, _ = conn
    # sin retención (NULL) pero con engagement
    _short(c, "v1", "question", 20, None, views=100, likes=20, comments=5)
    _short(c, "v2", "story", 20, None, views=100, likes=2, comments=0)
    res = compute_creator_self_signals(c)  # no debe crashear
    assert res["median_retention"] is None
    q = _signal(c, hook_type="question")
    assert q[0] > 1.0          # premium por engagement
    assert q[1] is None        # sin retención


def test_confirmed_clip_attribution(conn):
    c, _ = conn
    _short(c, "v1", "question", 20, 75.0)
    # clip confirmado con categoría 'startups' apuntando a v1
    c.execute(
        "INSERT INTO clip_links (user_id, episode_id, clip_start, clip_end, "
        "clip_attrs_json, video_id, status) VALUES "
        "('local','ep1',0,20,?, 'v1','confirmed')",
        (json.dumps({"category": "startups"}),),
    )
    c.commit()
    compute_creator_self_signals(c)
    topic = _signal(c, topic_tag="startups")
    assert topic is not None              # el atributo del clip se atribuyó al video real
    assert topic[1] == pytest.approx(75.0, abs=0.1)


def test_creator_hints_mention_retention(conn):
    c, db_path = conn
    _short(c, "v1", "question", 20, 82.0)
    _short(c, "v2", "story", 20, 40.0)
    compute_creator_self_signals(c)
    cfg = CurationConfig(language="es")
    addendum = build_signal_addendum(cfg, db_path=db_path)
    assert "CREATOR SELF" in addendum
    assert "retiene" in addendum   # los hints mencionan retención
