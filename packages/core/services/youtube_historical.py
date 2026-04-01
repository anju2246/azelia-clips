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

from packages.core.services.telemetry import TelemetryService
from packages.core.llm_provider import get_llm

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

    def __init__(self, telemetry_service: TelemetryService):
        self.telemetry = telemetry_service
        self.llm = get_llm()

    async def fetch_transcript(self, video_id: str) -> Tuple[Optional[str], str]:
        """Fetch transcript via API first, fall back to yt-dlp + whisper."""
        if YouTubeTranscriptApi:
            try:
                transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['es', 'en'])
                text = " ".join([seg['text'] for seg in transcript])
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

            except Exception as e:
                logger.warning("YouTube Analytics query failed for batch: %s", e)
                continue

        logger.info("Fetched analytics for %d/%d videos", len(analytics_map), len(video_ids))
        return analytics_map

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

        system_prompt = """Eres un Analista de Audiencias experto en YouTube Shorts.
Analiza este YouTube Short histórico combinando su transcripción con las métricas de rendimiento reales.
Devuelve SOLO un JSON con estos campos (sin markdown, sin explicación):
{
  "hook_type": "question|storytelling|surprising_fact|controversial_statement|negative_frame|tutorial|weak",
  "emotional_charge": "inspirational|urgent|comedic|outrage|educational|empathetic",
  "engagement_potential": 1-10,
  "core_topics": ["topic1", "topic2"],
  "episode_format": "solo|interview|co_host|panel|narrative",
  "retention_analysis": "Una frase explicando por qué este video retuvo o no a la audiencia",
  "growth_driver": "Una frase sobre si este video atrajo suscriptores y por qué"
}"""

        user_prompt = f"Título Original: {title}{metrics_context}\n\nTRANSCRIPT:\n{transcript}"

        try:
            result_json = await self.llm.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,
            )

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
        _report(25, f"📊 Analíticas obtenidas. Iniciando análisis con IA...")

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
                    UPDATE youtube_shorts SET
                        average_view_duration = ?,
                        average_view_percentage = ?,
                        shares_count = ?,
                        subscribers_gained = ?,
                        subscribers_lost = ?,
                        estimated_minutes_watched = ?,
                        hook_type = ?,
                        emotional_charge = ?,
                        core_topics = ?,
                        llm_analysis = ?
                    WHERE video_id = ? AND user_id = ?
                """, (
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
                    v_id,
                    user_id,
                ))
                conn.commit()
                conn.close()
                logger.info("✅ Stored analysis for %s in local DB", v_id)
            except Exception as e:
                logger.error("Failed to store analysis for %s: %s", v_id, e)

            # ─── Telemetry (Safe Switch) ───
            if self.SUPABASE_SYNC_ENABLED:
                self.telemetry.track_youtube_performance(
                    user_id=user_id,
                    youtube_id=v_id,
                    views=metrics.get("views", 0),
                    likes=metrics.get("likes", 0),
                    comments=metrics.get("comments", 0),
                    duration_seconds=duration_delta.total_seconds(),
                    hook_type=analysis.get("hook_type"),
                    predicted_score=analysis.get("engagement_potential"),
                    category=analysis.get("core_topics", ["General"])[0] if analysis.get("core_topics") else "General",
                    episode_format=analysis.get("episode_format", "solo"),
                )
            else:
                logger.info("📦 Supabase sync paused (Local Intelligence mode). Data stored locally only.")

            processed_count += 1

        return {
            "status": "success",
            "processed": processed_count,
            "failed": failed_count,
            "total_evaluated": len(short_ids),
            "analytics_fetched": len(analytics_map),
        }
