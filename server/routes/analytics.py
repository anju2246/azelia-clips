"""
Server Routes — Platform Analytics & YouTube OAuth
"""

import glob
import logging
import os
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, Request, UploadFile

from packages.core.auth import User
from packages.core.crypto import decrypt_token, encrypt_token
from server.middleware.auth import require_auth
from server.services import user_settings as user_settings_store

logger = logging.getLogger(__name__)
router = APIRouter()


def _find_client_secrets() -> str:
    """Auto-discover Google OAuth client_secrets file.
    Searches in private/ first (gitignored), then project root.
    Supports Google's long filenames like 'client_secret_1234...json'.
    """
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    search_dirs = [
        os.path.join(project_root, "private"),
        project_root,
    ]
    patterns = ["client_secret*.json", "client_secrets.json"]

    for d in search_dirs:
        for pattern in patterns:
            matches = glob.glob(os.path.join(d, pattern))
            if matches:
                return matches[0]

    raise HTTPException(
        status_code=500,
        detail="Missing client_secrets.json. Download from Google Cloud Console and place in private/ folder.",
    )


# ─── Personal Intelligence Insights ─────────────────────────────────────────


@router.get("/analytics/insights")
async def get_analytics_insights(user: User = Depends(require_auth)):
    """
    Aggregate insights from the local job store for Personal Intelligence.
    Returns stats about processed episodes and generated clips.
    """
    from server.workers.job_store import get_job_store

    store = get_job_store()

    try:
        # Query all completed jobs from SQLite
        import sqlite3 as _sqlite3

        conn = _sqlite3.connect(store.db_path)
        cursor = conn.execute("""
            SELECT
                COUNT(*) as total_jobs,
                SUM(clips_generated) as total_clips,
                COUNT(DISTINCT episode_id) as total_episodes,
                AVG(clips_generated) as avg_clips_per_job
            FROM jobs
            WHERE status = 'completed'
        """)
        row = cursor.fetchone()

        total_jobs = row[0] if row else 0
        total_clips = row[1] or 0
        total_episodes = row[2] or 0
        avg_clips = row[3] or 0

        if total_clips == 0:
            return {
                "total_clips": 0,
                "total_episodes": 0,
                "average_score": 0,
                "top_categories": {},
                "top_hook_types": {},
                "avg_duration": 0,
            }

        return {
            "total_clips": total_clips,
            "total_episodes": total_episodes,
            "total_jobs": total_jobs,
            "average_score": 0,  # Will be populated when virality scoring is persisted
            "top_categories": {},  # Will be populated from ic_telemetry_events
            "top_hook_types": {},  # Will be populated from ic_telemetry_events
            "avg_duration": 0,  # Will be populated from clip metadata
            "avg_clips_per_episode": round(avg_clips, 1),
        }
    except Exception:
        # Table might not exist yet (first run)
        return {
            "total_clips": 0,
            "total_episodes": 0,
            "average_score": 0,
            "top_categories": {},
            "top_hook_types": {},
            "avg_duration": 0,
        }


# ─── YouTube Shorts Sync & Insights ─────────────────────────────────────────

import sqlite3
from pathlib import Path

YT_DB_PATH = Path(__file__).parent.parent / "data" / "youtube_shorts.db"


def _get_yt_db():
    """Get or create the YouTube shorts database with multi-user support."""
    YT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(YT_DB_PATH))

    # ── Migrate single-PK table to composite PK (video_id, user_id) ──
    # Check if old single-PK table exists and migrate it transparently
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='youtube_shorts'"
    ).fetchone()
    if row and "PRIMARY KEY (video_id, user_id)" not in row[0]:
        conn.execute("ALTER TABLE youtube_shorts RENAME TO youtube_shorts_old")
        conn.execute("""
            CREATE TABLE youtube_shorts (
                video_id TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT '__legacy__',
                title TEXT,
                published_at TEXT,
                duration_seconds INTEGER,
                view_count INTEGER DEFAULT 0,
                like_count INTEGER DEFAULT 0,
                comment_count INTEGER DEFAULT 0,
                channel_name TEXT,
                channel_id TEXT,
                thumbnail_url TEXT,
                synced_at TEXT,
                average_view_duration REAL,
                average_view_percentage REAL,
                shares_count INTEGER DEFAULT 0,
                subscribers_gained INTEGER DEFAULT 0,
                subscribers_lost INTEGER DEFAULT 0,
                estimated_minutes_watched REAL,
                hook_type TEXT,
                emotional_charge TEXT,
                core_topics TEXT,
                llm_analysis TEXT,
                PRIMARY KEY (video_id, user_id)
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO youtube_shorts
            SELECT video_id, COALESCE(user_id, '__legacy__'), title, published_at,
                   duration_seconds, view_count, like_count, comment_count,
                   channel_name, channel_id, thumbnail_url, synced_at,
                   NULL, NULL, 0, 0, 0, NULL, NULL, NULL, NULL, NULL
            FROM youtube_shorts_old
        """)
        conn.execute("DROP TABLE youtube_shorts_old")
        conn.commit()
    elif not row:
        conn.execute("""
            CREATE TABLE youtube_shorts (
                video_id TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT '__legacy__',
                title TEXT,
                published_at TEXT,
                duration_seconds INTEGER,
                view_count INTEGER DEFAULT 0,
                like_count INTEGER DEFAULT 0,
                comment_count INTEGER DEFAULT 0,
                channel_name TEXT,
                channel_id TEXT,
                thumbnail_url TEXT,
                synced_at TEXT,
                average_view_duration REAL,
                average_view_percentage REAL,
                shares_count INTEGER DEFAULT 0,
                subscribers_gained INTEGER DEFAULT 0,
                subscribers_lost INTEGER DEFAULT 0,
                estimated_minutes_watched REAL,
                hook_type TEXT,
                emotional_charge TEXT,
                core_topics TEXT,
                llm_analysis TEXT,
                PRIMARY KEY (video_id, user_id)
            )
        """)

    # ── Multi-user connection store (replaces old youtube_sync_meta) ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS youtube_connections (
            user_id TEXT PRIMARY KEY,
            channel_id TEXT,
            channel_name TEXT,
            refresh_token TEXT,
            last_synced TEXT
        )
    """)
    # Idempotent additions for async sync tracking (safe to re-run)
    for col_def in (
        "channel_thumbnail TEXT",
        "sync_status TEXT",  # 'pending' | 'complete' | 'failed' | NULL
        "sync_started_at TEXT",
        "sync_completed_at TEXT",
        "sync_error TEXT",
        "total_shorts INTEGER DEFAULT 0",
    ):
        try:
            conn.execute(f"ALTER TABLE youtube_connections ADD COLUMN {col_def}")
        except Exception:
            pass  # column already exists
    # Keep legacy table alive for backward compat but don't use it
    conn.execute("""
        CREATE TABLE IF NOT EXISTS youtube_sync_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    return conn


def _get_user_id_from_auth(authorization: str) -> str | None:
    """Extract user_id from a Supabase JWT Authorization header.
    Uses server-side JWT verification via Supabase API (no manual decode).
    """
    if not authorization:
        return None
    try:
        from packages.core.auth import verify_supabase_jwt

        token = authorization.replace("Bearer ", "").strip()
        user = verify_supabase_jwt(token)
        return user.id
    except Exception:
        return None


def _mark_sync_pending(user_id: str, channel_id: str, channel_name: str, channel_thumbnail: str):
    """Write initial sync row so the user sees channel metadata immediately.
    Preserves existing refresh_token if present (Google only returns it on first consent).
    """
    from datetime import datetime

    now = datetime.now(UTC).isoformat()
    uid = user_id or "__legacy__"
    conn = _get_yt_db()
    conn.execute(
        """
        INSERT INTO youtube_connections (
            user_id, channel_id, channel_name, channel_thumbnail,
            sync_status, sync_started_at, sync_error, total_shorts
        )
        VALUES (?, ?, ?, ?, 'pending', ?, NULL, 0)
        ON CONFLICT(user_id) DO UPDATE SET
            channel_id = excluded.channel_id,
            channel_name = excluded.channel_name,
            channel_thumbnail = excluded.channel_thumbnail,
            sync_status = 'pending',
            sync_started_at = excluded.sync_started_at,
            sync_error = NULL
    """,
        (uid, channel_id, channel_name, channel_thumbnail, now),
    )
    conn.commit()
    conn.close()


def _mark_sync_complete(user_id: str, total_shorts: int):
    from datetime import datetime

    now = datetime.now(UTC).isoformat()
    uid = user_id or "__legacy__"
    conn = _get_yt_db()
    conn.execute(
        """
        UPDATE youtube_connections
        SET sync_status = 'complete',
            sync_completed_at = ?,
            total_shorts = ?,
            last_synced = ?,
            sync_error = NULL
        WHERE user_id = ?
    """,
        (now, total_shorts, now, uid),
    )
    conn.commit()
    conn.close()


def _mark_sync_failed(user_id: str, error_msg: str):
    from datetime import datetime

    now = datetime.now(UTC).isoformat()
    uid = user_id or "__legacy__"
    conn = _get_yt_db()
    conn.execute(
        """
        UPDATE youtube_connections
        SET sync_status = 'failed',
            sync_completed_at = ?,
            sync_error = ?
        WHERE user_id = ?
    """,
        (now, (error_msg or "unknown")[:300], uid),
    )
    conn.commit()
    conn.close()


async def _run_full_sync(
    access_token: str, channel_id: str, user_id: str, authorization: str | None
):
    """Background task wrapper around _sync_channel.
    Keeps sync_status row up-to-date regardless of outcome.
    """
    try:
        from server.services.analytics import AnalyticsSync

        analytics = None
        # `authorization` is the user's Supabase bearer header value. We split
        # off the JWT once: AnalyticsSync uses it for Supabase-scoped queries,
        # _sync_channel passes it to telemetry so the Edge Function can attest
        # consent + compute cohort_hash.
        user_jwt = authorization.replace("Bearer ", "").strip() if authorization else None
        if user_jwt:
            try:
                analytics = AnalyticsSync(auth_token=user_jwt)
            except Exception:
                pass
        result = await _sync_channel(
            access_token, channel_id, user_id=user_id, user_jwt=user_jwt, analytics=analytics
        )
        total = int(result.get("total_shorts", 0)) if isinstance(result, dict) else 0
        _mark_sync_complete(user_id, total)
    except Exception as e:
        import logging
        import traceback

        logging.getLogger(__name__).error(
            f"Background YouTube sync failed for user {user_id}: {type(e).__name__}: {e}\n{traceback.format_exc()[:500]}"
        )
        _mark_sync_failed(user_id, f"{type(e).__name__}: {e}")


@router.get("/analytics/youtube/status")
async def get_youtube_status(user: User = Depends(require_auth)):
    """Check if YouTube shorts have been synced (user-scoped)."""
    try:
        user_id = user.id
        conn = _get_yt_db()

        query = "SELECT COUNT(*) FROM youtube_shorts"
        params = ()
        if user_id:
            query += " WHERE user_id = ?"
            params = (user_id,)

        cursor = conn.execute(query, params)
        count = cursor.fetchone()[0]

        # Read from youtube_connections (user-scoped)
        channel_name = None
        last_synced = None
        sync_status = None
        if user_id:
            cursor2 = conn.execute(
                "SELECT channel_name, last_synced, sync_status FROM youtube_connections WHERE user_id = ?",
                (user_id,),
            )
            row2 = cursor2.fetchone()
            if row2:
                channel_name = row2[0]
                last_synced = row2[1]
                sync_status = row2[2]

        conn.close()
        # Note: caller may also want sync_status — see /analytics/youtube/sync-status
        return {
            "connected": count > 0 or channel_name is not None,
            "channel_name": channel_name,
            "total_shorts": count,
            "last_synced": last_synced,
            "sync_status": sync_status,  # 'pending' | 'complete' | 'failed' | None
        }
    except Exception:
        return {"connected": False, "total_shorts": 0}


# ─── Creator signals extraction (Ticket A) ──────────────────────────
# Pulls top-performing shorts from local SQLite, sends to Sonnet for
# pattern extraction, writes anonymous signals to the central IC Cascade
# with source_type='creator_self' and cohort_hash tied to the user.

_CREATOR_SIGNALS_PROMPT = """You are a podcast clip analyst. I'm giving you the titles and performance metrics of a creator's top-performing YouTube Shorts. Your job is to extract structural patterns the Ranker can use for future clips from this creator.

For each short, infer:
- hook_type: one of [question, bold_claim, story, data_point, cliffhanger, comparison, challenge, revelation, number_list, contradiction, other]
- emotional_charge: one of [curious, outraged, inspired, humor, fear, surprise, neutral]
- duration_bucket: one of [0-30s, 30-45s, 45-60s, 60s+]
- has_cta: boolean
- topic_tags: up to 3 concise topic tags, lowercase snake_case

Then synthesize the TOP 5 recurring patterns across the whole batch. Each pattern is one aggregate row.

Return JSON ONLY with this exact shape (no prose, no markdown fences):
{
  "patterns": [
    {
      "signal_type": "clip_hook" | "emotion_pattern" | "duration_pattern" | "topic_trend",
      "hook_type"?: string,
      "emotional_charge"?: string,
      "duration_bucket"?: string,
      "topic_tag"?: string,
      "sample_size": number,
      "performance_premium": number,
      "confidence": number,
      "pattern": object
    }
  ]
}

`performance_premium` = how much more views these clips got vs creator's median (0.0-5.0 range, 1.0=median, >1 is above).
`confidence` = 0.0-1.0 based on how consistent the pattern is across the batch.
`pattern` = the structural fields in a JSON object."""


# Default Anthropic model for Ticket A (classification over shorts metadata).
# Haiku 4.5 handles this task as well as Sonnet and costs ~3x less.
# Users can override via body.model in the POST endpoint — constrained by
# _ALLOWED_ANTHROPIC_MODELS below so an authed user cannot force arbitrary
# (potentially expensive) model IDs onto the server's Anthropic budget.
_CREATOR_SIGNALS_DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# Allowlist of Anthropic models any endpoint in this file may invoke on the
# user's behalf. Protects against someone scripting POSTs with `model=opus...`
# to drain the shared key. Keep this in sync with the frontend modal pickers.
_ALLOWED_ANTHROPIC_MODELS = frozenset(
    {
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-6",
        "claude-opus-4-7",
    }
)


def _resolve_anthropic_model(
    requested: str | None, fallback: str = _CREATOR_SIGNALS_DEFAULT_MODEL
) -> str:
    """Return a model ID from the allowlist; 400 on anything else.

    Accepts None/empty (→ fallback) and exact matches. Rejects everything
    else loudly so an attacker or a stale frontend can't push unknown IDs
    through to Anthropic.
    """
    if not requested:
        return fallback
    chosen = requested.strip()
    if chosen not in _ALLOWED_ANTHROPIC_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported model '{chosen}'. Allowed: {sorted(_ALLOWED_ANTHROPIC_MODELS)}",
        )
    return chosen


def _estimate_extraction_cost(
    num_shorts: int, anthropic_model: str = _CREATOR_SIGNALS_DEFAULT_MODEL
) -> dict:
    """Rough cost estimate for extracting creator signals.

    Pricing per M tokens (as of 2026-04):
      - Haiku 4.5: $1 in / $5 out
      - Sonnet 4.6: $3 in / $15 out
      - Opus 4.7: $15 in / $75 out
    """
    # ~1.5k tokens per short title + stats, plus 4k prompt overhead.
    input_tokens = num_shorts * 1500 + 4000
    # Expected ~2500 output tokens for structured JSON with 5 patterns.
    output_tokens = 2500
    m = anthropic_model.lower()
    if "opus" in m:
        in_rate, out_rate = 15.0, 75.0
    elif "sonnet" in m:
        in_rate, out_rate = 3.0, 15.0
    else:  # haiku / default
        in_rate, out_rate = 1.0, 5.0
    cost = (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
    return {
        "num_shorts": num_shorts,
        "input_tokens_est": input_tokens,
        "output_tokens_est": output_tokens,
        "cost_usd_est": round(cost, 3),
        "model": anthropic_model,
    }


def _creator_signals_url() -> str:
    """URL of the creator-signals Edge Function."""
    from packages.core.config import settings as _s

    return f"{_s.supabase_url.rstrip('/')}/functions/v1/creator-signals"


@router.get("/analytics/youtube/extract-creator-signals/estimate")
async def estimate_creator_signals_cost(
    model: str | None = None,
    user: User = Depends(require_auth),
):
    """v0.1.0: returns empty estimate — feature requires the central IC Cascade
    (Edge Function + Supabase central). Re-introduces in v0.1.1 as 100% local:
    LLM analyzes user's own shorts and writes patterns to
    ~/.azelia/data/youtube_shorts.db, no central calls."""
    return {
        "total_shorts": 0,
        "model_options": {},
        "coming_in": "v0.1.1",
        "note": "Creator-signal extraction goes 100% local in v0.1.1.",
    }
    conn = _get_yt_db()  # noqa — unreachable, kept for v0.1.1 port reference
    cur = conn.execute(
        "SELECT COUNT(*) FROM youtube_shorts WHERE user_id = ?",
        (user.id,),
    )
    total = cur.fetchone()[0]
    conn.close()

    chosen_model = _resolve_anthropic_model(model)
    batch_size = min(30, total)
    est = _estimate_extraction_cost(batch_size, chosen_model)
    est["total_shorts_available"] = total
    est["batch_size"] = batch_size
    # Also return the costs across all available models so the UI can show a picker.
    est["model_options"] = {
        "claude-haiku-4-5-20251001": _estimate_extraction_cost(
            batch_size, "claude-haiku-4-5-20251001"
        )["cost_usd_est"],
        "claude-sonnet-4-6": _estimate_extraction_cost(batch_size, "claude-sonnet-4-6")[
            "cost_usd_est"
        ],
        "claude-opus-4-7": _estimate_extraction_cost(batch_size, "claude-opus-4-7")["cost_usd_est"],
    }
    return est


@router.post("/analytics/youtube/extract-creator-signals")
async def extract_creator_signals(
    request: Request,
    body: dict = Body(default_factory=dict),
    user: User = Depends(require_auth),
):
    """v0.1.0: disabled — required the central IC Cascade. Reintroduces in
    v0.1.1 as a fully local extractor (LLM analyzes shorts, writes patterns
    to ~/.azelia/data/youtube_shorts.db, no Supabase/Edge calls)."""
    raise HTTPException(
        status_code=501,
        detail={
            "status": "coming_soon",
            "message": "Creator-signal extraction goes 100% local in v0.1.1.",
            "version_target": "0.1.1",
        },
    )
    # Original SaaS-era impl below — kept verbatim for v0.1.1 port reference
    """Extract structural patterns from this creator's top shorts and insert
    them as anonymous signals (`source_type='creator_self'`, `cohort_hash`)
    into the central IC Cascade. Feeds the Ranker for the user's future
    pipeline runs plus every other creator in the same niche.

    Body:
      { "batch_size": 30, "confirmed": true }

    Returns:
      { status, signals_created, cost_est, cost_actual?, patterns_summary }
    """
    if not body.get("confirmed"):
        raise HTTPException(status_code=400, detail="confirmed=true is required to run")

    from packages.core.config import settings as app_settings

    api_key = (
        user_settings_store.effective_setting(user.id, "ANTHROPIC_API_KEY")
        or app_settings.anthropic_api_key
    )
    if not api_key or not api_key.startswith("sk-"):
        raise HTTPException(status_code=400, detail="Anthropic API key not configured")

    batch_size = max(5, min(int(body.get("batch_size") or 30), 50))

    # 1. Pull top shorts by views from local SQLite
    conn = _get_yt_db()
    cur = conn.execute(
        """
        SELECT video_id, title, duration_seconds, view_count, like_count, comment_count
        FROM youtube_shorts
        WHERE user_id = ?
        ORDER BY view_count DESC
        LIMIT ?
        """,
        (user.id, batch_size),
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        raise HTTPException(
            status_code=400, detail="No YouTube shorts synced yet. Connect YouTube first."
        )

    shorts_payload = [
        {
            "title": r[1],
            "duration_seconds": r[2],
            "view_count": r[3],
            "like_count": r[4],
            "comment_count": r[5],
        }
        for r in rows
    ]

    # 2. Call Anthropic. Default = Haiku (cheap, good enough for classification).
    #    User can override via body.model; validation is lax — Anthropic will
    #    reject an unknown model ID and we'll surface that 502.
    chosen_model = _resolve_anthropic_model(body.get("model"))
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=api_key)
        user_content = (
            _CREATOR_SIGNALS_PROMPT
            + "\n\nSHORTS BATCH:\n"
            + "\n".join(
                f'{i + 1}. "{s["title"]}" · dur={s["duration_seconds"]}s · views={s["view_count"]} · likes={s["like_count"]}'
                for i, s in enumerate(shorts_payload)
            )
        )
        resp = client.messages.create(
            model=chosen_model,
            max_tokens=3000,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = resp.content[0].text if resp.content else ""
    except Exception as exc:
        logger.exception("Anthropic call failed in pattern extraction")
        raise HTTPException(status_code=502, detail="Anthropic call failed") from exc

    # 3. Parse the JSON reply
    import json as _json
    import re as _re

    cleaned = _re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=_re.MULTILINE).strip()
    try:
        parsed = _json.loads(cleaned)
        patterns = parsed.get("patterns", [])
    except Exception as exc:
        logger.exception("Sonnet returned non-JSON response")
        raise HTTPException(status_code=502, detail="Sonnet returned invalid JSON") from exc

    if not isinstance(patterns, list) or not patterns:
        raise HTTPException(status_code=502, detail="No patterns returned by Sonnet")

    # 4. Build signal rows and insert via service role
    from datetime import datetime

    now = datetime.now(UTC)
    year, week, _ = now.isocalendar()
    period = f"{year}-W{week:02d}"

    # Resolve region/language/category from user's own profile via user JWT.
    from packages.core.taxonomy import normalize_country as _norm_country
    from packages.core.taxonomy import normalize_language as _norm_lang
    from packages.core.taxonomy import normalize_niche as _norm_niche

    profile_region = None
    profile_language = "en"
    profile_category = None
    user_jwt = getattr(request.state, "user_jwt", None) or ""
    try:
        import httpx as _httpx

        pr = _httpx.get(
            f"{app_settings.supabase_url}/rest/v1/profiles",
            params={"id": f"eq.{user.id}", "select": "preferences,content_niche"},
            headers={
                "apikey": app_settings.supabase_key,
                "Authorization": f"Bearer {user_jwt or app_settings.supabase_key}",
            },
            timeout=5,
        )
        if pr.status_code == 200 and pr.json():
            p = pr.json()[0]
            prefs = p.get("preferences") or {}
            profile_region = _norm_country(prefs.get("region")) or None
            profile_language = _norm_lang(prefs.get("language")) or "en"
            profile_category = _norm_niche(p.get("content_niche")) or None
    except Exception:
        pass

    # 4. POST patterns to the creator-signals Edge Function.
    #    The function computes cohort_hash server-side, inserts into ic_signals,
    #    and invalidates the user's LocalIntelligence cache — no service role needed here.
    if not user_jwt:
        raise HTTPException(status_code=401, detail="Missing user token for creator signals")
    if not app_settings.supabase_url:
        raise HTTPException(status_code=500, detail="SUPABASE_URL not configured")

    try:
        import httpx as _httpx2

        fn_resp = _httpx2.post(
            _creator_signals_url(),
            json={
                "patterns": patterns,
                "region": profile_region,
                "language": profile_language,
                "category": profile_category,
                "period": period,
            },
            headers={
                "Authorization": f"Bearer {user_jwt}",
                "apikey": app_settings.supabase_key,
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        if fn_resp.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"creator-signals insert failed: {fn_resp.status_code} {fn_resp.text[:200]}",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("creator-signals Edge Function call failed")
        raise HTTPException(status_code=502, detail="Insert error") from exc

    # 5. Estimated vs actual usage — rate tied to the model actually used.
    usage = getattr(resp, "usage", None)
    actual_cost = None
    if usage:
        in_t = getattr(usage, "input_tokens", 0) or 0
        out_t = getattr(usage, "output_tokens", 0) or 0
        m = chosen_model.lower()
        if "opus" in m:
            in_rate, out_rate = 15.0, 75.0
        elif "sonnet" in m:
            in_rate, out_rate = 3.0, 15.0
        else:
            in_rate, out_rate = 1.0, 5.0
        actual_cost = round((in_t / 1_000_000) * in_rate + (out_t / 1_000_000) * out_rate, 4)

    try:
        signals_created = fn_resp.json().get("signals_created", len(patterns))
    except Exception:
        signals_created = len(patterns)

    return {
        "status": "complete",
        "signals_created": signals_created,
        "batch_size": batch_size,
        "model_used": chosen_model,
        "cost_est": _estimate_extraction_cost(batch_size, chosen_model),
        "cost_actual_usd": actual_cost,
        "patterns_summary": [
            {
                k: v
                for k, v in pat.items()
                if k
                in (
                    "signal_type",
                    "hook_type",
                    "emotional_charge",
                    "duration_bucket",
                    "topic_tag",
                    "confidence",
                )
            }
            for pat in patterns
        ],
    }


@router.get("/analytics/my-content-intelligence")
async def get_my_content_intelligence(
    request: Request,
    user: User = Depends(require_auth),
):
    """v0.1.0: returns empty — depends on creator-signals (disabled). UI gets
    {empty: true, reason: 'feature_disabled'} so it renders the placeholder."""
    return {
        "empty": True,
        "reason": "feature_disabled",
        "coming_in": "v0.1.1",
        "top_hooks": [],
        "retention_patterns": [],
        "best_durations": [],
    }
    # Original impl below — preserved for v0.1.1 port
    """Aggregate the creator's own `ic_signals` (source_type='creator_self').

    These are the patterns the user extracted from THEIR own shorts, using
    THEIR own API tokens, in the Creator Signals flow. The Intelligence
    dashboard needs a place to show them back so the spend makes sense.

    Returns:
      - top_hooks:         best-performing hook_type patterns (by performance_premium × confidence)
      - retention_patterns:signals with retention/engagement angle
      - topic_performance: patterns grouped by topic
      - avoid_patterns:    low-confidence / underperforming patterns (performance_premium < 1)
      - empty state flag   so the UI can prompt a first extraction
    """
    from packages.core.config import settings as app_settings

    user_jwt = getattr(request.state, "user_jwt", None) or ""
    if not user_jwt or not app_settings.supabase_url:
        return {"empty": True, "reason": "unauthenticated"}

    # Fetch via the creator-signals Edge Function — cohort_hash is computed
    # server-side with COHORT_SALT. No service role needed on this server.
    import httpx as _httpx

    try:
        r = _httpx.get(
            _creator_signals_url(),
            headers={
                "Authorization": f"Bearer {user_jwt}",
                "apikey": app_settings.supabase_key,
            },
            timeout=10,
        )
        # 404 means the Edge Function isn't deployed yet — treat as no signals.
        if r.status_code == 404:
            return {"empty": True, "reason": "no_signals_yet"}
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"creator-signals fetch failed: {r.status_code}")
        data = r.json()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("creator-signals fetch failed")
        raise HTTPException(status_code=502, detail="ic_signals fetch error") from exc

    rows = data.get("signals") or []
    if not rows:
        return {"empty": True, "reason": "no_signals_yet"}

    def _score(row: dict) -> float:
        pp = float(row.get("performance_premium") or 1.0)
        conf = float(row.get("confidence") or 0.5)
        return pp * conf

    # top_hooks: best hook_type patterns
    hooks = []
    for row in rows:
        pat = row.get("pattern") or {}
        hook = pat.get("hook_type")
        if not hook:
            continue
        hooks.append(
            {
                "hook_type": hook,
                "emotional_charge": pat.get("emotional_charge"),
                "duration_bucket": row.get("duration_bucket"),
                "performance_premium": float(row.get("performance_premium") or 1.0),
                "confidence": float(row.get("confidence") or 0.5),
                "sample_size": int(row.get("sample_size") or 0),
                "score": round(_score(row), 3),
            }
        )
    hooks.sort(key=lambda x: x["score"], reverse=True)
    top_hooks = hooks[:5]

    # topic_performance: aggregate by pattern.topic
    topics: dict[str, dict] = {}
    for row in rows:
        pat = row.get("pattern") or {}
        topic = pat.get("topic") or pat.get("topic_tag")
        if not topic:
            continue
        entry = topics.setdefault(
            topic, {"topic": topic, "sample_size": 0, "perf_sum": 0.0, "n": 0}
        )
        entry["sample_size"] += int(row.get("sample_size") or 0)
        entry["perf_sum"] += float(row.get("performance_premium") or 1.0)
        entry["n"] += 1
    topic_performance = sorted(
        [
            {
                "topic": t["topic"],
                "avg_performance_premium": round(t["perf_sum"] / max(t["n"], 1), 2),
                "sample_size": t["sample_size"],
            }
            for t in topics.values()
        ],
        key=lambda x: x["avg_performance_premium"],
        reverse=True,
    )[:5]

    # retention_patterns: signals where signal_type relates to retention/engagement
    retention_patterns = [
        {
            "signal_type": row.get("signal_type"),
            "pattern": row.get("pattern"),
            "performance_premium": float(row.get("performance_premium") or 1.0),
            "confidence": float(row.get("confidence") or 0.5),
        }
        for row in rows
        if row.get("signal_type") in ("retention_pattern", "engagement_pattern", "clip_structure")
    ][:5]

    # avoid_patterns: performance_premium < 1 (below this creator's median)
    avoid_patterns = [
        {
            "hook_type": (row.get("pattern") or {}).get("hook_type"),
            "emotional_charge": (row.get("pattern") or {}).get("emotional_charge"),
            "performance_premium": float(row.get("performance_premium") or 1.0),
            "confidence": float(row.get("confidence") or 0.5),
            "sample_size": int(row.get("sample_size") or 0),
        }
        for row in rows
        if float(row.get("performance_premium") or 1.0) < 1.0
    ][:3]

    return {
        "empty": False,
        "signal_count": len(rows),
        "top_hooks": top_hooks,
        "retention_patterns": retention_patterns,
        "topic_performance": topic_performance,
        "avoid_patterns": avoid_patterns,
    }


@router.get("/analytics/youtube/sync-status")
async def get_youtube_sync_status(user: User = Depends(require_auth)):
    """Current YouTube sync state for this user — used by frontend to poll after OAuth.

    Returns one of:
      {status: 'none'}                                    # no connection yet
      {status: 'pending', channel_name, channel_thumbnail, sync_started_at}
      {status: 'complete', channel_name, total_shorts, last_synced, ...}
      {status: 'failed', channel_name, error, ...}
    """
    try:
        conn = _get_yt_db()
        cursor = conn.execute(
            """
            SELECT channel_id, channel_name, channel_thumbnail,
                   sync_status, sync_started_at, sync_completed_at,
                   sync_error, total_shorts, last_synced
            FROM youtube_connections
            WHERE user_id = ?
            """,
            (user.id,),
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return {"status": "none"}
        (
            channel_id,
            channel_name,
            channel_thumbnail,
            sync_status,
            sync_started_at,
            sync_completed_at,
            sync_error,
            total_shorts,
            last_synced,
        ) = row
        return {
            "status": sync_status or ("complete" if last_synced else "none"),
            "channel_id": channel_id,
            "channel_name": channel_name,
            "channel_thumbnail": channel_thumbnail,
            "sync_started_at": sync_started_at,
            "sync_completed_at": sync_completed_at,
            "total_shorts": total_shorts or 0,
            "last_synced": last_synced,
            "error": sync_error,
        }
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning(f"sync-status endpoint error: {type(e).__name__}: {e}")
        return {"status": "none"}


@router.post("/analytics/youtube/sync")
async def sync_youtube_shorts(body: dict = Body(...), user: User = Depends(require_auth)):
    """
    Fetch ALL shorts from the user's YouTube channel using their Google provider token.
    Paginates through all uploads, filters for shorts (<= 60s), and stores locally.
    """
    provider_token = body.get("provider_token")
    if not provider_token:
        raise HTTPException(status_code=400, detail="Missing provider_token")

    import requests

    YT_API = "https://www.googleapis.com/youtube/v3"
    headers = {"Authorization": f"Bearer {provider_token}"}

    # Step 1: Get the channel info and uploads playlist
    channel_res = requests.get(
        f"{YT_API}/channels",
        params={"part": "snippet,contentDetails,statistics", "mine": "true"},
        headers=headers,
    )

    if channel_res.status_code != 200:
        error_detail = channel_res.json().get("error", {}).get("message", "Unknown error")
        raise HTTPException(status_code=400, detail=f"YouTube API error: {error_detail}")

    channels = channel_res.json().get("items", [])
    if not channels:
        raise HTTPException(status_code=404, detail="No YouTube channel found for this account")

    channel = channels[0]
    channel_name = channel["snippet"]["title"]
    channel_id = channel["id"]
    uploads_playlist_id = channel["contentDetails"]["relatedPlaylists"]["uploads"]

    # Step 2: Paginate through ALL uploads
    all_video_ids = []
    next_page = None

    while True:
        params = {
            "part": "snippet",
            "playlistId": uploads_playlist_id,
            "maxResults": 50,
        }
        if next_page:
            params["pageToken"] = next_page

        playlist_res = requests.get(f"{YT_API}/playlistItems", params=params, headers=headers)
        if playlist_res.status_code != 200:
            break

        data = playlist_res.json()
        for item in data.get("items", []):
            video_id = item["snippet"]["resourceId"]["videoId"]
            all_video_ids.append(video_id)

        next_page = data.get("nextPageToken")
        if not next_page:
            break

    if not all_video_ids:
        return {"total_shorts": 0, "channel_name": channel_name}

    # Step 3: Get video details in batches of 50 (API limit)
    shorts = []

    for i in range(0, len(all_video_ids), 50):
        batch = all_video_ids[i : i + 50]
        video_res = requests.get(
            f"{YT_API}/videos",
            params={"part": "snippet,contentDetails,statistics", "id": ",".join(batch)},
            headers=headers,
        )

        if video_res.status_code != 200:
            continue

        for video in video_res.json().get("items", []):
            # Parse ISO 8601 duration (PT1M30S → 90 seconds)
            duration_str = video["contentDetails"]["duration"]
            duration_secs = _parse_iso_duration(duration_str)

            stats = video.get("statistics", {})
            snippet = video["snippet"]
            thumbnails = snippet.get("thumbnails", {})
            thumb_url = thumbnails.get("high", thumbnails.get("default", {})).get("url", "")

            shorts.append(
                {
                    "video_id": video["id"],
                    "title": snippet.get("title", ""),
                    "published_at": snippet.get("publishedAt", ""),
                    "duration_seconds": duration_secs,
                    "view_count": int(stats.get("viewCount", 0)),
                    "like_count": int(stats.get("likeCount", 0)),
                    "comment_count": int(stats.get("commentCount", 0)),
                    "channel_name": channel_name,
                    "channel_id": channel_id,
                    "thumbnail_url": thumb_url,
                }
            )

    # Step 4: Store in SQLite
    conn = _get_yt_db()
    now = datetime.now().isoformat()

    for s in shorts:
        conn.execute(
            """
            INSERT OR REPLACE INTO youtube_shorts
            (video_id, title, published_at, duration_seconds, view_count, like_count,
             comment_count, channel_name, channel_id, thumbnail_url, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                s["video_id"],
                s["title"],
                s["published_at"],
                s["duration_seconds"],
                s["view_count"],
                s["like_count"],
                s["comment_count"],
                s["channel_name"],
                s["channel_id"],
                s["thumbnail_url"],
                now,
            ),
        )

    # Save sync metadata
    # Legacy sync endpoint — store in youtube_connections if user_id available
    # (This endpoint doesn't have user context, so we use a fallback)
    conn.execute(
        """
        INSERT OR REPLACE INTO youtube_connections (user_id, channel_id, channel_name, last_synced)
        VALUES (?, ?, ?, ?)
    """,
        ("__legacy__", channel_id, channel_name, now),
    )
    conn.commit()
    conn.close()

    return {
        "total_shorts": len(shorts),
        "total_videos_scanned": len(all_video_ids),
        "channel_name": channel_name,
    }


@router.post("/analytics/youtube/sync-with-code")
async def sync_youtube_with_code(
    body: dict = Body(...),
    authorization: str = Header(None),
    user: User = Depends(require_auth),
):
    """
    Step 1: Exchange OAuth code for access token, then list available channels.
    Returns the token + list of channels so the user can pick which to sync.
    If channel_id is provided, skip channel selection and sync directly.
    """
    try:
        code = body.get("code")
        redirect_uri = body.get("redirect_uri")
        channel_id = body.get("channel_id")  # Optional: skip picker and sync this channel
        access_token = body.get("access_token")  # Optional: reuse existing token

        import json

        import requests as http_requests

        # If no token yet, exchange the code
        if not access_token:
            if not code:
                raise HTTPException(status_code=400, detail="Missing authorization code")
            if not redirect_uri:
                raise HTTPException(status_code=400, detail="Missing redirect_uri")

            secrets_path = _find_client_secrets()
            with open(secrets_path) as f:
                secrets_data = json.load(f)

            client_info = secrets_data.get("web") or secrets_data.get("installed", {})
            client_id = client_info.get("client_id")
            client_secret = client_info.get("client_secret")
            token_uri = client_info.get("token_uri", "https://oauth2.googleapis.com/token")

            if not client_id or not client_secret:
                raise HTTPException(status_code=500, detail="Invalid client_secrets.json")

            token_res = http_requests.post(
                token_uri,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )

            if token_res.status_code != 200:
                import logging

                try:
                    error_type = token_res.json().get("error", "unknown_error")
                except Exception:
                    error_type = "unknown_error"
                logging.error(f"YouTube token exchange failed with error: {error_type}")
                error_msg = (
                    token_res.json().get("error_description", "Token exchange failed")
                    if token_res.headers.get("content-type", "").startswith("application/json")
                    else "Token exchange failed"
                )
                raise HTTPException(status_code=400, detail=f"Failed to exchange code: {error_msg}")

            access_token = token_res.json().get("access_token")
            refresh_token = token_res.json().get("refresh_token")
            if not access_token:
                raise HTTPException(status_code=400, detail="No access token received")

            if refresh_token:
                conn_db = _get_yt_db()
                # Store refresh_token scoped to user_id via youtube_connections
                _uid = _get_user_id_from_auth(authorization) or "__legacy__"
                conn_db.execute(
                    """
                    INSERT INTO youtube_connections (user_id, refresh_token)
                    VALUES (?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET refresh_token = excluded.refresh_token
                """,
                    (_uid, encrypt_token(refresh_token)),
                )
                conn_db.commit()
                conn_db.close()

        headers = {"Authorization": f"Bearer {access_token}"}
        YT_API = "https://www.googleapis.com/youtube/v3"

        # Authenticate to get user_id & AnalyticsSync
        from server.services.analytics import AnalyticsSync

        user_id = user.id
        if authorization:
            try:
                token = authorization.replace("Bearer ", "").strip()
                AnalyticsSync(auth_token=token)
            except Exception:
                import logging

                logging.getLogger(__name__).warning(
                    "AnalyticsSync init failed — check configuration"
                )

        # If channel_id provided, sync directly (fast-return + background task)
        if channel_id:
            # Fetch minimal channel metadata so the user sees name/thumbnail immediately
            ch_res = http_requests.get(
                f"{YT_API}/channels", params={"part": "snippet", "id": channel_id}, headers=headers
            )
            ch_name = ""
            ch_thumb = ""
            if ch_res.status_code == 200:
                items = ch_res.json().get("items", [])
                if items:
                    ch_name = items[0]["snippet"]["title"]
                    ch_thumb = (
                        items[0]["snippet"].get("thumbnails", {}).get("default", {}).get("url", "")
                    )
            _mark_sync_pending(user_id, channel_id, ch_name, ch_thumb)
            import asyncio

            asyncio.create_task(_run_full_sync(access_token, channel_id, user_id, authorization))
            return {
                "connected": True,
                "channel_name": ch_name,
                "channel_thumbnail": ch_thumb,
                "syncing": True,
            }

        # Otherwise, list all accessible channels for the user to pick
        # 1. Get the default "mine" channel
        channels = []
        mine_res = http_requests.get(
            f"{YT_API}/channels",
            params={"part": "snippet,statistics,contentDetails", "mine": "true"},
            headers=headers,
        )

        if mine_res.status_code == 200:
            for ch in mine_res.json().get("items", []):
                thumb = ch["snippet"].get("thumbnails", {}).get("default", {}).get("url", "")
                channels.append(
                    {
                        "id": ch["id"],
                        "title": ch["snippet"]["title"],
                        "handle": ch["snippet"].get("customUrl", ""),
                        "subscribers": ch["statistics"].get("subscriberCount", "0"),
                        "video_count": ch["statistics"].get("videoCount", "0"),
                        "thumbnail": thumb,
                    }
                )

        # If only 1 channel, kick off sync in background and return immediately
        if len(channels) == 1:
            ch0 = channels[0]
            _mark_sync_pending(user_id, ch0["id"], ch0["title"], ch0["thumbnail"])
            import asyncio

            asyncio.create_task(_run_full_sync(access_token, ch0["id"], user_id, authorization))
            return {
                "connected": True,
                "channel_name": ch0["title"],
                "channel_thumbnail": ch0["thumbnail"],
                "syncing": True,
            }

        # Multiple channels or none: return them for selection
        return {
            "needs_channel_selection": True,
            "access_token": access_token,
            "channels": channels,
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback

        trace = traceback.format_exc()
        try:
            with open("/tmp/azelia_sync_error.txt", "w") as f:
                f.write(trace)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Sync crash: {str(e)} \nTrace: {trace}") from e


@router.post("/analytics/youtube/auto-sync")
async def auto_sync_youtube(authorization: str = Header(None), user: User = Depends(require_auth)):
    """Automatically fetch latest YouTube stats using stored refresh_token (user-scoped)."""
    try:
        user_id = user.id
        conn = _get_yt_db()
        cursor = conn.execute(
            "SELECT refresh_token, channel_id FROM youtube_connections WHERE user_id = ?",
            (user_id,),
        )
        row = cursor.fetchone()
        conn.close()

        if not row or not row[0] or not row[1]:
            raise HTTPException(
                status_code=400,
                detail="No refresh token or channel ID found. Please connect manually.",
            )

        refresh_token = decrypt_token(row[0])
        channel_id = row[1]

        import json

        import requests as http_requests

        secrets_path = _find_client_secrets()
        with open(secrets_path) as f:
            secrets_data = json.load(f)

        client_info = secrets_data.get("web") or secrets_data.get("installed", {})
        client_id = client_info.get("client_id")
        client_secret = client_info.get("client_secret")
        token_uri = client_info.get("token_uri", "https://oauth2.googleapis.com/token")

        token_res = http_requests.post(
            token_uri,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )

        if token_res.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to refresh token")

        access_token = token_res.json().get("access_token")

        # Authenticate for telemetry
        from server.services.analytics import AnalyticsSync

        analytics = None
        if authorization:
            try:
                token = authorization.replace("Bearer ", "").strip()
                analytics = AnalyticsSync(auth_token=token)
            except Exception:
                pass

        result = await _sync_channel(access_token, channel_id, user_id=user_id, analytics=analytics)
        return result
    except HTTPException:
        raise
    except Exception as e:
        import traceback

        trace = traceback.format_exc()
        try:
            with open("/tmp/azelia_auto_sync_error.txt", "w") as f:
                f.write(trace)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Auto-sync crash: {str(e)} \nTrace: {trace}") from e


async def _sync_channel(
    access_token: str,
    channel_id: str,
    user_id: str = None,
    user_jwt: str | None = None,
    analytics=None,
):
    """Sync all videos from a specific channel by ID."""
    import requests as http_requests

    headers = {"Authorization": f"Bearer {access_token}"}
    YT_API = "https://www.googleapis.com/youtube/v3"

    # Get channel info
    ch_res = http_requests.get(
        f"{YT_API}/channels",
        params={"part": "snippet,contentDetails,statistics", "id": channel_id},
        headers=headers,
    )

    if ch_res.status_code != 200 or not ch_res.json().get("items"):
        raise HTTPException(status_code=404, detail="Channel not found")

    channel = ch_res.json()["items"][0]
    channel_name = channel["snippet"]["title"]
    uploads_playlist = channel["contentDetails"]["relatedPlaylists"]["uploads"]

    # Fetch all videos from uploads playlist
    all_video_ids = []
    next_page = None

    while True:
        params = {"part": "snippet", "playlistId": uploads_playlist, "maxResults": 50}
        if next_page:
            params["pageToken"] = next_page

        pl_res = http_requests.get(f"{YT_API}/playlistItems", params=params, headers=headers)
        if pl_res.status_code != 200:
            break

        data = pl_res.json()
        for item in data.get("items", []):
            all_video_ids.append(item["snippet"]["resourceId"]["videoId"])

        next_page = data.get("nextPageToken")
        if not next_page:
            break

    # Get video details in batches of 50
    shorts = []
    for i in range(0, len(all_video_ids), 50):
        batch = all_video_ids[i : i + 50]
        vid_res = http_requests.get(
            f"{YT_API}/videos",
            params={"part": "snippet,contentDetails,statistics", "id": ",".join(batch)},
            headers=headers,
        )

        if vid_res.status_code != 200:
            continue

        for video in vid_res.json().get("items", []):
            duration_secs = _parse_iso_duration(video["contentDetails"]["duration"])
            stats = video.get("statistics", {})
            snippet = video["snippet"]
            thumbnails = snippet.get("thumbnails", {})
            thumb_url = thumbnails.get("high", thumbnails.get("default", {})).get("url", "")

            shorts.append(
                {
                    "video_id": video["id"],
                    "title": snippet.get("title", ""),
                    "published_at": snippet.get("publishedAt", ""),
                    "duration_seconds": duration_secs,
                    "view_count": int(stats.get("viewCount", 0)),
                    "like_count": int(stats.get("likeCount", 0)),
                    "comment_count": int(stats.get("commentCount", 0)),
                    "channel_name": channel_name,
                    "channel_id": channel_id,
                    "thumbnail_url": thumb_url,
                }
            )

    # Store in SQLite
    conn = _get_yt_db()
    now = datetime.now().isoformat()

    # Clear old data for THIS user only (multi-user safe)
    if user_id:
        conn.execute("DELETE FROM youtube_shorts WHERE user_id = ?", (user_id,))
    else:
        conn.execute("DELETE FROM youtube_shorts WHERE user_id IS NULL")

    for s in shorts:
        conn.execute(
            """
            INSERT OR REPLACE INTO youtube_shorts
            (video_id, user_id, title, published_at, duration_seconds, view_count, like_count, comment_count, channel_name, channel_id, thumbnail_url, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                s["video_id"],
                user_id,
                s["title"],
                s["published_at"],
                s["duration_seconds"],
                s["view_count"],
                s["like_count"],
                s["comment_count"],
                s["channel_name"],
                s["channel_id"],
                s["thumbnail_url"],
                now,
            ),
        )

    # Save connection metadata (user-scoped)
    _uid = user_id or "__legacy__"
    conn.execute(
        """
        INSERT INTO youtube_connections (user_id, channel_id, channel_name, last_synced)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            channel_id = excluded.channel_id,
            channel_name = excluded.channel_name,
            last_synced = excluded.last_synced
    """,
        (_uid, channel_id, channel_name, now),
    )
    conn.commit()
    conn.close()

    # --- SUPABASE TELEMETRY SYNC ---
    # Telemetry enrichment is best-effort: if PostgREST rejects the batch (URL too long,
    # special chars in titles, etc) the user's YouTube sync must still succeed.
    if user_id and analytics and analytics.Enabled:
        try:
            import hashlib

            from packages.core.services.telemetry import telemetry

            # Batch lookups — PostgREST chokes on very long `in.(...)` URLs
            clips_by_title: dict = {}
            titles = [s["title"] for s in shorts]
            BATCH = 50
            for i in range(0, len(titles), BATCH):
                chunk = titles[i : i + BATCH]
                try:
                    res = (
                        analytics.client.table("clips_metadata")
                        .select("video_title, hook_type, sentiment_score")
                        .in_("video_title", chunk)
                        .execute()
                    )
                    for row in res.data or []:
                        clips_by_title[row["video_title"]] = row
                except Exception as batch_err:
                    import logging

                    logging.getLogger(__name__).warning(
                        f"clips_metadata batch lookup failed (continuing without enrichment): {type(batch_err).__name__}"
                    )

            for s in shorts:
                clip_data = clips_by_title.get(s["title"])
                hook_type = clip_data.get("hook_type") if clip_data else None
                predicted_score = clip_data.get("sentiment_score") if clip_data else None

                title_hash = hashlib.sha256(s["title"].encode()).hexdigest()[:12]
                try:
                    telemetry.track_youtube_performance(
                        user_jwt=user_jwt,
                        youtube_id=s["video_id"],
                        views=s["view_count"],
                        likes=s["like_count"],
                        comments=s["comment_count"],
                        duration_seconds=s["duration_seconds"],
                        hook_type=hook_type,
                        predicted_score=predicted_score,
                        title_hash=title_hash,
                    )
                except Exception as track_err:
                    import logging

                    logging.getLogger(__name__).warning(
                        f"telemetry.track_youtube_performance failed for {s['video_id']}: {type(track_err).__name__}"
                    )
        except Exception as telemetry_err:
            import logging

            logging.getLogger(__name__).error(
                f"Telemetry block crashed (YouTube sync continues): {type(telemetry_err).__name__}: {telemetry_err}"
            )

    return {
        "total_shorts": len(shorts),
        "channel_name": channel_name,
        "channel_id": channel_id,
    }


# ─── YouTube Historical Extractor (Retroactive Intelligence) ────────────────

# Default Anthropic model for retroactive analysis. Haiku 4.5 classifies
# shorts well enough and costs ~5x less than Sonnet (~$0.32 vs $1.60 per
# 500 shorts). Users can override via body.model in /sync.
_RETROACTIVE_DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def _estimate_retroactive_cost(
    num_shorts: int, anthropic_model: str = _RETROACTIVE_DEFAULT_MODEL
) -> dict:
    """Cost estimate for retroactive sync.

    Each short needs a transcript + metrics analysis call.
    ~1500 input tokens (system prompt + transcript + metrics) + ~400 output tokens (JSON).

    Pricing per M tokens (2026-04):
      - Haiku 4.5: $1 in / $5 out
      - Sonnet 4.6: $3 in / $15 out
      - Opus 4.7: $15 in / $75 out
    """
    input_tokens = num_shorts * 1500
    output_tokens = num_shorts * 400
    m = anthropic_model.lower()
    if "opus" in m:
        in_rate, out_rate = 15.0, 75.0
    elif "sonnet" in m:
        in_rate, out_rate = 3.0, 15.0
    else:  # haiku / default
        in_rate, out_rate = 1.0, 5.0
    cost = (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
    return {
        "num_shorts": num_shorts,
        "input_tokens_est": input_tokens,
        "output_tokens_est": output_tokens,
        "cost_usd_est": round(cost, 3),
        "model": anthropic_model,
    }


@router.get("/analytics/youtube/historical/estimate")
async def estimate_historical_cost(
    model: str | None = None,
    user: User = Depends(require_auth),
):
    """Count available historical shorts and estimate Anthropic cost.

    Accepts ?model=... to preview cost at a different model.
    Returns model_options so the frontend can render a picker.
    """
    # Count shorts scoped to this user AND not yet analyzed by the LLM —
    # avoids re-billing the creator for the same content on repeated runs.
    conn = _get_yt_db()
    cursor = conn.execute(
        "SELECT COUNT(*) FROM youtube_shorts WHERE user_id = ? AND (llm_analysis IS NULL OR llm_analysis = '')",
        (user.id,),
    )
    count_row = cursor.fetchone()
    total_unanalyzed = count_row[0] if count_row else 0
    # Also expose the absolute total so the UI can tell the user how many
    # shorts are already analyzed.
    total_cur = conn.execute("SELECT COUNT(*) FROM youtube_shorts WHERE user_id = ?", (user.id,))
    total_all = total_cur.fetchone()[0] if total_cur else 0
    conn.close()

    total_shorts = total_unanalyzed
    if total_shorts == 0:
        return {
            "total_shorts": 0,
            "total_all": total_all,
            "estimated_cost_usd": 0.0,
            "model": _RETROACTIVE_DEFAULT_MODEL,
            "model_options": {
                "claude-haiku-4-5-20251001": 0.0,
                "claude-sonnet-4-6": 0.0,
                "claude-opus-4-7": 0.0,
            },
        }

    # Cap batch to 100 to match /sync behaviour (max_videos=100).
    batch_size = min(100, total_shorts)
    chosen_model = _resolve_anthropic_model(model, fallback=_RETROACTIVE_DEFAULT_MODEL)
    est = _estimate_retroactive_cost(batch_size, chosen_model)
    est["total_shorts"] = total_shorts
    est["batch_size"] = batch_size
    est["estimated_cost_usd"] = est["cost_usd_est"]
    est["model_options"] = {
        "claude-haiku-4-5-20251001": _estimate_retroactive_cost(
            batch_size, "claude-haiku-4-5-20251001"
        )["cost_usd_est"],
        "claude-sonnet-4-6": _estimate_retroactive_cost(batch_size, "claude-sonnet-4-6")[
            "cost_usd_est"
        ],
        "claude-opus-4-7": _estimate_retroactive_cost(batch_size, "claude-opus-4-7")[
            "cost_usd_est"
        ],
    }
    return est


@router.post("/analytics/youtube/historical/sync")
async def sync_historical_data(
    request: Request,
    body: dict = Body(default_factory=dict),
    user: User = Depends(require_auth),
):
    """
    Triggers the YouTubeHistoricalExtractor as a BACKGROUND JOB.
    Returns immediately with a job_id for polling progress.
    """
    import asyncio

    from server.workers.job_store import get_job_store

    user_id = user.id
    conn = _get_yt_db()
    cursor = conn.execute(
        "SELECT refresh_token, channel_id FROM youtube_connections WHERE user_id = ?", (user_id,)
    )
    row = cursor.fetchone()
    conn.close()

    if not row or not row[0] or not row[1]:
        raise HTTPException(status_code=400, detail="YouTube no conectado. Conéctalo primero.")

    refresh_token = decrypt_token(row[0])
    channel_id = row[1]

    # Refresh the access token
    import json

    import requests as http_requests

    secrets_path = _find_client_secrets()
    with open(secrets_path) as f:
        secrets_data = json.load(f)

    client_info = secrets_data.get("web") or secrets_data.get("installed", {})
    token_uri = client_info.get("token_uri", "https://oauth2.googleapis.com/token")

    token_res = http_requests.post(
        token_uri,
        data={
            "client_id": client_info.get("client_id"),
            "client_secret": client_info.get("client_secret"),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )

    if token_res.status_code != 200:
        raise HTTPException(status_code=401, detail="Failed to refresh Google token")

    access_token = token_res.json().get("access_token")

    # Resolve the user's preferred output language so the retroactive analysis
    # writes `retention_analysis` / `growth_driver` in the creator's language.
    try:
        from packages.clips.pipeline import _load_user_profile_context
        from packages.core.taxonomy import language_label as _lang_label

        _profile = _load_user_profile_context(user_id)
        _output_language = _lang_label(_profile.get("language") or "")
    except Exception:
        _output_language = "English"

    # Create a background job
    store = get_job_store()
    import uuid

    # Model choice constrained to the server's allowlist.
    chosen_model = _resolve_anthropic_model(body.get("model"), fallback=_RETROACTIVE_DEFAULT_MODEL)

    job_id = f"historical_{uuid.uuid4().hex[:8]}"
    store.create_job(job_id, episode_id=f"yt_historical_{user_id}", total_clips=0)
    store.update_progress(job_id, 0, "🔍 Preparando análisis histórico...")

    async def _run_historical_sync():
        """Background worker for historical sync."""
        try:
            from packages.core.services.telemetry import telemetry as telemetry_svc
            from packages.core.services.youtube_historical import YouTubeHistoricalExtractor

            extractor = YouTubeHistoricalExtractor(
                telemetry_svc,
                anthropic_model=chosen_model,
                output_language=_output_language,
                user_jwt=getattr(request.state, "user_jwt", None),
            )

            result = await extractor.process_historical_shorts(
                user_id=user_id,
                channel_id=channel_id,
                access_token=access_token,
                max_videos=100,
                job_id=job_id,
            )

            store.complete_job(
                job_id,
                clips_generated=result.get("processed", 0),
                message=f"✅ {result.get('processed', 0)} videos analizados",
            )
        except Exception as e:
            import logging as _logging
            import traceback

            _logging.error("Historical sync failed: %s\n%s", e, traceback.format_exc())
            store.fail_job(job_id, str(e))

    # Fire and forget
    asyncio.create_task(_run_historical_sync())

    return {
        "job_id": job_id,
        "status": "started",
        "model": chosen_model,
        "message": "Historical analysis started in the background.",
    }


@router.get("/analytics/youtube/historical/status/{job_id}")
async def get_historical_sync_status(job_id: str, user: User = Depends(require_auth)):
    """Poll the status of a historical sync background job."""
    from server.workers.job_store import get_job_store

    store = get_job_store()
    job = store.get_job_for_user(job_id, user.id)

    if not job:
        # 404 (not 403) so callers cannot enumerate other users' job IDs.
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job.job_id,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
    }


@router.get("/analytics/youtube/insights")
async def get_youtube_insights(user: User = Depends(require_auth)):
    """Aggregate insights from synced YouTube Shorts data (Local Intelligence)."""
    try:
        user_id = user.id
        conn = _get_yt_db()

        base_where = "WHERE 1=1"
        params_base = []
        if user_id:
            base_where = "WHERE user_id = ?"
            params_base = [user_id]

        # Basic totals + retention averages
        cursor = conn.execute(
            f"""
            SELECT
                COUNT(*) as total,
                COALESCE(SUM(view_count), 0) as total_views,
                COALESCE(SUM(like_count), 0) as total_likes,
                COALESCE(AVG(view_count), 0) as avg_views,
                COALESCE(AVG(duration_seconds), 0) as avg_duration,
                COALESCE(AVG(average_view_percentage), 0) as avg_retention,
                COALESCE(AVG(average_view_duration), 0) as avg_view_dur,
                COALESCE(SUM(shares_count), 0) as total_shares,
                COALESCE(SUM(subscribers_gained), 0) as total_subs_gained,
                COALESCE(SUM(subscribers_lost), 0) as total_subs_lost,
                COUNT(hook_type) as analyzed_count
            FROM youtube_shorts
            {base_where}
        """,
            params_base,
        )
        row = cursor.fetchone()
        total = row[0]
        total_views = row[1]
        total_likes = row[2]
        avg_views = row[3]
        avg_duration = row[4]
        avg_retention = row[5]
        avg_view_dur = row[6]
        total_shares = row[7]
        total_subs_gained = row[8]
        total_subs_lost = row[9]
        analyzed_count = row[10]

        if total == 0:
            conn.close()
            return {
                "total_shorts": 0,
                "total_views": 0,
                "total_likes": 0,
                "avg_views": 0,
                "avg_duration": 0,
                "best_performing": [],
                "duration_breakdown": [],
                "hook_type_breakdown": [],
                "emotional_charge_breakdown": [],
                "top_topics": [],
                "retention": {},
            }

        # Top 10 performing shorts (enriched with retention if available)
        best_cursor = conn.execute(
            f"""
            SELECT title, view_count, video_id, average_view_percentage, hook_type
            FROM youtube_shorts
            {base_where}
            ORDER BY view_count DESC
            LIMIT 10
        """,
            params_base,
        )
        best_performing = [
            {
                "title": r[0],
                "views": r[1],
                "url": f"https://youtube.com/shorts/{r[2]}",
                "retention_pct": round(r[3], 1) if r[3] else None,
                "hook_type": r[4],
            }
            for r in best_cursor.fetchall()
        ]

        # Duration breakdown
        duration_breakdown = []
        ranges = [
            ("0-15s", 0, 15),
            ("16-30s", 16, 30),
            ("31-60s", 31, 60),
            ("1-3 min", 61, 180),
            ("3+ min", 181, 99999),
        ]
        for label, lo, hi in ranges:
            params_range = params_base + [lo, hi]
            dc = conn.execute(
                f"""
                SELECT COUNT(*), COALESCE(AVG(view_count), 0), COALESCE(AVG(average_view_percentage), 0)
                FROM youtube_shorts
                {base_where} AND duration_seconds >= ? AND duration_seconds <= ?
            """,
                params_range,
            )
            dr = dc.fetchone()
            if dr[0] > 0:
                duration_breakdown.append(
                    {
                        "range": label,
                        "count": dr[0],
                        "avg_views": int(dr[1]),
                        "avg_retention": round(dr[2], 1) if dr[2] else None,
                    }
                )

        # ─── Local Intelligence: Hook Type Distribution ───
        hook_cursor = conn.execute(
            f"""
            SELECT hook_type, COUNT(*) as cnt,
                   COALESCE(AVG(view_count), 0), COALESCE(AVG(average_view_percentage), 0)
            FROM youtube_shorts
            {base_where} AND hook_type IS NOT NULL
            GROUP BY hook_type ORDER BY cnt DESC
        """,
            params_base,
        )
        hook_type_breakdown = [
            {
                "hook_type": r[0],
                "count": r[1],
                "avg_views": int(r[2]),
                "avg_retention": round(r[3], 1) if r[3] else None,
            }
            for r in hook_cursor.fetchall()
        ]

        # ─── Local Intelligence: Emotional Charge Distribution ───
        emotion_cursor = conn.execute(
            f"""
            SELECT emotional_charge, COUNT(*) as cnt,
                   COALESCE(AVG(view_count), 0), COALESCE(AVG(average_view_percentage), 0)
            FROM youtube_shorts
            {base_where} AND emotional_charge IS NOT NULL
            GROUP BY emotional_charge ORDER BY cnt DESC
        """,
            params_base,
        )
        emotional_charge_breakdown = [
            {
                "emotion": r[0],
                "count": r[1],
                "avg_views": int(r[2]),
                "avg_retention": round(r[3], 1) if r[3] else None,
            }
            for r in emotion_cursor.fetchall()
        ]

        # ─── Local Intelligence: Top Topics ───
        import json as _json

        topics_cursor = conn.execute(
            f"""
            SELECT core_topics FROM youtube_shorts
            {base_where} AND core_topics IS NOT NULL
        """,
            params_base,
        )
        topic_counter = {}
        for (topics_str,) in topics_cursor.fetchall():
            try:
                topics = _json.loads(topics_str)
                for t in topics:
                    topic_counter[t] = topic_counter.get(t, 0) + 1
            except Exception:
                pass
        top_topics = sorted(topic_counter.items(), key=lambda x: x[1], reverse=True)[:15]

        conn.close()

        return {
            "total_shorts": total,
            "total_views": int(total_views),
            "total_likes": int(total_likes),
            "total_shares": int(total_shares),
            "avg_views": int(avg_views),
            "avg_duration": round(avg_duration, 1),
            "best_performing": best_performing,
            "duration_breakdown": duration_breakdown,
            # ─── Local Intelligence Fields ───
            "analyzed_count": analyzed_count,
            "retention": {
                "avg_view_percentage": round(avg_retention, 1) if avg_retention else None,
                "avg_view_duration_seconds": round(avg_view_dur, 1) if avg_view_dur else None,
                "subscribers_gained": int(total_subs_gained),
                "subscribers_lost": int(total_subs_lost),
                "net_subscribers": int(total_subs_gained) - int(total_subs_lost),
            },
            "hook_type_breakdown": hook_type_breakdown,
            "emotional_charge_breakdown": emotional_charge_breakdown,
            "top_topics": [{"topic": t, "count": c} for t, c in top_topics],
        }
    except Exception:
        return {
            "total_shorts": 0,
            "total_views": 0,
            "total_likes": 0,
            "avg_views": 0,
            "avg_duration": 0,
            "best_performing": [],
            "duration_breakdown": [],
            "hook_type_breakdown": [],
            "emotional_charge_breakdown": [],
            "top_topics": [],
            "retention": {},
        }


def _parse_iso_duration(duration: str) -> int:
    """Parse ISO 8601 duration (PT1M30S) to seconds."""
    import re

    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


# ─── Platform Connections ────────────────────────────────────────────────────


@router.get("/connections/youtube")
async def get_youtube_connection_status(
    authorization: str = Header(None), user: User = Depends(require_auth)
):
    """Check if YouTube is connected for the current user."""
    token = (authorization or "").replace("Bearer ", "").strip()

    try:
        from server.services.analytics import AnalyticsSync

        analytics = AnalyticsSync(auth_token=token)

        if not analytics.Enabled:
            return {"is_connected": False}

        # Try to fetch the connection from user_connections table
        res = (
            analytics.client.table("user_connections")
            .select("*")
            .eq("platform", "youtube")
            .maybeSingle()
            .execute()
        )

        if res.data:
            metadata = res.data.get("metadata", {})
            return {
                "is_connected": True,
                "channel_name": metadata.get("title", "YouTube Channel"),
                "channel_id": metadata.get("channel_id"),
                "subscriber_count": metadata.get("statistics", {}).get("subscriberCount"),
                "video_count": metadata.get("statistics", {}).get("videoCount"),
            }

        return {"is_connected": False}
    except Exception:
        # Table might not exist yet or service not configured
        return {"is_connected": False}


@router.post("/connections/{platform}")
async def connect_platform_endpoint(
    platform: str, authorization: str = Header(None), user: User = Depends(require_auth)
):
    """Connect a social platform."""
    from server.services.analytics import AnalyticsSync

    token = (authorization or "").replace("Bearer ", "").strip()
    analytics = AnalyticsSync(auth_token=token)

    if not analytics.Enabled:
        raise HTTPException(
            status_code=500, detail="Analytics service not enabled (check Supabase config)"
        )

    success = analytics.connect_platform(platform)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to connect platform")

    return {"status": "connected", "platform": platform}


# ─── YouTube Analytics CSV Upload ────────────────────────────────────────────


@router.post("/analytics/upload-csv")
async def upload_analytics_csv(
    file: UploadFile = File(...),
    authorization: str = Header(None),
    user: User = Depends(require_auth),
):
    """Upload and process YouTube Analytics CSV."""
    from server.sources.youtube_analytics import YouTubeAnalyticsParser

    token = (authorization or "").replace("Bearer ", "").strip()

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Invalid file type. Only CSV supported.")

    try:
        content = await file.read()
        parser = YouTubeAnalyticsParser(auth_token=token)

        if not parser.enabled:
            raise HTTPException(status_code=500, detail="Analytics service not enabled")

        stats = parser.parse_and_sync(content)
        return stats

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("YouTube takeout parse failed")
        raise HTTPException(status_code=500, detail="Failed to parse takeout") from exc


# ─── YouTube API Fetch ───────────────────────────────────────────────────────


@router.post("/analytics/fetch-youtube")
async def fetch_youtube_analytics(
    provider_token: str = Form(...),
    authorization: str = Header(None),
    user: User = Depends(require_auth),
):
    """
    Fetch real-time analytics from YouTube Data API using the user's Google Access Token.
    Updates 'user_connections', matches videos to 'clips_metadata', and emits
    telemetry events for the LI feedback loop.
    """
    import hashlib

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    from packages.core.services.telemetry import telemetry
    from server.services.analytics import AnalyticsSync

    token = (authorization or "").replace("Bearer ", "").strip()
    analytics = AnalyticsSync(auth_token=token)
    if not analytics.Enabled:
        raise HTTPException(status_code=500, detail="Analytics service not enabled")

    user_id = user.id

    try:
        # Initialize YouTube Client
        creds = Credentials(token=provider_token)
        youtube = build("youtube", "v3", credentials=creds)

        # Get Channel Stats
        channel_resp = youtube.channels().list(mine=True, part="snippet,statistics").execute()
        if not channel_resp.get("items"):
            raise HTTPException(status_code=404, detail="No YouTube channel found for this user")

        channel = channel_resp["items"][0]
        channel_id = channel["id"]
        channel_title = channel["snippet"]["title"]

        # Update Connection Status
        analytics.connect_platform(
            "youtube",
            metadata={
                "channel_id": channel_id,
                "title": channel_title,
                "thumbnails": channel["snippet"]["thumbnails"],
                "statistics": channel["statistics"],
            },
        )

        # Get Recent Videos
        uploads_playlist_id = channel["contentDetails"]["relatedPlaylists"]["uploads"]

        videos_resp = (
            youtube.playlistItems()
            .list(playlistId=uploads_playlist_id, part="snippet", maxResults=50)
            .execute()
        )

        video_ids = [
            item["snippet"]["resourceId"]["videoId"] for item in videos_resp.get("items", [])
        ]

        # Get stats for these videos
        stats_resp = (
            youtube.videos()
            .list(id=",".join(video_ids), part="snippet,statistics,contentDetails")
            .execute()
        )

        matched_count = 0
        telemetry_count = 0

        # Sync Video Stats to Clips
        for vid in stats_resp.get("items", []):
            title = vid["snippet"]["title"]
            stats = vid["statistics"]

            views = int(stats.get("viewCount", 0))
            likes = int(stats.get("likeCount", 0))
            comments_count = int(stats.get("commentCount", 0))

            # Parse duration
            duration_secs = None
            if vid.get("contentDetails", {}).get("duration"):
                duration_secs = _parse_iso_duration(vid["contentDetails"]["duration"])

            metrics = {
                "platform": "youtube",
                "youtube_id": vid["id"],
                "views": views,
                "likes": likes,
                "comments": comments_count,
                "last_updated": "now()",
            }

            # Update clips_metadata (existing behavior)
            res = (
                analytics.client.table("clips_metadata")
                .update({"performance_metrics": metrics})
                .eq("video_title", title)
                .execute()
            )

            if res.data:
                matched_count += 1

                # Extract clip metadata for enriched telemetry
                clip_data = res.data[0] if res.data else {}
                hook_type = clip_data.get("hook_type")
                predicted_score = clip_data.get("sentiment_score")
                clip_duration = clip_data.get("duration_seconds") or duration_secs

                # NEW: Emit telemetry event for LI feedback loop.
                # `token` (set earlier from the Authorization header) is the
                # user JWT — fresh and authenticated for this request.
                if user_id:
                    title_hash = hashlib.sha256(title.encode()).hexdigest()[:12]
                    telemetry.track_youtube_performance(
                        user_jwt=token,
                        youtube_id=vid["id"],
                        views=views,
                        likes=likes,
                        comments=comments_count,
                        duration_seconds=clip_duration,
                        hook_type=hook_type,
                        predicted_score=predicted_score,
                        title_hash=title_hash,
                    )
                    telemetry_count += 1

        return {
            "status": "success",
            "channel": channel_title,
            "videos_scanned": len(video_ids),
            "clips_matched": matched_count,
            "telemetry_events": telemetry_count,
        }

    except Exception as exc:
        import logging

        logging.getLogger(__name__).error("YouTube Fetch Error occurred", exc_info=True)
        raise HTTPException(
            status_code=400, detail="Failed to fetch YouTube analytics. Please try again."
        ) from exc


# ─── YouTube OAuth Flow ──────────────────────────────────────────────────────


@router.get("/auth/youtube/authorize")
async def authorize_youtube(
    redirect_uri: str,
    authorization: str = Header(None),
    user: User = Depends(require_auth),
):
    """
    Start OAuth flow for YouTube connection.
    Returns the Google authorization URL (built manually, no PKCE).
    """
    import json
    from urllib.parse import urlencode

    try:
        secrets_file = _find_client_secrets()
        with open(secrets_file) as f:
            secrets_data = json.load(f)

        client_info = secrets_data.get("web") or secrets_data.get("installed", {})
        client_id = client_info.get("client_id")
        auth_uri = client_info.get("auth_uri", "https://accounts.google.com/o/oauth2/v2/auth")

        if not client_id:
            raise HTTPException(status_code=500, detail="Missing client_id in client_secrets.json")

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/yt-analytics.readonly",
            "access_type": "offline",
            "prompt": "consent",
        }

        authorization_url = f"{auth_uri}?{urlencode(params)}"
        return {"url": authorization_url}

    except HTTPException:
        raise
    except Exception as e:
        logger.info("OAuth Authorization Error occurred: %s", e)
        logger.exception("YouTube sync-with-code failed")
        raise HTTPException(status_code=500, detail="YouTube sync failed") from e


@router.post("/auth/youtube/callback")
async def callback_youtube(
    code: str = Body(..., embed=True),
    redirect_uri: str = Body(..., embed=True),
    authorization: str = Header(None),
    user: User = Depends(require_auth),
):
    """
    Exchange authorization code for tokens and link to current user.
    """
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build

    from server.services.analytics import AnalyticsSync

    token = (authorization or "").replace("Bearer ", "").strip()
    analytics = AnalyticsSync(auth_token=token)

    try:
        secrets_file = _find_client_secrets()
        flow = Flow.from_client_secrets_file(
            secrets_file,
            scopes=["https://www.googleapis.com/auth/youtube.readonly"],
            redirect_uri=redirect_uri,
        )

        flow.fetch_token(code=code)
        creds = flow.credentials

        # Use credentials to get channel info
        youtube = build("youtube", "v3", credentials=creds)

        channel_resp = youtube.channels().list(mine=True, part="snippet,statistics").execute()
        if not channel_resp.get("items"):
            raise HTTPException(status_code=404, detail="No YouTube channel found")

        channel = channel_resp["items"][0]

        # Save connection
        analytics.connect_platform(
            "youtube",
            metadata={
                "channel_id": channel["id"],
                "title": channel["snippet"]["title"],
                "thumbnails": channel["snippet"]["thumbnails"],
                "statistics": channel["statistics"],
                "refresh_token": creds.refresh_token,
                "access_token": creds.token,
            },
        )

        return {"status": "success", "channel": channel["snippet"]["title"]}

    except Exception as exc:
        import logging

        logging.getLogger(__name__).error("OAuth Callback Error occurred", exc_info=True)
        raise HTTPException(status_code=500, detail="Authentication failed. Please try again.") from exc
