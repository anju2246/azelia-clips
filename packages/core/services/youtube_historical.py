import os
import json
import logging
import tempfile
import asyncio
from typing import Optional, Tuple
from datetime import datetime, timezone

import isodate
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

    async def analyze_video(self, video: dict) -> Optional[dict]:
        """Fetches transcript and prompts LLM for IC analysis."""
        video_id = video.get("video_id")
        title = video.get("title", "")

        transcript, source = await self.fetch_transcript(video_id)
        if not transcript:
            logger.warning("No transcript for historical video %s", video_id)
            return None

        logger.info("Analyzing historical short %s (transcript via %s)...", video_id, source)

        system_prompt = """Eres un Analista de Audiencias.
Analiza este YouTube Short histórico para extraer sus patrones de retención.
Devuelve SOLO un JSON con estos campos (sin markdown):
{
  "hook_type": "question|storytelling|surprising_fact|controversial_statement|negative_frame|tutorial|weak",
  "emotional_charge": "inspirational|urgent|comedic|outrage|educational|empathetic",
  "engagement_potential": 1-10,
  "core_topics": ["topic1", "topic2"],
  "episode_format": "solo|interview|co_host|panel|narrative"
}"""

        user_prompt = f"Título Original: {title}\n\nTRANSCRIPT:\n{transcript}"

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
                "performance": video.get("metrics", {}),
            }

        except Exception as e:
            logger.error("LLM analysis failed for %s: %s", video_id, e)
            return None

    async def process_historical_shorts(
        self, user_id: str, channel_id: str, access_token: str, max_videos: int = 50
    ) -> dict:
        """
        Backward analysis of YouTube Shorts:
        1. Fetch shorts metadata from YouTube API
        2. Analyze each short (transcript -> LLM)
        3. Sink into Collective Intelligence telemetry
        """
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

        # Fetch videos
        playlist_response = youtube.playlistItems().list(
            part='contentDetails',
            playlistId=uploads_playlist_id,
            maxResults=min(max_videos, 50),
        ).execute()

        videos_data = [
            {"video_id": item['contentDetails']['videoId']}
            for item in playlist_response.get('items', [])
        ]

        if not videos_data:
            return {"status": "success", "processed": 0, "message": "No videos found"}

        # Fetch stats in bulk
        vid_ids = ",".join(v["video_id"] for v in videos_data)
        stats_response = youtube.videos().list(
            part="statistics,snippet,contentDetails", id=vid_ids
        ).execute()

        stats_map = {}
        for s in stats_response.get("items", []):
            stats_map[s["id"]] = {
                "title": s["snippet"]["title"],
                "duration": s["contentDetails"]["duration"],
                "metrics": {
                    "views": int(s["statistics"].get("viewCount", 0)),
                    "likes": int(s["statistics"].get("likeCount", 0)),
                    "comments": int(s["statistics"].get("commentCount", 0)),
                },
            }

        processed_count = 0
        failed_count = 0

        for video in videos_data:
            v_id = video["video_id"]
            if v_id not in stats_map:
                continue

            full_vid_data = {"video_id": v_id, **stats_map[v_id]}

            # Shorts filter: videos <= 65s
            duration_delta = isodate.parse_duration(full_vid_data["duration"])
            if duration_delta.total_seconds() > 65:
                continue

            result = await self.analyze_video(full_vid_data)
            if not result:
                failed_count += 1
                continue

            analysis = result["analysis"]
            metrics = result["performance"]

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
            processed_count += 1

        return {
            "status": "success",
            "processed": processed_count,
            "failed": failed_count,
            "total_evaluated": len(videos_data),
        }
