import csv
import io
from typing import Optional, Dict, List
from rich.console import Console

console = Console()

class YouTubeAnalyticsParser:
    """
    Parses YouTube Studio CSV exports and syncs performance data to clips_metadata.
    """
    
    def __init__(self, auth_token: Optional[str] = None):
        from packages.core.config import settings
        self.auth_token = auth_token
        self.supabase_url = settings.supabase_url
        self.supabase_key = settings.supabase_key
        self.client = None
        self.enabled = False
        
        if self.supabase_url and self.supabase_key and self.auth_token:
            try:
                from supabase import create_client
                self.client = create_client(self.supabase_url, self.supabase_key)
                self.client.auth.set_session(self.auth_token, "dummy_refresh")
                self.enabled = True
            except Exception as e:
                console.print(f"[yellow]⚠️  YouTube Parser Failed to Init: {e}[/yellow]")

    def parse_and_sync(self, file_content: bytes) -> Dict[str, int]:
        """
        Parse CSV bytes and update matching clips in Supabase.
        Returns stats: {'matched': 5, 'updated': 5, 'failed': 0}
        """
        if not self.enabled:
            return {"error": "Supabase client not initialized"}
            
        stats = {"processed": 0, "matched": 0, "updated": 0, "errors": 0}
        
        try:
            # Decode bytes to string
            content_str = file_content.decode('utf-8')
            reader = csv.DictReader(io.StringIO(content_str))
            
            # Normalize column names (YouTube CSV headers change sometimes)
            # Common headers: "Video title", "Video publish time", "Views", "Watch time (hours)", "Subscribers", "Impressions", "Impressions click-through rate (%)"
            
            for row in reader:
                stats["processed"] += 1
                title = row.get("Video title", "").strip()
                if not title:
                    continue
                    
                # Extract metrics
                try:
                    views = int(row.get("Views", 0))
                    watch_time = float(row.get("Watch time (hours)", 0))
                    impressions = int(row.get("Impressions", 0))
                    ctr = float(row.get("Impressions click-through rate (%)", 0).replace("%", ""))
                    likes = int(row.get("Likes", 0)) if "Likes" in row else 0
                    
                    metrics = {
                        "platform": "youtube",
                        "views": views,
                        "watch_time_hours": watch_time,
                        "impressions": impressions,
                        "ctr": ctr,
                        "likes": likes,
                        "last_updated": "now()"
                    }
                    
                    # Find clip by title
                    # Note: exact match required for now. 
                    # Users must not change title when uploading or must manually link (future feature).
                    res = self.client.table("clips_metadata")\
                        .select("id, performance_metrics")\
                        .eq("video_title", title)\
                        .execute()
                        
                    if res.data:
                        stats["matched"] += 1
                        clip_id = res.data[0]['id']
                        current_metrics = res.data[0].get('performance_metrics', {}) or {}
                        
                        # Merge metrics (overwrite youtube specific keys)
                        current_metrics.update(metrics)
                        
                        # Update row
                        self.client.table("clips_metadata")\
                            .update({"performance_metrics": current_metrics})\
                            .eq("id", clip_id)\
                            .execute()
                            
                        stats["updated"] += 1
                        console.print(f"[green]Matched: {title} ({views} views)[/green]")
                    else:
                        # console.print(f"[dim]No match for: {title}[/dim]")
                        pass
                        
                except Exception as e:
                    console.print(f"[red]Error parsing row {title}: {e}[/red]")
                    stats["errors"] += 1
                    
            return stats
            
        except Exception as e:
            console.print(f"[red]CSV Parse Error: {e}[/red]")
            return {"error": str(e)}
