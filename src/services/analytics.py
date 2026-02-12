import os
from typing import Optional, Dict, Any
from rich.console import Console

console = Console()

class AnalyticsSync:
    """
    Handles synchronization of local clip metadata to the Community Cloud (Supabase).
    Respects privacy settings and relies on the user's Auth Token.
    
    Security:
    - Uses Supabase Edge Function 'ingest-analytics' for secure data insertion.
    - Does NOT write directly to the database (RLS prevents this).
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
        self.supabase_url = settings.get("supabase_url") # Safer get
        self.supabase_key = settings.get("supabase_key") # Anon key
        
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
        Push anonymized clip metadata to the cloud via Secure Edge Function.
        
        Args:
            clip_data: Dict with 'duration', 'hook_type', 'score', etc.
            user_id: Optional (Handled by Auth Context in Edge Function)
        """
        if not self.Enabled or not self.client:
            return

        try:
            # Prepare payload matching Edge Function expectations
            payload = {
                "local_clip_id": clip_data.get("clip_hash", "unknown"),
                "duration_seconds": int(clip_data.get("duration", 0)),
                "hook_type": clip_data.get("hook_type", "unknown"),
                "visual_style": clip_data.get("style", "standard"),
                "sentiment_score": float(clip_data.get("score", 0)),
                # Metrics for specific platforms (flexible JSONB)
                # Currently sending empty, but structure allows extension
                "platform_metrics": {} 
            }
            
            # Invoke the Edge Function
            # The client is authenticated, so it sends the User JWT automatically.
            response = self.client.functions.invoke("ingest-analytics", invoke_options={'body': payload})
            
            # Check for function error (Supabase functions return data/error object)
            # But the python client might raise exception or return response object?
            # It usually returns a FunctionResponse object.
            
            # Let's assume standard behavior:
            if hasattr(response, 'error') and response.error:
                 console.print(f"[red]❌ Sync Error (Function): {response.error}[/red]")
            else:
                console.print(f"[blue]☁️  Synced Clip Metadata to Community DB (Secure)[/blue]")
            
        except Exception as e:
            # Fail silently to not break the pipeline
            console.print(f"[red]❌ Sync Error: {e}[/red]")
