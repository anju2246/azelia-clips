"""
Server Routes — Platform Analytics & YouTube OAuth
"""

import os
import glob
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
