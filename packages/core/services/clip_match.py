"""Vínculo clip generado ↔ video subido a YouTube (auto-match + confirmación).

Heurística determinista y sin red: similitud de título/caption + proximidad de
duración. El auto-match NUNCA confirma solo — deja candidatos `suggested` que el
usuario confirma/rechaza. Al confirmar, los atributos del clip (hook/categoría/…)
quedan atribuidos al desempeño real del video (retención/engagement).
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import List, Optional

# Pesos y umbrales (constantes nombradas, no mágicos).
TITLE_WEIGHT = 0.7
DURATION_WEIGHT = 0.3
DURATION_EXACT_TOLERANCE_S = 3.0   # |Δdur| ≤ esto ⇒ proximidad 1.0
DURATION_MAX_DELTA_S = 30.0        # más allá ⇒ proximidad 0.0
TOP_K_PER_CLIP = 3
MIN_CONFIDENCE = 0.15              # por debajo, no se sugiere

_EMOJI_AND_PUNCT = re.compile(r"[^\w\sáéíóúñü]", re.UNICODE)
_WS = re.compile(r"\s+")


def _normalize(text: Optional[str]) -> str:
    if not text:
        return ""
    t = text.lower()
    t = _EMOJI_AND_PUNCT.sub(" ", t)
    return _WS.sub(" ", t).strip()


def title_similarity(a: Optional[str], b: Optional[str]) -> float:
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def duration_proximity(clip_dur: float, short_dur: float) -> float:
    if not short_dur or short_dur <= 0:
        return 0.0
    delta = abs(float(clip_dur) - float(short_dur))
    if delta <= DURATION_EXACT_TOLERANCE_S:
        return 1.0
    if delta >= DURATION_MAX_DELTA_S:
        return 0.0
    # lineal entre tolerancia y max
    span = DURATION_MAX_DELTA_S - DURATION_EXACT_TOLERANCE_S
    return max(0.0, 1.0 - (delta - DURATION_EXACT_TOLERANCE_S) / span)


def _clip_duration(clip: dict) -> float:
    if clip.get("duration") is not None:
        return float(clip["duration"])
    return float(clip.get("end_time", 0) or 0) - float(clip.get("start_time", 0) or 0)


def combined_score(clip: dict, short: dict) -> tuple[float, str]:
    """Score 0–1 + método dominante para un par (clip, short)."""
    title_sim = title_similarity(clip.get("title"), short.get("title"))
    caption_sim = title_similarity(clip.get("social_caption"), short.get("title"))
    text_sim = max(title_sim, caption_sim)
    text_method = "title" if title_sim >= caption_sim else "caption"
    dur_prox = duration_proximity(_clip_duration(clip), short.get("duration_seconds", 0))
    score = TITLE_WEIGHT * text_sim + DURATION_WEIGHT * dur_prox
    if text_sim == 0.0 and dur_prox > 0:
        method = "duration"
    elif dur_prox > 0 and text_sim > 0:
        method = "combined"
    else:
        method = text_method
    return round(score, 4), method


def _clip_attrs(clip: dict) -> str:
    return json.dumps(
        {
            "category": clip.get("category"),
            "suggested_hashtags": clip.get("suggested_hashtags"),
            "caption_hashtags": clip.get("caption_hashtags"),
            "virality_score": clip.get("virality_score"),
            "summary": clip.get("summary"),
        },
        ensure_ascii=False,
    )


def suggest_links(
    conn: sqlite3.Connection,
    clips: List[dict],
    shorts: List[dict],
    episode_id: str,
    user_id: str = "local",
) -> List[dict]:
    """Genera candidatos `suggested` para cada clip contra los shorts.

    Idempotente por (user_id, episode_id, clip_start, clip_end): re-sugerir
    reemplaza los candidatos del clip. Devuelve las filas sugeridas (dicts).
    """
    now = datetime.now(timezone.utc).isoformat()
    out: List[dict] = []
    for clip in clips:
        start = float(clip.get("start_time", 0) or 0)
        end = float(clip.get("end_time", 0) or 0)
        dur = _clip_duration(clip)
        attrs = _clip_attrs(clip)

        scored = []
        for short in shorts:
            score, method = combined_score(clip, short)
            if score >= MIN_CONFIDENCE:
                scored.append((score, method, short))
        scored.sort(key=lambda x: x[0], reverse=True)
        scored = scored[:TOP_K_PER_CLIP]

        # Reemplazar candidatos previos NO confirmados de este clip.
        conn.execute(
            "DELETE FROM clip_links WHERE user_id=? AND episode_id=? AND "
            "clip_start=? AND clip_end=? AND status='suggested'",
            (user_id, episode_id, start, end),
        )
        for score, method, short in scored:
            conn.execute(
                """
                INSERT OR IGNORE INTO clip_links
                  (user_id, episode_id, clip_title, clip_caption, clip_start,
                   clip_end, clip_duration, clip_attrs_json, video_id,
                   match_confidence, match_method, status, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,'suggested',?,?)
                """,
                (
                    user_id, episode_id, clip.get("title"), clip.get("social_caption"),
                    start, end, dur, attrs, short.get("video_id"),
                    score, method, now, now,
                ),
            )
            out.append({
                "episode_id": episode_id,
                "clip_title": clip.get("title"),
                "video_id": short.get("video_id"),
                "match_confidence": score,
                "match_method": method,
                "status": "suggested",
            })
    conn.commit()
    out.sort(key=lambda r: r["match_confidence"], reverse=True)
    return out


def confirm_link(
    conn: sqlite3.Connection, link_id: int, video_id: Optional[str], user_id: str = "local"
) -> Optional[dict]:
    """Confirma un link. Fija video_id (si se pasa) y status='confirmed'.
    Si otro link confirmado tenía ese video_id, lo reabre a 'suggested'.
    Devuelve el link confirmado o None si no existe.
    """
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute(
        "SELECT id, video_id FROM clip_links WHERE id=? AND user_id=?",
        (link_id, user_id),
    ).fetchone()
    if not row:
        return None
    chosen_video = video_id or row[1]
    if chosen_video:
        # El último confirmado gana; el previo sobre el mismo video vuelve a suggested.
        conn.execute(
            "UPDATE clip_links SET status='suggested', updated_at=? "
            "WHERE user_id=? AND video_id=? AND status='confirmed' AND id<>?",
            (now, user_id, chosen_video, link_id),
        )
    conn.execute(
        "UPDATE clip_links SET status='confirmed', video_id=?, updated_at=? WHERE id=?",
        (chosen_video, now, link_id),
    )
    conn.commit()
    r = conn.execute(
        "SELECT id, episode_id, clip_title, video_id, match_confidence, status "
        "FROM clip_links WHERE id=?",
        (link_id,),
    ).fetchone()
    return {
        "id": r[0], "episode_id": r[1], "clip_title": r[2],
        "video_id": r[3], "match_confidence": r[4], "status": r[5],
    }


def reject_link(conn: sqlite3.Connection, link_id: int, user_id: str = "local") -> bool:
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "UPDATE clip_links SET status='rejected', updated_at=? WHERE id=? AND user_id=?",
        (now, link_id, user_id),
    )
    conn.commit()
    return cur.rowcount > 0
