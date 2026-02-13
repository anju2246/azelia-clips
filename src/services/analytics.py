import os
from typing import Optional, Dict, Any
from rich.console import Console

console = Console()

class AnalyticsSync:
    """
    Handles synchronization of local clip metadata to the Community Cloud (Supabase).
    Respects privacy settings and relies on the user's Auth Token.
    """
    
    def __init__(self, auth_token: Optional[str] = None):
        """
        Initialize with user's auth token and project config.
        
        Args:
            auth_token: JWT from Supabase Auth (passed from Frontend)
        """
        self.auth_token = auth_token
        self.Enabled = False
        self.client = None
        
        # We need the Project URL. The Anon Key is public, but we need the URL.
        # Ideally, this comes from settings or .env
        from src.config import settings
        self.supabase_url = settings.supabase_url
        self.supabase_key = settings.supabase_key # Anon key
        
        if self.supabase_url and self.supabase_key and self.auth_token:
            try:
                from supabase import create_client, Client
                # Initialize standard client with Anon Key
                self.client: Client = create_client(self.supabase_url, self.supabase_key)
                
                # SET THE USER SESSION!
                # This is critical. We must act AS the user to pass RLS.
                self.client.auth.set_session(self.auth_token, "dummy_refresh")
                self.Enabled = True
                console.print(f"[green]🔄 Analytics Sync Enabled (User Authenticated)[/green]")
            except Exception as e:
                console.print(f"[yellow]⚠️  Analytics Sync Failed to Init: {e}[/yellow]")
        else:
            if not self.auth_token:
                console.print(f"[dim]   Analytics Sync Disabled (No Auth Token)[/dim]")
            elif not self.supabase_url:
                console.print(f"[dim]   Analytics Sync Disabled (No Supabase URL)[/dim]")

    def sync_clip(self, clip_data: Dict[str, Any], user_id: Optional[str] = None):
        """
        Push anonymized clip metadata to the cloud.
        
        Args:
            clip_data: Dict with 'duration', 'hook_type', 'score', etc.
            user_id: Optional, but RLS will use the token's user anyway.
        """
        if not self.Enabled or not self.client:
            return

        try:
            # Prepare payload matching table schema
            payload = {
                "local_clip_id": clip_data.get("clip_hash", "unknown"),
                "duration_seconds": int(clip_data.get("duration", 0)),
                "hook_type": clip_data.get("hook_type", "unknown"),
                "visual_style": clip_data.get("style", "standard"),
                "sentiment_score": float(clip_data.get("score", 0)),
                # 'user_id' is handled by Supabase Auth Context (RLS) automatically?
                # Usually we insert it, or let default=auth.uid() handle it if configured.
                # Let's try inserting without it first, or if we have it from token.
            }
            
            # If we decoded the token we could pass user_id, but the RLS 
            # might require the column to match auth.uid().
            # Best practice: Let the backend handle it or pass it if known.
            if user_id:
                payload["user_id"] = user_id
            
            # Perform Insert
            res = self.client.table("clips_metadata").insert(payload).execute()
            console.print(f"[blue]☁️  Synced Clip Metadata to Community DB[/blue]")
            
        except Exception as e:
            # Fail silently to not break the pipeline
            console.print(f"[red]❌ Sync Error: {e}[/red]")
