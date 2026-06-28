"""Clip Performance Intelligence — builder de hints para los agentes de curación.

Dos capas, leídas de la SQLite local (la misma de analytics/ranker):
  - CREATOR SELF: `creator_signals` — patrones que le funcionan al propio creador
    (incluida retención real). Tienen PRECEDENCIA.
  - NICHE: `niche_signals` — resultados ya computados por PodFinder (podintel_public),
    scopeados por idioma/región/categoría del perfil.

Builder Python puro y testeable: lee la DB vía un único punto (`YT_DB_PATH`,
monkeypatcheable en tests). Sin red. Toda ausencia de señales ⇒ string vacío.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from typing import List, Optional

logger = logging.getLogger(__name__)

# Misma DB que usa el ranker/analytics (repo server/data/youtube_shorts.db).
# Tests la sobreescriben por monkeypatch.
YT_DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "server", "data", "youtube_shorts.db",
)

NICHE_HINTS_MAX = 8
CREATOR_HINTS_MAX = 8
# region viene como ISO 3166-1 alpha-2 en el perfil; PodFinder usa nombres.
_REGION_CODE_TO_NAME = {"CO": "Colombia", "MX": "Mexico", "US": "USA"}


def _connect(db_path: Optional[str]) -> Optional[sqlite3.Connection]:
    path = db_path or YT_DB_PATH
    if not path or not os.path.exists(path):
        return None
    try:
        return sqlite3.connect(path)
    except Exception:
        return None


def _region_name(config) -> Optional[str]:
    code = (getattr(config, "region", "") or "").strip()
    if not code:
        return None
    return _REGION_CODE_TO_NAME.get(code.upper(), code)


def _category(config) -> Optional[str]:
    niche = (getattr(config, "content_niche", "") or "").strip().lower()
    return niche or None


def _fetch_creator_hints(config, conn: sqlite3.Connection) -> List[str]:
    """Hints CREATOR SELF desde creator_signals (migrado del ranker, + retención)."""
    user_id = getattr(config, "user_cohort_hash", "") or "local"
    try:
        rows = conn.execute(
            """
            SELECT hook_type, emotional_charge, duration_bucket, topic_tag,
                   performance_premium, confidence, avg_retention_pct
            FROM creator_signals
            WHERE user_id = ? AND performance_premium >= 1.0
            ORDER BY performance_premium * confidence DESC
            LIMIT ?
            """,
            (user_id, CREATOR_HINTS_MAX),
        ).fetchall()
    except Exception as e:
        logger.debug("creator_signals fetch skipped: %s", e)
        return []

    hints: List[str] = []
    for hook, emotion, duration, topic, premium, conf, retention in rows:
        bits = []
        if hook:
            bits.append(f"hook '{hook}'")
        if emotion:
            bits.append(f"feel {emotion}")
        if duration:
            bits.append(f"~{duration}")
        if topic:
            bits.append(f"about {topic}")
        if not bits:
            continue
        premium = float(premium or 1.0)
        conf = float(conf or 0.5)
        tail = f"×{premium:.2f}, conf={conf:.2f}"
        if retention is not None:
            tail += f", retiene {float(retention):.0f}%"
        hints.append(f"{' / '.join(bits)} supera tu mediana ({tail})")
    return hints


def _describe_pattern(signal_type: str, pattern_json: Optional[str]) -> str:
    try:
        d = json.loads(pattern_json) if pattern_json else {}
    except Exception:
        d = {}
    if not isinstance(d, dict) or not d:
        return signal_type
    return ", ".join(f"{k}={v}" for k, v in d.items())


def _fetch_niche_hints(config, conn: sqlite3.Connection) -> List[str]:
    """Hints NICHE desde niche_signals, scopeados por idioma→categoría→fallback."""
    language = (getattr(config, "language", "") or "").strip().lower() or None
    category = _category(config)

    def _query(where: str, params: list):
        sql = (
            "SELECT signal_type, pattern_json, metric_type, metric_value, "
            "performance_premium, saturation, confidence, region, category "
            "FROM niche_signals WHERE " + where +
            " ORDER BY (COALESCE(performance_premium,1.0) * "
            "COALESCE(confidence,0.3)) DESC LIMIT ?"
        )
        return conn.execute(sql, params + [NICHE_HINTS_MAX]).fetchall()

    rows = []
    try:
        if language and category:
            rows = _query("LOWER(language)=? AND LOWER(category)=?", [language, category])
        if not rows and language:
            rows = _query("LOWER(language)=?", [language])
        if not rows:
            rows = _query("1=1", [])
    except Exception as e:
        logger.debug("niche_signals fetch skipped: %s", e)
        return []

    hints: List[str] = []
    for stype, pat, metric_type, _mv, premium, saturation, _conf, _region, _cat in rows:
        premium = float(premium or 1.0)
        sat = f", {saturation}" if saturation else ""
        hints.append(
            f"{stype}: {_describe_pattern(stype, pat)} ×{premium:.2f} en {metric_type}{sat}"
        )
    return hints


def _fetch_dropoff_hint(conn: sqlite3.Connection) -> Optional[str]:
    """Resumen de 'dónde se va la gente' desde retention_curves."""
    try:
        rows = conn.execute(
            "SELECT drop_off_ratio FROM retention_curves WHERE drop_off_ratio IS NOT NULL"
        ).fetchall()
    except Exception:
        return None
    vals = [r[0] for r in rows if r[0] is not None]
    if not vals:
        return None
    avg = sum(vals) / len(vals)
    return (
        f"La audiencia suele caer al {avg * 100:.0f}% del clip — "
        "el gancho y el pico deben ir ANTES de ese punto."
    )


def build_signal_addendum(config, db_path: Optional[str] = None) -> str:
    """Bloque de señales (CREATOR SELF + NICHE) para inyectar al system prompt.

    String vacío si no hay DB o no hay señales (degradación elegante).
    """
    conn = _connect(db_path)
    if conn is None:
        return ""
    try:
        creator = _fetch_creator_hints(config, conn)
        niche = _fetch_niche_hints(config, conn)
        dropoff = _fetch_dropoff_hint(conn)
    finally:
        conn.close()

    if not creator and not niche and not dropoff:
        return ""

    parts = ["## Clip Performance Intelligence (señales)"]
    if creator or dropoff:
        parts.append("CREATOR SELF — patrones que TE funcionan (precede sobre NICHE):")
        parts.extend(f"- {h}" for h in creator)
        if dropoff:
            parts.append(f"- {dropoff}")
    if niche:
        parts.append("NICHE SIGNAL — qué rinde en tu nicho (podintel):")
        parts.extend(f"- {h}" for h in niche)
    return "\n".join(parts)
