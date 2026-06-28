"""CREATOR SELF — señales del propio creador ponderadas por retención real.

Agregación determinista (sin LLM, sin red) sobre los datos propios del creador:
sus YouTube Shorts (retención + engagement) y los clips confirmados
(`clip_links`) que atribuyen los atributos del clip al desempeño real del video.

NO es un port de la metodología de PodFinder (esa capa se IMPORTA). Esto es la
inteligencia propia: "qué le funciona a ESTE creador", con la retención como
métrica primaria y el engagement como respaldo cuando no hay retención.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Buckets de duración (mismos cortes que usa el resto del sistema).
_DURATION_BUCKETS = [("0-15s", 0, 15), ("15-30s", 15, 30), ("30-45s", 30, 45), ("45-60s", 45, 60)]
CONFIDENCE_FULL_N = 10  # tamaño de muestra para confidence = 1.0


def duration_bucket(seconds: float) -> str:
    s = seconds or 0
    for label, lo, hi in _DURATION_BUCKETS:
        if lo <= s < hi:
            return label
    return "60s+"


def _engagement(views, likes, comments) -> float:
    views = views or 0
    if views <= 0:
        return 0.0
    return ((likes or 0) + (comments or 0)) / views


def _mean(xs):
    return statistics.mean(xs) if xs else None


def compute_creator_self_signals(conn: sqlite3.Connection, user_id: str = "local") -> dict:
    """Recalcula las señales CREATOR SELF (signal_type='creator_self') desde
    los shorts + clips confirmados. Idempotente: borra las previas del usuario
    y reescribe. Devuelve {written, median_retention}.
    """
    # Solo contenido PÚBLICO. Los unlisted/private (cortes en bruto, episodios
    # completos, archivos de trabajo) no representan lo que ve la audiencia, así
    # que no deben sesgar las señales. NULL = privacidad aún no backfilleada ⇒
    # se incluye para no regresionar instalaciones sin ese dato.
    rows = conn.execute(
        "SELECT video_id, hook_type, emotional_charge, duration_seconds, "
        "average_view_percentage, view_count, like_count, comment_count, core_topics "
        "FROM youtube_shorts WHERE user_id=? "
        "AND (privacy_status IS NULL OR privacy_status='public')",
        (user_id,),
    ).fetchall()

    recs = []
    for vid, hook, emotion, dur, avp, views, likes, comments, core_topics in rows:
        # core_topics: lista separada por comas, viene de la clasificación
        # automática del short (transcript → LLM). Atribuye tema al desempeño real.
        topics = [t.strip() for t in (core_topics or "").split(",") if t.strip()]
        recs.append({
            "hook_type": hook,
            "emotional_charge": emotion,
            "duration_bucket": duration_bucket(dur or 0),
            "retention": avp,
            "engagement": _engagement(views, likes, comments),
            "topics": topics,
        })

    rets = [r["retention"] for r in recs if r["retention"] is not None]
    median_ret = statistics.median(rets) if rets else None
    engs = [r["engagement"] for r in recs if r["engagement"]]
    median_eng = statistics.median(engs) if engs else None

    # Agrupar por hook_type, emotional_charge, duration_bucket y tema.
    groups: dict[tuple, list] = defaultdict(list)
    for r in recs:
        if r["hook_type"]:
            groups[("hook", r["hook_type"])].append(r)
        if r["emotional_charge"]:
            groups[("emotion", r["emotional_charge"])].append(r)
        if r["duration_bucket"]:
            groups[("duration", r["duration_bucket"])].append(r)
        for topic in r["topics"]:
            groups[("topic", topic)].append(r)

    now = datetime.now(timezone.utc)
    period = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"

    conn.execute(
        "DELETE FROM creator_signals WHERE user_id=? AND signal_type='creator_self'",
        (user_id,),
    )

    written = 0
    for (kind, val), members in groups.items():
        grp_ret = [m["retention"] for m in members if m["retention"] is not None]
        avg_ret = _mean(grp_ret)
        avg_eng = _mean([m["engagement"] for m in members if m["engagement"]])

        if avg_ret is not None and median_ret:
            premium = avg_ret / median_ret
        elif avg_eng is not None and median_eng:
            premium = avg_eng / median_eng
        else:
            premium = 1.0

        confidence = min(1.0, len(members) / CONFIDENCE_FULL_N)
        conn.execute(
            """
            INSERT INTO creator_signals
              (user_id, signal_type, hook_type, emotional_charge, duration_bucket, topic_tag,
               performance_premium, confidence, sample_size, avg_retention_pct, period)
            VALUES (?, 'creator_self', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                val if kind == "hook" else None,
                val if kind == "emotion" else None,
                val if kind == "duration" else None,
                val if kind == "topic" else None,
                round(premium, 4),
                round(confidence, 4),
                len(members),
                round(avg_ret, 2) if avg_ret is not None else None,
                period,
            ),
        )
        written += 1

    conn.commit()
    return {"written": written, "median_retention": median_ret}
