import os
import json
import logging
import tempfile
import asyncio
from typing import Optional, Tuple
from datetime import datetime, timezone

import isodate
import sqlite3
import googleapiclient.discovery
from google.oauth2.credentials import Credentials

# NOTE: TelemetryService removed in local-first MVP (v0.1.0).
# This module is currently unused — YouTube historical sync returns 501.
# Re-enable in v0.1.1 with local-only persistence (no central telemetry).
from packages.core.llm_provider import get_llm  # noqa: F401

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None

logger = logging.getLogger(__name__)


class YouTubeHistoricalExtractor:
    """
    Analyzes historical YouTube Shorts to cold-start the Collective Intelligence Dashboard.
    Uses youtube_transcript_api with yt-dlp + mlx-whisper as fallback.
    """

    WHISPER_MODEL = "mlx-community/whisper-tiny"
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
        self.llm = get_llm()
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
        return result, "whisper_fallback"

    async def _transcribe_fallback(self, video_id: str) -> Optional[str]:
        """Downloads audio with yt-dlp and transcribes with mlx-whisper."""
        try:
            import mlx_whisper
        except ImportError:
            logger.error("mlx-whisper not installed — cannot use whisper fallback. Install with: pip install 'azelia-clips[asr-mlx]'")
            return None

        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, f"{video_id}.mp3")
        url = f"https://www.youtube.com/watch?v={video_id}"

        try:
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp",
                "--extract-audio", "--audio-format", "mp3",
                "--audio-quality", "5", "--no-playlist",
                "--quiet", "--no-warnings",
                "-o", output_path, url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()

            if proc.returncode != 0 or not os.path.exists(output_path):
                logger.error("yt-dlp failed for %s: %s", video_id, stderr.decode()[:200])
                return None

            result = mlx_whisper.transcribe(
                output_path, path_or_hf_repo=self.WHISPER_MODEL, verbose=False
            )
            return result.get("text", "").strip() or None

        except Exception as e:
            logger.error("Fallback transcription error for %s: %s", video_id, e)
            return None
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)
            if os.path.exists(temp_dir):
                os.rmdir(temp_dir)

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
        from packages.core.utils import detect_language as _detect_lang, language_label as _lang_label
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
            result_json = await self._call_anthropic(system_prompt, user_prompt, temperature=0.1)

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
                part="statistics,snippet,contentDetails", id=",".join(batch)
            ).execute()

            for s in stats_response.get("items", []):
                stats_map[s["id"]] = {
                    "title": s["snippet"]["title"],
                    "duration": s["contentDetails"]["duration"],
                    "published_at": s["snippet"].get("publishedAt", ""),
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
        _report(25, f"📊 Analíticas obtenidas. Filtrando shorts ya analizados...")

        # Skip shorts that already have an LLM analysis in our local SQLite —
        # re-running historical sync should NEVER re-bill the creator for
        # content we already processed.
        try:
            _abspath = os.path.abspath(self.YT_DB_PATH)
            _c = sqlite3.connect(_abspath)
            placeholders = ",".join(["?"] * len(short_ids)) if short_ids else ""
            if placeholders:
                _rows = _c.execute(
                    f"SELECT video_id FROM youtube_shorts WHERE user_id=? AND video_id IN ({placeholders}) AND llm_analysis IS NOT NULL AND llm_analysis != ''",
                    (user_id, *short_ids),
                ).fetchall()
                _analyzed = {r[0] for r in _rows}
            else:
                _analyzed = set()
            _c.close()
            if _analyzed:
                short_ids = [v for v in short_ids if v not in _analyzed]
                _report(26, f"⏭️  Saltando {len(_analyzed)} shorts ya analizados. Quedan {len(short_ids)}.")
        except Exception as _filter_err:
            logger.warning("Could not filter already-analyzed shorts: %s", _filter_err)

        # Set total in JobStore for accurate percentage
        if _store and job_id:
            _store.set_total_clips(job_id, len(short_ids))

        # ─── Process each short ───
        processed_count = 0
        failed_count = 0
        db_path = os.path.abspath(self.YT_DB_PATH)

        for v_id in short_ids:
            if v_id not in stats_map:
                continue

            stat_data = stats_map[v_id]
            duration_delta = isodate.parse_duration(stat_data["duration"])
            analytics_data = analytics_map.get(v_id, {})

            full_vid_data = {
                "video_id": v_id,
                "title": stat_data["title"],
                "metrics": stat_data["metrics"],
                "analytics": analytics_data,
            }

            # Report per-video progress (25% to 95% range)
            video_progress = 25 + int((processed_count + failed_count) / max(len(short_ids), 1) * 70)
            _report(video_progress, f"🧠 Analizando {processed_count + failed_count + 1}/{len(short_ids)}: {stat_data['title'][:40]}...")

            result = await self.analyze_video(full_vid_data)
            if not result:
                failed_count += 1
                continue

            analysis = result["analysis"]
            metrics = result["performance"]
            vid_analytics = result.get("analytics", {})

            # ─── Store in local SQLite (Local Intelligence) ───
            try:
                conn = sqlite3.connect(db_path)
                conn.execute("""
                    INSERT INTO youtube_shorts
                        (video_id, user_id, title, duration_seconds,
                         view_count, like_count, comment_count,
                         average_view_duration, average_view_percentage,
                         shares_count, subscribers_gained, subscribers_lost,
                         estimated_minutes_watched,
                         hook_type, emotional_charge, core_topics, llm_analysis,
                         synced_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(video_id, user_id) DO UPDATE SET
                        average_view_duration = excluded.average_view_duration,
                        average_view_percentage = excluded.average_view_percentage,
                        shares_count = excluded.shares_count,
                        subscribers_gained = excluded.subscribers_gained,
                        subscribers_lost = excluded.subscribers_lost,
                        estimated_minutes_watched = excluded.estimated_minutes_watched,
                        hook_type = excluded.hook_type,
                        emotional_charge = excluded.emotional_charge,
                        core_topics = excluded.core_topics,
                        llm_analysis = excluded.llm_analysis,
                        synced_at = excluded.synced_at
                """, (
                    v_id,
                    user_id,
                    stat_data["title"],
                    int(duration_delta.total_seconds()),
                    metrics.get("views", 0),
                    metrics.get("likes", 0),
                    metrics.get("comments", 0),
                    vid_analytics.get("averageViewDuration"),
                    vid_analytics.get("averageViewPercentage"),
                    vid_analytics.get("shares", 0),
                    vid_analytics.get("subscribersGained", 0),
                    vid_analytics.get("subscribersLost", 0),
                    vid_analytics.get("estimatedMinutesWatched"),
                    analysis.get("hook_type"),
                    analysis.get("emotional_charge"),
                    json.dumps(analysis.get("core_topics", []), ensure_ascii=False),
                    json.dumps(analysis, ensure_ascii=False),
                ))
                conn.commit()
                conn.close()
                logger.info("✅ Stored analysis for %s in local DB", v_id)
            except Exception as e:
                logger.error("Failed to store analysis for %s: %s", v_id, e)

            # Telemetry removed in local-first MVP — data stays in local SQLite.
            logger.info("Stored locally (telemetry disabled in v0.1.0).")

            processed_count += 1

        return {
            "status": "success",
            "processed": processed_count,
            "failed": failed_count,
            "total_evaluated": len(short_ids),
            "analytics_fetched": len(analytics_map),
        }
