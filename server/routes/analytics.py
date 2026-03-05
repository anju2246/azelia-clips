"""
Server Routes — Platform Analytics & YouTube OAuth
"""

import os
import glob
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException, Form, Header, Body

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
        detail="Missing client_secrets.json. Download from Google Cloud Console and place in private/ folder."
    )


# ─── Personal Intelligence Insights ─────────────────────────────────────────

@router.get("/analytics/insights")
async def get_analytics_insights(authorization: str = Header(None)):
    """
    Aggregate insights from the local job store for Personal Intelligence.
    Returns stats about processed episodes and generated clips.
    """
    from server.workers.job_store import get_job_store
    
    store = get_job_store()
    
    try:
        # Query all completed jobs from SQLite
        conn = store._get_conn()
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
    except Exception as e:
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
    """Get or create the YouTube shorts database."""
    YT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(YT_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS youtube_shorts (
            video_id TEXT PRIMARY KEY,
            title TEXT,
            published_at TEXT,
            duration_seconds INTEGER,
            view_count INTEGER DEFAULT 0,
            like_count INTEGER DEFAULT 0,
            comment_count INTEGER DEFAULT 0,
            channel_name TEXT,
            channel_id TEXT,
            thumbnail_url TEXT,
            synced_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS youtube_sync_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    return conn


@router.get("/analytics/youtube/status")
async def get_youtube_status():
    """Check if YouTube shorts have been synced."""
    try:
        conn = _get_yt_db()
        cursor = conn.execute("SELECT COUNT(*) FROM youtube_shorts")
        count = cursor.fetchone()[0]
        
        cursor2 = conn.execute("SELECT value FROM youtube_sync_meta WHERE key = 'channel_name'")
        row = cursor2.fetchone()
        channel_name = row[0] if row else None
        
        cursor3 = conn.execute("SELECT value FROM youtube_sync_meta WHERE key = 'last_synced'")
        row3 = cursor3.fetchone()
        last_synced = row3[0] if row3 else None
        
        conn.close()
        return {
            "connected": count > 0,
            "channel_name": channel_name,
            "total_shorts": count,
            "last_synced": last_synced,
        }
    except Exception:
        return {"connected": False, "total_shorts": 0}


@router.post("/analytics/youtube/sync")
async def sync_youtube_shorts(body: dict = Body(...)):
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
    channel_res = requests.get(f"{YT_API}/channels", params={
        "part": "snippet,contentDetails,statistics",
        "mine": "true"
    }, headers=headers)
    
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
        batch = all_video_ids[i:i+50]
        video_res = requests.get(f"{YT_API}/videos", params={
            "part": "snippet,contentDetails,statistics",
            "id": ",".join(batch)
        }, headers=headers)
        
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
            
            shorts.append({
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
            })
    
    # Step 4: Store in SQLite
    conn = _get_yt_db()
    now = datetime.now().isoformat()
    
    for s in shorts:
        conn.execute("""
            INSERT OR REPLACE INTO youtube_shorts 
            (video_id, title, published_at, duration_seconds, view_count, like_count, 
             comment_count, channel_name, channel_id, thumbnail_url, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            s["video_id"], s["title"], s["published_at"], s["duration_seconds"],
            s["view_count"], s["like_count"], s["comment_count"],
            s["channel_name"], s["channel_id"], s["thumbnail_url"], now
        ))
    
    # Save sync metadata
    conn.execute("INSERT OR REPLACE INTO youtube_sync_meta (key, value) VALUES ('channel_name', ?)", (channel_name,))
    conn.execute("INSERT OR REPLACE INTO youtube_sync_meta (key, value) VALUES ('channel_id', ?)", (channel_id,))
    conn.execute("INSERT OR REPLACE INTO youtube_sync_meta (key, value) VALUES ('last_synced', ?)", (now,))
    conn.commit()
    conn.close()
    
    return {
        "total_shorts": len(shorts),
        "total_videos_scanned": len(all_video_ids),
        "channel_name": channel_name,
    }


@router.get("/analytics/youtube/insights")
async def get_youtube_insights():
    """Aggregate insights from synced YouTube Shorts data."""
    try:
        conn = _get_yt_db()
        
        # Basic totals
        cursor = conn.execute("""
            SELECT 
                COUNT(*) as total,
                COALESCE(SUM(view_count), 0) as total_views,
                COALESCE(SUM(like_count), 0) as total_likes,
                COALESCE(AVG(view_count), 0) as avg_views,
                COALESCE(AVG(duration_seconds), 0) as avg_duration
            FROM youtube_shorts
        """)
        row = cursor.fetchone()
        total = row[0]; total_views = row[1]; total_likes = row[2]
        avg_views = row[3]; avg_duration = row[4]
        
        if total == 0:
            conn.close()
            return {"total_shorts": 0, "total_views": 0, "total_likes": 0,
                    "avg_views": 0, "avg_duration": 0, "best_performing": [],
                    "duration_breakdown": []}
        
        # Top 10 performing shorts
        best_cursor = conn.execute("""
            SELECT title, view_count, video_id
            FROM youtube_shorts
            ORDER BY view_count DESC
            LIMIT 10
        """)
        best_performing = [
            {"title": r[0], "views": r[1], "url": f"https://youtube.com/shorts/{r[2]}"}
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
            dc = conn.execute("""
                SELECT COUNT(*), COALESCE(AVG(view_count), 0)
                FROM youtube_shorts
                WHERE duration_seconds >= ? AND duration_seconds <= ?
            """, (lo, hi))
            dr = dc.fetchone()
            if dr[0] > 0:
                duration_breakdown.append({
                    "range": label,
                    "count": dr[0],
                    "avg_views": int(dr[1])
                })
        
        conn.close()
        
        return {
            "total_shorts": total,
            "total_views": int(total_views),
            "total_likes": int(total_likes),
            "avg_views": int(avg_views),
            "avg_duration": round(avg_duration, 1),
            "best_performing": best_performing,
            "duration_breakdown": duration_breakdown,
        }
    except Exception:
        return {"total_shorts": 0, "total_views": 0, "total_likes": 0,
                "avg_views": 0, "avg_duration": 0, "best_performing": [],
                "duration_breakdown": []}


def _parse_iso_duration(duration: str) -> int:
    """Parse ISO 8601 duration (PT1M30S) to seconds."""
    import re
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


# ─── Platform Connections ────────────────────────────────────────────────────

@router.get("/connections/youtube")
async def get_youtube_connection_status(authorization: str = Header(None)):
    """Check if YouTube is connected for the current user."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    
    token = authorization.replace("Bearer ", "").strip()
    
    try:
        from server.services.analytics import AnalyticsSync
        analytics = AnalyticsSync(auth_token=token)
        
        if not analytics.Enabled:
            return {"is_connected": False}
        
        # Try to fetch the connection from user_connections table
        res = analytics.client.table("user_connections")\
            .select("*")\
            .eq("platform", "youtube")\
            .maybeSingle()\
            .execute()
        
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
async def connect_platform_endpoint(platform: str, authorization: str = Header(None)):
    """Connect a social platform."""
    from server.services.analytics import AnalyticsSync
    
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
        
    token = authorization.replace("Bearer ", "").strip()
    analytics = AnalyticsSync(auth_token=token)
    
    if not analytics.Enabled:
        raise HTTPException(status_code=500, detail="Analytics service not enabled (check Supabase config)")
        
    success = analytics.connect_platform(platform)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to connect platform")
        
    return {"status": "connected", "platform": platform}


# ─── YouTube Analytics CSV Upload ────────────────────────────────────────────

@router.post("/analytics/upload-csv")
async def upload_analytics_csv(
    file: UploadFile = File(...),
    authorization: str = Header(None)
):
    """Upload and process YouTube Analytics CSV."""
    from server.sources.youtube_analytics import YouTubeAnalyticsParser
    
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
        
    token = authorization.replace("Bearer ", "").strip()
    
    if not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="Invalid file type. Only CSV supported.")
        
    try:
        content = await file.read()
        parser = YouTubeAnalyticsParser(auth_token=token)
        
        if not parser.enabled:
             raise HTTPException(status_code=500, detail="Analytics service not enabled")
             
        stats = parser.parse_and_sync(content)
        return stats
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── YouTube API Fetch ───────────────────────────────────────────────────────

@router.post("/analytics/fetch-youtube")
async def fetch_youtube_analytics(
    provider_token: str = Form(...),
    authorization: str = Header(None)
):
    """
    Fetch real-time analytics from YouTube Data API using the user's Google Access Token.
    Updates 'user_connections' and matches videos to 'clips_metadata'.
    """
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from server.services.analytics import AnalyticsSync
    
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    
    # Setup Supabase Client (to save results)
    token = authorization.replace("Bearer ", "").strip()
    analytics = AnalyticsSync(auth_token=token)
    if not analytics.Enabled:
         raise HTTPException(status_code=500, detail="Analytics service not enabled")

    try:
        # Initialize YouTube Client
        creds = Credentials(token=provider_token)
        youtube = build('youtube', 'v3', credentials=creds)
        
        # Get Channel Stats
        channel_resp = youtube.channels().list(mine=True, part='snippet,statistics').execute()
        if not channel_resp.get('items'):
             raise HTTPException(status_code=404, detail="No YouTube channel found for this user")
             
        channel = channel_resp['items'][0]
        channel_id = channel['id']
        channel_title = channel['snippet']['title']
        
        # Update Connection Status
        analytics.connect_platform("youtube", metadata={
            "channel_id": channel_id,
            "title": channel_title,
            "thumbnails": channel['snippet']['thumbnails'],
            "statistics": channel['statistics']
        })
        
        # Get Recent Videos
        uploads_playlist_id = channel['contentDetails']['relatedPlaylists']['uploads']
        
        videos_resp = youtube.playlistItems().list(
            playlistId=uploads_playlist_id,
            part='snippet',
            maxResults=50
        ).execute()
        
        video_ids = [item['snippet']['resourceId']['videoId'] for item in videos_resp.get('items', [])]
        
        # Get stats for these videos
        stats_resp = youtube.videos().list(
            id=','.join(video_ids),
            part='snippet,statistics'
        ).execute()
        
        matched_count = 0
        
        # Sync Video Stats to Clips
        for vid in stats_resp.get('items', []):
            title = vid['snippet']['title']
            stats = vid['statistics']
            
            metrics = {
                "platform": "youtube",
                "youtube_id": vid['id'],
                "views": int(stats.get('viewCount', 0)),
                "likes": int(stats.get('likeCount', 0)),
                "comments": int(stats.get('commentCount', 0)),
                "last_updated": "now()"
            }
            
            res = analytics.client.table("clips_metadata")\
                .update({"performance_metrics": metrics})\
                .eq("video_title", title)\
                .execute()
                
            if res.data:
                matched_count += 1
                
        return {
            "status": "success", 
            "channel": channel_title, 
            "videos_scanned": len(video_ids),
            "clips_matched": matched_count
        }

    except Exception as e:
        print(f"YouTube Fetch Error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# ─── YouTube OAuth Flow ──────────────────────────────────────────────────────

@router.get("/auth/youtube/authorize")
async def authorize_youtube(
    redirect_uri: str,
    authorization: str = Header(None)
):
    """
    Start OAuth flow for YouTube connection (resource-only).
    Returns the Google authorization URL.
    """
    from google_auth_oauthlib.flow import Flow
    
    try:
        secrets_file = _find_client_secrets()

        flow = Flow.from_client_secrets_file(
            secrets_file,
            scopes=['https://www.googleapis.com/auth/youtube.readonly'],
            redirect_uri=redirect_uri
        )
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            prompt='consent',
            include_granted_scopes='true'
        )
        
        return {"url": authorization_url}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auth/youtube/callback")
async def callback_youtube(
    code: str = Body(..., embed=True),
    redirect_uri: str = Body(..., embed=True),
    authorization: str = Header(None)
):
    """
    Exchange authorization code for tokens and link to current user.
    """
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    from server.services.analytics import AnalyticsSync
    
    if not authorization:
         raise HTTPException(status_code=401, detail="User must be logged in to link account")
         
    token = authorization.replace("Bearer ", "").strip()
    analytics = AnalyticsSync(auth_token=token)
    
    try:
        secrets_file = _find_client_secrets()
        flow = Flow.from_client_secrets_file(
            secrets_file,
            scopes=['https://www.googleapis.com/auth/youtube.readonly'],
            redirect_uri=redirect_uri
        )
        
        flow.fetch_token(code=code)
        creds = flow.credentials
        
        # Use credentials to get channel info
        youtube = build('youtube', 'v3', credentials=creds)
        
        channel_resp = youtube.channels().list(mine=True, part='snippet,statistics').execute()
        if not channel_resp.get('items'):
             raise HTTPException(status_code=404, detail="No YouTube channel found")
             
        channel = channel_resp['items'][0]
        
        # Save connection
        analytics.connect_platform("youtube", metadata={
            "channel_id": channel['id'],
            "title": channel['snippet']['title'],
            "thumbnails": channel['snippet']['thumbnails'],
            "statistics": channel['statistics'],
            "refresh_token": creds.refresh_token,
            "access_token": creds.token
        })
        
        return {"status": "success", "channel": channel['snippet']['title']}
        
    except Exception as e:
        print(f"OAuth Callback Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
