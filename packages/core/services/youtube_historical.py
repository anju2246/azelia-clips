import asyncio
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import googleapiclient.discovery
import isodate
from google.oauth2.credentials import Credentials

# El sync histórico SÍ está cableado: POST /analytics/youtube/historical/sync
# llama a YouTubeHistoricalExtractor. No devuelve 501. El comentario viejo
# que decía "unused / 501" estaba desactualizado. Lo que impedía correrlo
# fuera del Mac era el fallback MLX Whisper tiny, que solo existe en Apple
# Silicon. El fallback ahora es NVIDIA Parakeet en Linux.
from packages.core.llm_provider import get_llm

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None

logger = logging.getLogger(__name__)

# Por debajo de esta fracción de audiencia retenida consideramos que la gente
# "se fue" (drop-off). 0.5 = quedó la mitad de quienes empezaron.
RETENTION_DROP_THRESHOLD = 0.5


def parse_retention_curve(response: dict) -> list[dict]:
    """Convierte la respuesta de YouTube Analytics (dimensión
    `elapsedVideoTimeRatio`) en una curva normalizada.

    Espera `metrics=audienceWatchRatio,relativeRetentionPerformance` y
    `dimensions=elapsedVideoTimeRatio`. Robusto al orden de columnas: usa
    `columnHeaders` para mapear. Devuelve [{ratio, audience_watch_ratio,
    relative_retention}] ordenado por ratio. Filas inválidas se omiten.
    """
    if not isinstance(response, dict):
        return []
    headers = [h.get("name") for h in response.get("columnHeaders", [])]
    rows = response.get("rows") or []
    curve: list[dict] = []
    for row in rows:
        try:
            rd = dict(zip(headers, row))
            ratio = rd.get("elapsedVideoTimeRatio")
            if ratio is None:
                continue
            curve.append({
                "ratio": float(ratio),
                "audience_watch_ratio": (
                    float(rd["audienceWatchRatio"])
                    if rd.get("audienceWatchRatio") is not None else None
                ),
                "relative_retention": (
                    float(rd["relativeRetentionPerformance"])
                    if rd.get("relativeRetentionPerformance") is not None else None
                ),
            })
        except (ValueError, TypeError):
            continue
    curve.sort(key=lambda p: p["ratio"])
    return curve


def derive_drop_off_ratio(
    curve: list[dict], threshold: float = RETENTION_DROP_THRESHOLD
) -> Optional[float]:
    """Primer `ratio` donde `audience_watch_ratio` cae por debajo del umbral
    (dónde se va la mayoría de la gente). None si nunca baja del umbral."""
    for point in curve:
        awr = point.get("audience_watch_ratio")
        if awr is not None and awr < threshold:
            return point["ratio"]
    return None


def store_retention_curve(
    conn, video_id: str, curve: list[dict], user_id: str = "local"
) -> Optional[float]:
    """Upsert idempotente de la curva en `retention_curves`. Devuelve el
    drop_off_ratio derivado."""
    import json as _json
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    drop_off = derive_drop_off_ratio(curve)
    conn.execute(
        """
        INSERT INTO retention_curves (video_id, user_id, curve_json, drop_off_ratio, fetched_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(video_id, user_id) DO UPDATE SET
            curve_json = excluded.curve_json,
            drop_off_ratio = excluded.drop_off_ratio,
            fetched_at = excluded.fetched_at
        """,
        (
            video_id, user_id, _json.dumps(curve),
            drop_off, _dt.now(_tz.utc).isoformat(),
        ),
    )
    conn.commit()
    return drop_off


def labeling_available() -> tuple[bool, str]:
    """Hay un LLM para etiquetar transcripts. Si no, no se inventan etiquetas."""
    from packages.core.config import settings as _settings

    if (getattr(_settings, "anthropic_api_key", "") or "").strip():
        return True, ""
    try:
        get_llm()
    except Exception as e:
        return False, (
            "Etiquetar transcripts requiere ANTHROPIC_API_KEY o Claude Code autenticado. "
            f"({e})"
        )
    return True, ""


def _metric_or_none(analytics: dict, key: str):
    """Valor real de Analytics, o None si la API no lo trajo. None no pisa
    un número ya guardado y no se sustituye por un cero inventado."""
    if not analytics or key not in analytics or analytics[key] is None:
        return None
    return analytics[key]


def core_topics_for_storage(topics) -> str:
    """CSV, el formato que lee creator_self. El JSON completo queda en llm_analysis."""
    if isinstance(topics, str):
        return topics.strip()
    if not isinstance(topics, list):
        return ""
    return ",".join(str(topic).strip() for topic in topics if str(topic).strip())


def upsert_short_performance(conn, user_id: str, record: dict) -> None:
    """Guarda vistas, likes, comentarios y retención real. No borra una
    etiqueta previa ni una retención ya medida si este pase no la trajo."""
    analytics = record.get("analytics") or {}
    conn.execute(
        """
        INSERT INTO youtube_shorts
            (video_id, user_id, title, published_at, duration_seconds,
             view_count, like_count, comment_count, privacy_status,
             average_view_duration, average_view_percentage,
             shares_count, subscribers_gained, subscribers_lost,
             estimated_minutes_watched, synced_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(video_id, user_id) DO UPDATE SET
            title = excluded.title,
            published_at = COALESCE(excluded.published_at, youtube_shorts.published_at),
            duration_seconds = excluded.duration_seconds,
            view_count = excluded.view_count,
            like_count = excluded.like_count,
            comment_count = excluded.comment_count,
            privacy_status = COALESCE(excluded.privacy_status, youtube_shorts.privacy_status),
            average_view_duration = COALESCE(excluded.average_view_duration, youtube_shorts.average_view_duration),
            average_view_percentage = COALESCE(excluded.average_view_percentage, youtube_shorts.average_view_percentage),
            shares_count = COALESCE(excluded.shares_count, youtube_shorts.shares_count),
            subscribers_gained = COALESCE(excluded.subscribers_gained, youtube_shorts.subscribers_gained),
            subscribers_lost = COALESCE(excluded.subscribers_lost, youtube_shorts.subscribers_lost),
            estimated_minutes_watched = COALESCE(excluded.estimated_minutes_watched, youtube_shorts.estimated_minutes_watched),
            synced_at = excluded.synced_at
        """,
        (
            record["video_id"],
            user_id,
            record.get("title") or "",
            record.get("published_at") or None,
            record.get("duration_seconds"),
            int(record.get("views") or 0),
            int(record.get("likes") or 0),
            int(record.get("comments") or 0),
            record.get("privacy_status"),
            _metric_or_none(analytics, "averageViewDuration"),
            _metric_or_none(analytics, "averageViewPercentage"),
            _metric_or_none(analytics, "shares"),
            _metric_or_none(analytics, "subscribersGained"),
            _metric_or_none(analytics, "subscribersLost"),
            _metric_or_none(analytics, "estimatedMinutesWatched"),
        ),
    )


def store_short_labels(conn, user_id: str, video_id: str, analysis: dict) -> None:
    conn.execute(
        """
        UPDATE youtube_shorts
        SET hook_type = ?, emotional_charge = ?, core_topics = ?, llm_analysis = ?
        WHERE video_id = ? AND user_id = ?
        """,
        (
            analysis.get("hook_type"),
            analysis.get("emotional_charge"),
            core_topics_for_storage(analysis.get("core_topics")),
            json.dumps(analysis, ensure_ascii=False),
            video_id,
            user_id,
        ),
    )


def pending_label_ids(conn, user_id: str, video_ids: list[str]) -> list[str]:
    """Shorts que todavía no tienen análisis. Re-correr el sync no vuelve a
    cobrar el LLM por un short ya etiquetado."""
    if not video_ids:
        return []
    placeholders = ",".join(["?"] * len(video_ids))
    rows = conn.execute(
        f"""
        SELECT video_id FROM youtube_shorts
        WHERE user_id=? AND video_id IN ({placeholders})
          AND llm_analysis IS NOT NULL AND llm_analysis != ''
        """,
        (user_id, *video_ids),
    ).fetchall()
    done = {row[0] for row in rows}
    return [video_id for video_id in video_ids if video_id not in done]


def snapshot_path_for(db_path: str, user_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (user_id or "local"))[:80]
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), f"creator_self.{safe or 'local'}.json")


class YouTubeHistoricalExtractor:
    """
    Analiza los Shorts históricos del propio canal y refresca el snapshot
    creator_self con vistas, likes, comentarios y average view percentage reales.
    Captions de YouTube primero; si faltan, NVIDIA Parakeet en Linux.
    """

    # Path to local SQLite DB
    YT_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "server", "data", "youtube_shorts.db")

    SUPABASE_SYNC_ENABLED = True

    # Default model for retroactive analysis. Haiku handles the classification task
    # well enough and costs ~5x less than Sonnet (~$0.32 vs $1.60 per 500 shorts).
    DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

    def __init__(
        self,
        telemetry_service=None,  # kept for API compat; ignored in local-first MVP
        anthropic_model: Optional[str] = None,
        output_language: str = "English",
    ):
        # El LLM se resuelve al etiquetar. Construirlo aquí tumbaba el sync
        # entero en una máquina sin Claude Code ni ANTHROPIC_API_KEY, antes
        # siquiera de guardar las métricas reales del canal.
        self.anthropic_model = anthropic_model or self.DEFAULT_ANTHROPIC_MODEL
        # Human-readable language label (e.g. "Spanish", "Japanese"). Used in
        # the `Respond in X` instruction at the top of the analysis prompt so
        # `retention_analysis` and `growth_driver` values end up in the
        # creator's language — consistent with the live clip pipeline.
        self.output_language = output_language or "English"

    async def fetch_transcript(self, video_id: str) -> Tuple[Optional[str], str]:
        """Fetch transcript via API first, fall back to yt-dlp + whisper."""
        if YouTubeTranscriptApi:
            try:
                # youtube-transcript-api 1.x dropped the static `get_transcript`
                # in favor of the instance method `fetch`. Snippets now expose
                # attributes (.text/.start/.duration) instead of dict keys.
                ytt = YouTubeTranscriptApi()
                fetched = ytt.fetch(video_id, languages=['es', 'en'])
                text = " ".join([s.text for s in fetched])
                return text.replace('\n', ' ').strip(), "youtube_api"
            except Exception as e:
                logger.warning("YouTube transcript API failed for %s: %s", video_id, e)

        result = await self._transcribe_fallback(video_id)
        return result, "nvidia_parakeet"

    async def _transcribe_fallback(self, video_id: str) -> Optional[str]:
        """Baja el audio con yt-dlp y lo transcribe con NVIDIA Parakeet (Linux)."""
        from packages.core.services.nvidia_asr import transcribe_wav

        temp_dir = tempfile.mkdtemp(prefix="azelia_parakeet_")
        outtmpl = os.path.join(temp_dir, "%(id)s.%(ext)s")
        url = f"https://www.youtube.com/watch?v={video_id}"

        try:
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp",
                "-x",
                "--audio-format",
                "wav",
                "--postprocessor-args",
                "ffmpeg:-ar 16000 -ac 1",
                "--no-playlist",
                "--quiet",
                "--no-warnings",
                "-o",
                outtmpl,
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            wavs = [
                os.path.join(temp_dir, name)
                for name in os.listdir(temp_dir)
                if name.lower().endswith(".wav")
            ]
            if proc.returncode != 0 or not wavs:
                logger.error("yt-dlp failed for %s: %s", video_id, stderr.decode()[:200])
                return None

            return await asyncio.to_thread(transcribe_wav, wavs[0])

        except Exception as e:
            logger.error("NVIDIA Parakeet fallback failed for %s: %s", video_id, e)
            return None
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    async def fetch_youtube_analytics(
        self, creds: Credentials, channel_id: str, video_ids: list[str]
    ) -> dict:
        """
        Fetch exhaustive per-video metrics from YouTube Analytics API.
        Returns a dict: {video_id: {metric: value, ...}}
        """
        try:
            yt_analytics = googleapiclient.discovery.build(
                "youtubeAnalytics", "v2", credentials=creds
            )
        except Exception as e:
            logger.warning("Could not build YouTube Analytics client: %s", e)
            return {}

        analytics_map = {}
        metrics_str = (
            "views,comments,likes,dislikes,shares,"
            "estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
            "subscribersGained,subscribersLost"
        )

        # YouTube Analytics API requires a date range
        start_date = "2020-01-01"
        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Process in batches of 200 video IDs (API filter limit)
        for i in range(0, len(video_ids), 200):
            batch_ids = video_ids[i:i+200]
            filters_str = "video==" + ",".join(batch_ids)

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = yt_analytics.reports().query(
                        ids=f"channel=={channel_id}",
                        startDate=start_date,
                        endDate=end_date,
                        metrics=metrics_str,
                        dimensions="video",
                        filters=filters_str,
                        maxResults=200,
                    ).execute()

                    headers = [h["name"] for h in response.get("columnHeaders", [])]
                    for row in response.get("rows", []):
                        row_dict = dict(zip(headers, row))
                        vid_id = row_dict.pop("video", None)
                        if vid_id:
                            analytics_map[vid_id] = row_dict
                    break  # success

                except Exception as e:
                    error_str = str(e)
                    if "quotaExceeded" in error_str or ("403" in error_str and "quota" in error_str.lower()):
                        logger.warning("YouTube Analytics quota exceeded — stopping sync early after %d videos", len(analytics_map))
                        return analytics_map
                    if attempt < max_retries - 1:
                        import time
                        wait = 2 ** attempt
                        logger.warning("YouTube Analytics batch failed (attempt %d/%d), retrying in %ds: %s", attempt + 1, max_retries, wait, error_str)
                        time.sleep(wait)
                    else:
                        logger.warning("YouTube Analytics batch failed after %d attempts, skipping: %s", max_retries, error_str)

        logger.info("Fetched analytics for %d/%d videos", len(analytics_map), len(video_ids))
        return analytics_map

    async def fetch_retention_curve(
        self, creds: Credentials, channel_id: str, video_id: str
    ) -> list[dict]:
        """Trae la curva de retención de un video (dónde se va la gente).

        YouTube Analytics v2 con dimensión `elapsedVideoTimeRatio`. Devuelve
        la curva normalizada (ver `parse_retention_curve`). Lista vacía si la
        API falla — nunca propaga la excepción (degradación elegante).
        """
        try:
            yt_analytics = googleapiclient.discovery.build(
                "youtubeAnalytics", "v2", credentials=creds
            )
        except Exception as e:
            logger.warning("Could not build YouTube Analytics client for curve: %s", e)
            return []

        start_date = "2020-01-01"
        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            response = yt_analytics.reports().query(
                ids=f"channel=={channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics="audienceWatchRatio,relativeRetentionPerformance",
                dimensions="elapsedVideoTimeRatio",
                filters=f"video=={video_id}",
            ).execute()
        except Exception as e:
            logger.warning("Retention curve fetch failed for %s: %s", video_id, e)
            return []
        return parse_retention_curve(response)

    async def _call_anthropic(self, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> str:
        """Direct Anthropic call using the chosen model.

        Historical analysis deliberately uses its own model choice (Haiku by default)
        so the user can trade cost vs. quality without changing the global `anthropic_model`
        that drives the live clips pipeline.
        """
        from packages.core.config import settings as _settings

        api_key = getattr(_settings, "anthropic_api_key", "") or ""
        if not api_key:
            raise RuntimeError("Anthropic API key not configured — retroactive sync needs Anthropic.")

        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise RuntimeError(f"anthropic SDK not installed: {e}")

        client = Anthropic(api_key=api_key)
        # Anthropic SDK is sync; wrap in a thread to avoid blocking the event loop.
        def _run():
            resp = client.messages.create(
                model=self.anthropic_model,
                max_tokens=1500,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return resp.content[0].text if resp.content else ""

        return await asyncio.to_thread(_run)

    async def _complete(self, system_prompt: str, user_prompt: str) -> str:
        """Etiqueta con el modelo histórico si hay clave de Anthropic; si no,
        con el LLM ya configurado (Claude Code). Sin ninguno, no inventa la etiqueta."""
        from packages.core.config import settings as _settings

        if (getattr(_settings, "anthropic_api_key", "") or "").strip():
            return await self._call_anthropic(system_prompt, user_prompt, temperature=0.1)
        llm = get_llm()
        return await asyncio.to_thread(llm.chat, system_prompt, user_prompt, 0.1)

    def _open_shorts_db(self):
        """Abre la SQLite del canal y aplica las migraciones de analytics."""
        from server.routes import analytics as analytics_routes

        target = os.path.abspath(self.YT_DB_PATH)
        previous = analytics_routes.YT_DB_PATH
        analytics_routes.YT_DB_PATH = Path(target)
        try:
            return analytics_routes._get_yt_db()
        finally:
            analytics_routes.YT_DB_PATH = previous

    async def analyze_video(self, video: dict) -> Optional[dict]:
        """Fetches transcript and prompts LLM for IC analysis (Stage 1: Structural Extraction)."""
        video_id = video.get("video_id")
        title = video.get("title", "")
        metrics = video.get("metrics", {})
        analytics = video.get("analytics", {})

        transcript, source = await self.fetch_transcript(video_id)
        if not transcript:
            logger.warning("No transcript for historical video %s", video_id)
            return None

        logger.info("Analyzing historical short %s (transcript via %s)...", video_id, source)

        # Detect language per-video. youtube-transcript-api requests captions in
        # `['es','en']` order so for non-Latin podcasts we'd otherwise label
        # everything Spanish. With detection the LLM writes `retention_analysis`
        # and `growth_driver` in the actual language of the short.
        from packages.core.utils import detect_language as _detect_lang
        from packages.core.utils import language_label as _lang_label
        per_video_lang = _lang_label(_detect_lang(transcript, fallback="en"))

        # Build rich metrics context for the LLM
        metrics_context = ""
        if metrics or analytics:
            metrics_context = "\n\nMÉTRICAS DE RENDIMIENTO:"
            if metrics.get("views"):
                metrics_context += f"\n- Vistas: {metrics['views']:,}"
            if metrics.get("likes"):
                metrics_context += f"\n- Likes: {metrics['likes']:,}"
            if metrics.get("comments"):
                metrics_context += f"\n- Comentarios: {metrics['comments']:,}"
            if analytics.get("averageViewPercentage"):
                metrics_context += f"\n- Retención Promedio: {analytics['averageViewPercentage']:.1f}%"
            if analytics.get("averageViewDuration"):
                metrics_context += f"\n- Duración Promedio de Vista: {analytics['averageViewDuration']:.1f}s"
            if analytics.get("shares"):
                metrics_context += f"\n- Compartidos: {analytics['shares']:,}"
            if analytics.get("subscribersGained"):
                metrics_context += f"\n- Suscriptores Ganados: {analytics['subscribersGained']:,}"
            if analytics.get("subscribersLost"):
                metrics_context += f"\n- Suscriptores Perdidos: {analytics['subscribersLost']:,}"
            if analytics.get("estimatedMinutesWatched"):
                metrics_context += f"\n- Minutos Totales Vistos: {analytics['estimatedMinutesWatched']:.1f}"

        system_prompt = f"""You are an audience analyst specialised in YouTube Shorts.

⚠️ OUTPUT LANGUAGE: Respond in {per_video_lang}. The free-text fields
(`retention_analysis`, `growth_driver`, and each `core_topics` entry) MUST be
written in {per_video_lang}. The enum values for `hook_type`,
`emotional_charge`, and `episode_format` stay in English as shown.

Analyze this historical YouTube Short by combining its transcript with the real
performance metrics. Return ONLY a JSON object with these fields (no markdown,
no prose):
{{
  "hook_type": "question|storytelling|surprising_fact|controversial_statement|negative_frame|tutorial|weak",
  "emotional_charge": "inspirational|urgent|comedic|outrage|educational|empathetic",
  "engagement_potential": 1-10,
  "core_topics": ["topic1", "topic2"],
  "episode_format": "solo|interview|co_host|panel|narrative",
  "retention_analysis": "One sentence explaining why this video did or did not retain the audience",
  "growth_driver": "One sentence about whether this video attracted subscribers and why"
}}"""

        user_prompt = f"Original Title: {title}{metrics_context}\n\nTRANSCRIPT:\n{transcript}"

        try:
            result_json = await self._complete(system_prompt, user_prompt)

            # Strip markdown fences if present
            if result_json.startswith("```"):
                result_json = result_json.strip()
                if '\n' in result_json:
                    result_json = result_json.split('\n', 1)[1]
                if result_json.endswith("```"):
                    result_json = result_json[:-3]

            analysis = json.loads(result_json.strip())

            return {
                "video_id": video_id,
                "title": title,
                "analysis": analysis,
                "performance": metrics,
                "analytics": analytics,
            }

        except Exception as e:
            logger.error("LLM analysis failed for %s: %s", video_id, e)
            return None

    async def process_historical_shorts(
        self, user_id: str, channel_id: str, access_token: str, max_videos: int = 50,
        job_id: str = None,
    ) -> dict:
        """
        Backward analysis of YouTube Shorts:
        1. Fetch shorts metadata from YouTube Data API
        2. Fetch exhaustive analytics from YouTube Analytics API
        3. Analyze each short (transcript + metrics -> LLM Stage 1)
        4. Store results in local SQLite (Local Intelligence)
        5. (Future) Sink into Collective Intelligence telemetry
        """
        # Optional JobStore for progress reporting
        _store = None
        if job_id:
            try:
                from server.workers.job_store import get_job_store
                _store = get_job_store()
            except Exception:
                pass

        def _report(progress: int, message: str):
            if _store and job_id:
                _store.update_progress(job_id, progress, message)
            logger.info(message)

        _report(2, "🔍 Buscando canal en YouTube...")
        creds = Credentials(token=access_token)
        youtube = googleapiclient.discovery.build("youtube", "v3", credentials=creds)

        logger.info("Scanning channel %s up to %d shorts...", channel_id, max_videos)

        # Find uploads playlist
        channel_response = youtube.channels().list(
            part='contentDetails', id=channel_id
        ).execute()

        if not channel_response.get('items'):
            raise ValueError("Channel not found.")

        uploads_playlist_id = (
            channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
        )

        # Fetch videos (paginate to get up to max_videos)
        videos_data = []
        next_page_token = None
        while len(videos_data) < max_videos:
            playlist_response = youtube.playlistItems().list(
                part='contentDetails',
                playlistId=uploads_playlist_id,
                maxResults=min(max_videos - len(videos_data), 50),
                pageToken=next_page_token,
            ).execute()

            for item in playlist_response.get('items', []):
                videos_data.append({"video_id": item['contentDetails']['videoId']})

            next_page_token = playlist_response.get('nextPageToken')
            if not next_page_token:
                break

        _report(5, f"📋 {len(videos_data)} videos encontrados en el canal.")

        if not videos_data:
            return {"status": "success", "processed": 0, "message": "No videos found"}

        # Fetch stats in bulk
        vid_ids = [v["video_id"] for v in videos_data]
        stats_map = {}
        for i in range(0, len(vid_ids), 50):
            batch = vid_ids[i:i+50]
            stats_response = youtube.videos().list(
                part="statistics,snippet,contentDetails,status", id=",".join(batch)
            ).execute()

            for s in stats_response.get("items", []):
                stats_map[s["id"]] = {
                    "title": s["snippet"]["title"],
                    "duration": s["contentDetails"]["duration"],
                    "published_at": s["snippet"].get("publishedAt", ""),
                    "privacy_status": (s.get("status") or {}).get("privacyStatus"),
                    "metrics": {
                        "views": int(s["statistics"].get("viewCount", 0)),
                        "likes": int(s["statistics"].get("likeCount", 0)),
                        "comments": int(s["statistics"].get("commentCount", 0)),
                    },
                }

        # ─── YouTube Analytics API: Fetch exhaustive per-video metrics ───
        short_ids = []
        for v in videos_data:
            v_id = v["video_id"]
            if v_id in stats_map:
                duration_delta = isodate.parse_duration(stats_map[v_id]["duration"])
                if duration_delta.total_seconds() <= 65:
                    short_ids.append(v_id)

        _report(15, f"🎬 {len(short_ids)} shorts detectados. Obteniendo analíticas de YouTube...")
        analytics_map = await self.fetch_youtube_analytics(creds, channel_id, short_ids)
        _report(25, "📊 Analíticas obtenidas. Guardando métricas reales...")

        db_path = os.path.abspath(self.YT_DB_PATH)
        conn = self._open_shorts_db()
        try:
            for v_id in short_ids:
                stat_data = stats_map[v_id]
                duration_delta = isodate.parse_duration(stat_data["duration"])
                upsert_short_performance(conn, user_id, {
                    "video_id": v_id,
                    "title": stat_data["title"],
                    "published_at": stat_data.get("published_at") or None,
                    "duration_seconds": int(duration_delta.total_seconds()),
                    "privacy_status": stat_data.get("privacy_status"),
                    "views": stat_data["metrics"].get("views", 0),
                    "likes": stat_data["metrics"].get("likes", 0),
                    "comments": stat_data["metrics"].get("comments", 0),
                    "analytics": analytics_map.get(v_id, {}),
                })
                existing_curve = conn.execute(
                    "SELECT 1 FROM retention_curves WHERE video_id=? AND user_id=?",
                    (v_id, user_id),
                ).fetchone()
                if existing_curve:
                    continue
                curve = await self.fetch_retention_curve(creds, channel_id, v_id)
                if curve:
                    store_retention_curve(conn, v_id, curve, user_id=user_id)
            conn.commit()

            # Las métricas se refrescan siempre. El LLM solo corre en shorts
            # sin etiqueta, para no volver a cobrar lo ya analizado.
            to_label = pending_label_ids(conn, user_id, short_ids)
            already = len(short_ids) - len(to_label)
            if already:
                _report(26, f"⏭️  {already} shorts ya etiquetados conservan su análisis. Métricas actualizadas.")

            can_label, label_reason = labeling_available()
            if not can_label:
                logger.warning("Historical labels skipped: %s", label_reason)
                _report(40, label_reason)

            if _store and job_id:
                _store.set_total_clips(job_id, len(to_label))

            processed_count = 0
            failed_count = 0
            if can_label:
                for index, v_id in enumerate(to_label):
                    stat_data = stats_map[v_id]
                    analytics_data = analytics_map.get(v_id, {})
                    full_vid_data = {
                        "video_id": v_id,
                        "title": stat_data["title"],
                        "metrics": stat_data["metrics"],
                        "analytics": analytics_data,
                    }
                    video_progress = 25 + int(index / max(len(to_label), 1) * 65)
                    _report(
                        video_progress,
                        f"🧠 Analizando {index + 1}/{len(to_label)}: {stat_data['title'][:40]}...",
                    )
                    result = await self.analyze_video(full_vid_data)
                    if not result:
                        failed_count += 1
                        continue
                    try:
                        store_short_labels(conn, user_id, v_id, result["analysis"])
                        conn.commit()
                        processed_count += 1
                        logger.info("Stored labels for %s", v_id)
                    except Exception as e:
                        failed_count += 1
                        logger.error("Failed to store labels for %s: %s", v_id, e)

            from packages.core.services.creator_self import refresh_creator_self_snapshot

            snapshot = refresh_creator_self_snapshot(
                conn, user_id, snapshot_path=snapshot_path_for(db_path, user_id)
            )
        finally:
            conn.close()
        _report(
            100,
            f"✅ Snapshot creator_self: {snapshot['signals_written']} señales, "
            f"retención en {snapshot['shorts_with_retention']} shorts",
        )

        return {
            "status": "success",
            "processed": processed_count,
            "failed": failed_count,
            "total_evaluated": len(to_label),
            "metrics_refreshed": len(short_ids),
            "analytics_fetched": len(analytics_map),
            "labeling_skipped": None if can_label else label_reason,
            "creator_self": snapshot,
        }
