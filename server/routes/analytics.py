"""
Server Routes — Platform Analytics & YouTube OAuth
"""

import os
import glob
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException, Form, Header, Body, Request

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
            user_id TEXT,
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
    # Ensure user_id column exists if table was already created
    try:
        conn.execute("ALTER TABLE youtube_shorts ADD COLUMN user_id TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    conn.execute("""
        CREATE TABLE IF NOT EXISTS youtube_sync_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    return conn


@router.get("/analytics/youtube/status")
async def get_youtube_status(request: Request):
    """Check if YouTube shorts have been synced."""
    try:
        user = getattr(request.state, "user", None)
        conn = _get_yt_db()
        
        query = "SELECT COUNT(*) FROM youtube_shorts"
        params = ()
        if user:
            query += " WHERE user_id = ? OR user_id IS NULL"
            params = (user["id"],)
            
        cursor = conn.execute(query, params)
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


@router.post("/analytics/youtube/sync-with-code")
async def sync_youtube_with_code(
    body: dict = Body(...),
    authorization: str = Header(None)
):
    """
    Step 1: Exchange OAuth code for access token, then list available channels.
    Returns the token + list of channels so the user can pick which to sync.
    If channel_id is provided, skip channel selection and sync directly.
    """
    code = body.get("code")
    redirect_uri = body.get("redirect_uri")
    channel_id = body.get("channel_id")  # Optional: skip picker and sync this channel
    access_token = body.get("access_token")  # Optional: reuse existing token
    
    import requests as http_requests
    import json
    
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
        
        token_res = http_requests.post(token_uri, data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
        
        if token_res.status_code != 200:
            import logging
            logging.error(f"YouTube token exchange failed: {token_res.text}")
            error_msg = token_res.json().get("error_description", "Token exchange failed")
            raise HTTPException(status_code=400, detail=f"Failed to exchange code: {error_msg}")
        
        access_token = token_res.json().get("access_token")
        refresh_token = token_res.json().get("refresh_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="No access token received")
            
        if refresh_token:
            conn_db = _get_yt_db()
            conn_db.execute("INSERT OR REPLACE INTO youtube_sync_meta (key, value) VALUES ('refresh_token', ?)", (refresh_token,))
            conn_db.commit()
            conn_db.close()
    
    headers = {"Authorization": f"Bearer {access_token}"}
    YT_API = "https://www.googleapis.com/youtube/v3"
    
    # Authenticate to get user_id & AnalyticsSync
    from server.services.analytics import AnalyticsSync
    user_id = None
    analytics = None
    if authorization:
        try:
            token = authorization.replace("Bearer ", "").strip()
            analytics = AnalyticsSync(auth_token=token)
            import json, base64
            payload = token.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            decoded = json.loads(base64.b64decode(payload))
            user_id = decoded.get("sub")
        except Exception as e:
            print(f"Auth parsing failed: {e}")

    # If channel_id provided, sync directly
    if channel_id:
        result = await _sync_channel(access_token, channel_id, user_id=user_id, analytics=analytics)
        return result
    
    # Otherwise, list all accessible channels for the user to pick
    # 1. Get the default "mine" channel
    channels = []
    mine_res = http_requests.get(f"{YT_API}/channels", params={
        "part": "snippet,statistics,contentDetails",
        "mine": "true"
    }, headers=headers)
    
    if mine_res.status_code == 200:
        for ch in mine_res.json().get("items", []):
            thumb = ch["snippet"].get("thumbnails", {}).get("default", {}).get("url", "")
            channels.append({
                "id": ch["id"],
                "title": ch["snippet"]["title"],
                "handle": ch["snippet"].get("customUrl", ""),
                "subscribers": ch["statistics"].get("subscriberCount", "0"),
                "video_count": ch["statistics"].get("videoCount", "0"),
                "thumbnail": thumb,
            })
    
    # If only 1 channel, sync it automatically
    if len(channels) == 1:
        result = await _sync_channel(access_token, channels[0]["id"], user_id=user_id, analytics=analytics)
        return result
    
    # Multiple channels or none: return them for selection
    return {
        "needs_channel_selection": True,
        "access_token": access_token,
        "channels": channels,
    }


@router.post("/analytics/youtube/auto-sync")
async def auto_sync_youtube(authorization: str = Header(None)):
    """Automatically fetch latest YouTube stats using stored refresh_token."""
    conn = _get_yt_db()
    cursor = conn.execute("SELECT value FROM youtube_sync_meta WHERE key = 'refresh_token'")
    row = cursor.fetchone()
    
    cursor_ch = conn.execute("SELECT value FROM youtube_sync_meta WHERE key = 'channel_id'")
    row_ch = cursor_ch.fetchone()
    conn.close()
    
    if not row or not row_ch:
        raise HTTPException(status_code=400, detail="No refresh token or channel ID found. Please connect manually.")
        
    refresh_token = row[0]
    channel_id = row_ch[0]
    
    import json
    import requests as http_requests
    
    secrets_path = _find_client_secrets()
    with open(secrets_path) as f:
        secrets_data = json.load(f)
    
    client_info = secrets_data.get("web") or secrets_data.get("installed", {})
    client_id = client_info.get("client_id")
    client_secret = client_info.get("client_secret")
    token_uri = client_info.get("token_uri", "https://oauth2.googleapis.com/token")
    
    token_res = http_requests.post(token_uri, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    
    if token_res.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to refresh token")
        
    access_token = token_res.json().get("access_token")
    
    # Authenticate for telemetry
    from server.services.analytics import AnalyticsSync
    user_id = None
    analytics = None
    if authorization:
        try:
            token = authorization.replace("Bearer ", "").strip()
            analytics = AnalyticsSync(auth_token=token)
            import base64
            payload = token.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            decoded = json.loads(base64.b64decode(payload))
            user_id = decoded.get("sub")
        except Exception:
            pass
            
    result = await _sync_channel(access_token, channel_id, user_id=user_id, analytics=analytics)
    return result


async def _sync_channel(access_token: str, channel_id: str, user_id: str = None, analytics = None):
    """Sync all videos from a specific channel by ID."""
    import requests as http_requests
    
    headers = {"Authorization": f"Bearer {access_token}"}
    YT_API = "https://www.googleapis.com/youtube/v3"
    
    # Get channel info
    ch_res = http_requests.get(f"{YT_API}/channels", params={
        "part": "snippet,contentDetails,statistics",
        "id": channel_id
    }, headers=headers)
    
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
        batch = all_video_ids[i:i+50]
        vid_res = http_requests.get(f"{YT_API}/videos", params={
            "part": "snippet,contentDetails,statistics",
            "id": ",".join(batch)
        }, headers=headers)
        
        if vid_res.status_code != 200:
            continue
        
        for video in vid_res.json().get("items", []):
            duration_secs = _parse_iso_duration(video["contentDetails"]["duration"])
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
    
    # Store in SQLite
    conn = _get_yt_db()
    now = datetime.now().isoformat()
    
    # Clear ALL old data — only one channel at a time
    conn.execute("DELETE FROM youtube_shorts")
    conn.execute("DELETE FROM youtube_sync_meta")
    
    # Get User ID from arguments to associate local data
    # (user_id is already passed correctly to _sync_channel)
    
    for s in shorts:
        conn.execute("""
            INSERT OR REPLACE INTO youtube_shorts 
            (video_id, user_id, title, published_at, duration_seconds, view_count, like_count, comment_count, channel_name, channel_id, thumbnail_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (s["video_id"], user_id, s["title"], s["published_at"], s["duration_seconds"],
              s["view_count"], s["like_count"], s["comment_count"], s["channel_name"], s["channel_id"], s["thumbnail_url"]))
    
    conn.execute("INSERT OR REPLACE INTO youtube_sync_meta (key, value) VALUES ('channel_name', ?)", (channel_name,))
    conn.execute("INSERT OR REPLACE INTO youtube_sync_meta (key, value) VALUES ('last_synced', ?)", (now,))
    conn.execute("INSERT OR REPLACE INTO youtube_sync_meta (key, value) VALUES ('channel_id', ?)", (channel_id,))
    conn.commit()
    conn.close()
    
    # --- SUPABASE TELEMETRY SYNC ---
    if user_id and analytics and analytics.Enabled:
        from packages.core.services.telemetry import telemetry
        import hashlib
        
        # Match SQLite titles against Supabase clips_metadata
        for s in shorts:
            metrics = {
                "platform": "youtube",
                "youtube_id": s["video_id"],
                "views": s["view_count"],
                "likes": s["like_count"],
                "comments": s["comment_count"],
                "last_updated": "now()"
            }
            
            # Update Supabase and get the clip's hook type etc.
            res = analytics.client.table("clips_metadata")\
                .update({"performance_metrics": metrics})\
                .eq("video_title", s["title"])\
                .execute()
                
            if res.data:
                clip_data = res.data[0]
                hook_type = clip_data.get("hook_type")
                predicted_score = clip_data.get("sentiment_score")
                
                title_hash = hashlib.sha256(s["title"].encode()).hexdigest()[:12]
                telemetry.track_youtube_performance(
                    user_id=user_id,
                    youtube_id=s["video_id"],
                    views=s["view_count"],
                    likes=s["like_count"],
                    comments=s["comment_count"],
                    duration_seconds=s["duration_seconds"],
                    hook_type=hook_type,
                    predicted_score=predicted_score,
                    title_hash=title_hash
                )
    
    return {
        "total_shorts": len(shorts),
        "channel_name": channel_name,
        "channel_id": channel_id,
    }


# ─── YouTube Historical Extractor (Retroactive Intelligence) ────────────────

@router.get("/analytics/youtube/historical/estimate")
async def estimate_historical_cost(request: Request, authorization: str = Header(None)):
    """
    Counts available historical shorts and calculates the OpenRouter LLM cost
    based on the user's currently configured model.
    """
    import httpx
    from packages.core.config import settings
    
    # 1. How many shorts do we have in local DB that aren't synced to telemetry yet?
    # For MVP, we'll just count how many shorts are in the DB and multiply.
    # We could be more precise and only count those without `ic_telemetry_events`.
    conn = _get_yt_db()
    cursor = conn.execute("SELECT COUNT(*) FROM youtube_shorts")
    count_row = cursor.fetchone()
    total_shorts = count_row[0] if count_row else 0
    conn.close()
    
    if total_shorts == 0:
        return {"total_shorts": 0, "estimated_cost_usd": 0.0, "model": "none"}
        
    # Determine which model is active
    active_model = None
    if settings.openai_model: active_model = settings.openai_model
    elif settings.anthropic_model: active_model = settings.anthropic_model
    elif settings.groq_model: active_model = settings.groq_model
    elif settings.vertex_model: active_model = settings.vertex_model
    else: active_model = "meta-llama/llama-3.3-70b-instruct" # default fallback
    
    # Prefix mapping for OpenRouter if needed
    or_model_id = active_model
    if not "/" in or_model_id and "gpt" not in or_model_id and "claude" not in or_model_id:
        # Simplistic mapping for local model names, but SettingsForm now saves OR names directly
        pass 
        
    # 2. Fetch OpenRouter pricing
    cost_per_token = 0.0
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://openrouter.ai/api/v1/models")
            if resp.status_code == 200:
                data = resp.json()
                for model in data.get("data", []):
                    if model.get("id") == active_model or active_model in model.get("id", ""):
                        pricing = model.get("pricing", {})
                        # price is given per 1 token as string
                        cost_per_token = float(pricing.get("prompt", 0.0))
                        break
    except Exception as e:
        import logging
        logging.warning(f"Failed to fetch OpenRouter pricing: {e}")
        # Fallback average price if API fails
        cost_per_token = 0.0000005 

    # 3. Calculate: ~800 tokens per transcript + prompt
    # Example: 800 tokens * 0.000001 = $0.0008 per video
    est_tokens_per_video = 800
    total_cost = total_shorts * est_tokens_per_video * cost_per_token
    
    return {
        "total_shorts": total_shorts,
        "estimated_cost_usd": round(total_cost, 4),
        "model": active_model,
        "cost_per_1M_tokens": round(cost_per_token * 1_000_000, 2)
    }

@router.post("/analytics/youtube/historical/sync")
async def sync_historical_data(request: Request, authorization: str = Header(None)):
    """
    Triggers the YouTubeHistoricalExtractor to fetch transcripts and analyze
    them with the LLM, sinking them to Collective Intelligence.
    """
    from packages.core.services.youtube_historical import YouTubeHistoricalExtractor
    from packages.core.services.telemetry import TelemetryService
    from packages.core.config import settings
    
    # Need youtube access token from sqlite metadata
    conn = _get_yt_db()
    cursor = conn.execute("SELECT value FROM youtube_sync_meta WHERE key = 'refresh_token'")
    row = cursor.fetchone()
    
    cursor_ch = conn.execute("SELECT value FROM youtube_sync_meta WHERE key = 'channel_id'")
    row_ch = cursor_ch.fetchone()
    conn.close()
    
    if not row or not row_ch:
        raise HTTPException(status_code=400, detail="YouTube not connected. Connect first.")
        
    refresh_token = row[0]
    channel_id = row_ch[0]
    
    # Refresh the access token
    import json
    import requests as http_requests
    secrets_path = _find_client_secrets()
    with open(secrets_path) as f:
        secrets_data = json.load(f)
    
    client_info = secrets_data.get("web") or secrets_data.get("installed", {})
    token_uri = client_info.get("token_uri", "https://oauth2.googleapis.com/token")
    
    token_res = http_requests.post(token_uri, data={
        "client_id": client_info.get("client_id"),
        "client_secret": client_info.get("client_secret"),
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    
    if token_res.status_code != 200:
        raise HTTPException(status_code=401, detail="Failed to refresh Google token")
        
    access_token = token_res.json().get("access_token")
    
    # Get user_id from auth header
    user_id = "default_user"
    if authorization:
        try:
            import base64
            token = authorization.replace("Bearer ", "").strip()
            payload = token.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            decoded = json.loads(base64.b64decode(payload))
            user_id = decoded.get("sub", user_id)
        except:
            pass
            
    # Init Extractor and run
    telemetry_svc = TelemetryService()
    extractor = YouTubeHistoricalExtractor(telemetry_svc)
    
    result = await extractor.process_historical_shorts(
        user_id=user_id,
        channel_id=channel_id,
        access_token=access_token,
        max_videos=100
    )
    
    return result


@router.get("/analytics/youtube/insights")
async def get_youtube_insights(request: Request):
    """Aggregate insights from synced YouTube Shorts data."""
    try:
        user = getattr(request.state, "user", None)
        conn = _get_yt_db()
        
        base_where = "WHERE 1=1"
        params_base = []
        if user:
            base_where = "WHERE (user_id = ? OR user_id IS NULL)"
            params_base = [user["id"]]
            
        # Basic totals
        cursor = conn.execute(f"""
            SELECT 
                COUNT(*) as total,
                COALESCE(SUM(view_count), 0) as total_views,
                COALESCE(SUM(like_count), 0) as total_likes,
                COALESCE(AVG(view_count), 0) as avg_views,
                COALESCE(AVG(duration_seconds), 0) as avg_duration
            FROM youtube_shorts
            {base_where}
        """, params_base)
        row = cursor.fetchone()
        total = row[0]; total_views = row[1]; total_likes = row[2]
        avg_views = row[3]; avg_duration = row[4]
        
        if total == 0:
            conn.close()
            return {"total_shorts": 0, "total_views": 0, "total_likes": 0,
                    "avg_views": 0, "avg_duration": 0, "best_performing": [],
                    "duration_breakdown": []}
        
        # Top 10 performing shorts
        best_cursor = conn.execute(f"""
            SELECT title, view_count, video_id
            FROM youtube_shorts
            {base_where}
            ORDER BY view_count DESC
            LIMIT 10
        """, params_base)
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
            params_range = params_base + [lo, hi]
            dc = conn.execute(f"""
                SELECT COUNT(*), COALESCE(AVG(view_count), 0)
                FROM youtube_shorts
                {base_where} AND duration_seconds >= ? AND duration_seconds <= ?
            """, params_range)
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
    Updates 'user_connections', matches videos to 'clips_metadata', and emits
    telemetry events for the LI feedback loop.
    """
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from server.services.analytics import AnalyticsSync
    from packages.core.services.telemetry import telemetry
    import hashlib
    
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    
    # Setup Supabase Client (to save results)
    token = authorization.replace("Bearer ", "").strip()
    analytics = AnalyticsSync(auth_token=token)
    if not analytics.Enabled:
         raise HTTPException(status_code=500, detail="Analytics service not enabled")

    # Extract user_id from JWT for telemetry
    user_id = None
    try:
        import json, base64
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)  # Fix padding
        decoded = json.loads(base64.b64decode(payload))
        user_id = decoded.get("sub")
    except Exception:
        pass

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
            part='snippet,statistics,contentDetails'
        ).execute()
        
        matched_count = 0
        telemetry_count = 0
        
        # Sync Video Stats to Clips
        for vid in stats_resp.get('items', []):
            title = vid['snippet']['title']
            stats = vid['statistics']
            
            views = int(stats.get('viewCount', 0))
            likes = int(stats.get('likeCount', 0))
            comments_count = int(stats.get('commentCount', 0))
            
            # Parse duration
            duration_secs = None
            if vid.get('contentDetails', {}).get('duration'):
                duration_secs = _parse_iso_duration(vid['contentDetails']['duration'])
            
            metrics = {
                "platform": "youtube",
                "youtube_id": vid['id'],
                "views": views,
                "likes": likes,
                "comments": comments_count,
                "last_updated": "now()"
            }
            
            # Update clips_metadata (existing behavior)
            res = analytics.client.table("clips_metadata")\
                .update({"performance_metrics": metrics})\
                .eq("video_title", title)\
                .execute()
                
            if res.data:
                matched_count += 1
                
                # Extract clip metadata for enriched telemetry
                clip_data = res.data[0] if res.data else {}
                hook_type = clip_data.get("hook_type")
                predicted_score = clip_data.get("sentiment_score")
                clip_duration = clip_data.get("duration_seconds") or duration_secs
                
                # NEW: Emit telemetry event for LI feedback loop
                if user_id:
                    title_hash = hashlib.sha256(title.encode()).hexdigest()[:12]
                    telemetry.track_youtube_performance(
                        user_id=user_id,
                        youtube_id=vid['id'],
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
            "prompt": "consent select_account",
        }
        
        authorization_url = f"{auth_uri}?{urlencode(params)}"
        return {"url": authorization_url}
        
    except HTTPException:
        raise
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
