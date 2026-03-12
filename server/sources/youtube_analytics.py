"""
YouTube Analytics Parser — Processes CSV exports from YouTube Studio.

Used when OAuth API access is not available or for historical data import.
Parses the standard YouTube Analytics CSV format and pushes anonymized
performance metrics to ic_telemetry_events for LI/IC consumption.
"""

import csv
import io
import hashlib
from typing import Optional, Dict, Any, List
from rich.console import Console

console = Console()


class YouTubeAnalyticsParser:
    """
    Parses YouTube Analytics CSV files and syncs anonymized performance data.
    
    Supports CSV formats:
      - "Content" tab export (per-video views, watch time, etc.)
      - "Overview" tab export (channel-level aggregates)
    """

    def __init__(self, auth_token: Optional[str] = None):
        self.auth_token = auth_token
        self.enabled = False
        self.client = None

        try:
            from packages.core.config import settings
            if settings.supabase_url and settings.supabase_key and auth_token:
                from supabase import create_client
                self.client = create_client(settings.supabase_url, settings.supabase_key)
                self.client.auth.set_session(auth_token, "dummy_refresh")
                self.enabled = True
        except Exception as e:
            console.print(f"[yellow]⚠️  YouTubeAnalyticsParser init failed: {e}[/yellow]")

    def parse_and_sync(self, csv_content: bytes) -> Dict[str, Any]:
        """
        Parse CSV content and push performance metrics to Supabase.
        
        Args:
            csv_content: Raw CSV bytes from YouTube Studio export
            
        Returns:
            Stats dict with parsed/synced counts
        """
        if not self.enabled or not self.client:
            return {"error": "Service not enabled", "parsed": 0, "synced": 0}

        try:
            text = csv_content.decode("utf-8-sig")  # Handle BOM
            reader = csv.DictReader(io.StringIO(text))
            
            rows = list(reader)
            if not rows:
                return {"parsed": 0, "synced": 0, "error": "Empty CSV"}

            # Detect CSV format by headers
            headers = set(rows[0].keys())
            
            if "Video title" in headers or "Content" in headers:
                return self._parse_content_csv(rows)
            else:
                return {"parsed": len(rows), "synced": 0, 
                        "warning": f"Unrecognized CSV format. Headers: {list(headers)[:5]}"}

        except Exception as e:
            console.print(f"[red]CSV Parse Error: {e}[/red]")
            return {"error": str(e), "parsed": 0, "synced": 0}

    def _parse_content_csv(self, rows: List[Dict]) -> Dict[str, Any]:
        """Parse YouTube Studio 'Content' tab CSV (per-video metrics)."""
        from packages.core.services.telemetry import telemetry
        
        synced = 0
        user_id = self._extract_user_id()
        
        for row in rows:
            title = row.get("Video title") or row.get("Content", "")
            if not title:
                continue
                
            views = self._safe_int(row.get("Views", 0))
            likes = self._safe_int(row.get("Likes", 0))
            comments_count = self._safe_int(row.get("Comments", 0))
            watch_hours = self._safe_float(row.get("Watch time (hours)", 0))
            avg_view_dur = row.get("Average view duration")
            
            # Parse average view duration (format: "0:42" or "1:23")
            duration_secs = None
            if avg_view_dur:
                duration_secs = self._parse_duration_str(avg_view_dur)
            
            if user_id and views > 0:
                title_hash = hashlib.sha256(title.encode()).hexdigest()[:12]
                telemetry.track_youtube_performance(
                    user_id=user_id,
                    youtube_id=title_hash,  # No video ID in CSV, use hash
                    views=views,
                    likes=likes,
                    comments=comments_count,
                    duration_seconds=duration_secs,
                    title_hash=title_hash,
                )
                synced += 1

        return {"parsed": len(rows), "synced": synced}

    def _extract_user_id(self) -> Optional[str]:
        """Extract user_id from the JWT auth token."""
        if not self.auth_token:
            return None
        try:
            import json, base64
            payload = self.auth_token.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            decoded = json.loads(base64.b64decode(payload))
            return decoded.get("sub")
        except Exception:
            return None

    @staticmethod
    def _safe_int(val) -> int:
        try:
            return int(str(val).replace(",", "").strip())
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _safe_float(val) -> float:
        try:
            return float(str(val).replace(",", "").strip())
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _parse_duration_str(dur_str: str) -> Optional[float]:
        """Parse 'M:SS' or 'H:MM:SS' duration to seconds."""
        try:
            parts = dur_str.strip().split(":")
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except (ValueError, IndexError):
            pass
        return None
