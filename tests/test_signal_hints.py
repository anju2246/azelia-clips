"""T3 — signal_hints (CREATOR SELF + NICHE) e inyección a finder/critic/ranker."""
from pathlib import Path

import pytest

import server.routes.analytics as analytics
import packages.clips.curation.signal_hints as sh
from packages.clips.curation.signal_hints import build_signal_addendum
from packages.core.services.niche_import import import_niche_signals
from packages.clips.curation.models import CurationConfig

FIXT = Path(__file__).parent / "fixtures" / "niche"
SIGNALS = FIXT / "ic_signals_slice.json"


@pytest.fixture
def db(tmp_path, monkeypatch):
    """DB temporal con niche importado; signal_hints apunta ahí."""
    db_path = tmp_path / "youtube_shorts.db"
    monkeypatch.setattr(analytics, "YT_DB_PATH", db_path)
    monkeypatch.setattr(sh, "YT_DB_PATH", str(db_path))
    conn = analytics._get_yt_db()
    import_niche_signals(conn, SIGNALS)
    conn.commit()
    yield conn, str(db_path)
    conn.close()


def _es_business_count(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM niche_signals "
        "WHERE LOWER(language)='es' AND LOWER(category)='business'"
    ).fetchone()[0]


def _es_count(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM niche_signals WHERE LOWER(language)='es'"
    ).fetchone()[0]


def _insert_creator_signal(conn):
    conn.execute(
        """INSERT INTO creator_signals
           (user_id, signal_type, hook_type, emotional_charge, duration_bucket,
            topic_tag, performance_premium, confidence, avg_retention_pct)
           VALUES ('local','clip_hook','question','curiosity','15-30s',
                   'startups', 1.6, 0.8, 72.0)""",
    )
    conn.commit()


def test_niche_scoping_filters_by_segment(db):
    conn, db_path = db
    cfg = CurationConfig(language="es", region="CO", content_niche="business")
    hints = sh._fetch_niche_hints(cfg, conn)
    expected = _es_business_count(conn)
    if expected > 0:
        assert len(hints) == min(expected, sh.NICHE_HINTS_MAX)
    assert all(isinstance(h, str) for h in hints)


def test_niche_fallback_to_language_when_no_category(db):
    conn, db_path = db
    cfg = CurationConfig(language="es", content_niche="categoria_inexistente")
    hints = sh._fetch_niche_hints(cfg, conn)
    assert len(hints) == min(_es_count(conn), sh.NICHE_HINTS_MAX)
    assert len(hints) > 0


def test_creator_self_precedes_niche(db):
    conn, db_path = db
    _insert_creator_signal(conn)
    cfg = CurationConfig(language="es", region="CO", content_niche="business")
    addendum = build_signal_addendum(cfg, db_path=db_path)
    assert "CREATOR SELF" in addendum
    assert "NICHE SIGNAL" in addendum
    assert addendum.index("CREATOR SELF") < addendum.index("NICHE SIGNAL")
    # la retención del creator aparece en el hint
    assert "retiene 72%" in addendum


def test_empty_when_no_signals(tmp_path, monkeypatch):
    db_path = tmp_path / "empty.db"
    monkeypatch.setattr(analytics, "YT_DB_PATH", db_path)
    conn = analytics._get_yt_db()  # crea tablas vacías
    conn.close()
    cfg = CurationConfig(language="es")
    assert build_signal_addendum(cfg, db_path=str(db_path)) == ""


def test_no_db_returns_empty(tmp_path):
    cfg = CurationConfig(language="es")
    assert build_signal_addendum(cfg, db_path=str(tmp_path / "nope.db")) == ""


# ── Inyección a los agentes ──────────────────────────────────────────────────

def _patch_llm(monkeypatch, module):
    monkeypatch.setattr(module, "get_llm", lambda: object())


def test_finder_prompt_includes_addendum(db, monkeypatch):
    _conn, _db_path = db
    import packages.clips.curation.agents.finder as finder_mod
    _patch_llm(monkeypatch, finder_mod)
    agent = finder_mod.FinderAgent()
    cfg = CurationConfig(language="es", region="CO", content_niche="business")
    prompt = agent._build_system_prompt(cfg, 15, 90)
    assert "NICHE SIGNAL" in prompt


def test_critic_prompt_includes_addendum(db, monkeypatch):
    _conn, _db_path = db
    import packages.clips.curation.agents.critic as critic_mod
    _patch_llm(monkeypatch, critic_mod)
    agent = critic_mod.CriticAgent()
    cfg = CurationConfig(language="es", region="CO", content_niche="business")
    prompt = agent._build_system_prompt(cfg, 15, 90, "")
    assert "NICHE SIGNAL" in prompt


def test_ranker_prompt_includes_addendum(db, monkeypatch):
    _conn, _db_path = db
    import packages.clips.curation.agents.ranker as ranker_mod
    _patch_llm(monkeypatch, ranker_mod)
    agent = ranker_mod.RankerAgent()
    cfg = CurationConfig(language="es", region="CO", content_niche="business")
    addendum = agent._build_ranker_addendum(cfg)
    assert "NICHE SIGNAL" in addendum
