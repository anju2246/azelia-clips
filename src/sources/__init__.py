"""Supabase integration for fetching Celia Podcast transcripts."""

import json
from dataclasses import dataclass

from rich.console import Console
from rich.table import Table
from supabase import create_client, Client

from src.asr.transcriber import Transcript, Segment, Word
from src.config import settings

console = Console()


@dataclass
class Episode:
    """Podcast episode metadata."""
    id: str
    title: str
    episode_number: str | None
    duration: float | None
    published_at: str | None
    transcript_text: str | None
    has_word_timestamps: bool = False


class SupabaseClient:
    """Client for fetching podcast data from Supabase."""

    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
    ):
        self.url = url or settings.supabase_url
        self.key = key or settings.supabase_key

        if not self.url or not self.key:
            raise ValueError(
                "Supabase credentials required. Set SUPABASE_URL and SUPABASE_KEY in .env"
            )

        self.client: Client = create_client(self.url, self.key)

    def list_episodes(self, limit: int = 20) -> list[Episode]:
        """
        List available episodes with transcripts.

        Args:
            limit: Maximum episodes to return

        Returns:
            List of Episode objects
        """
        try:
            response = (
                self.client.table("episodes")
                .select("id, title, guest_name, duration_seconds, published_at, raw_transcript")
                .not_.is_("raw_transcript", "null")
                .order("published_at", desc=True)
                .limit(limit)
                .execute()
            )
            return self._parse_episodes(response.data)
        except Exception as e:
            console.print(f"[red]Error fetching episodes:[/red] {e}")
            return []

    def _parse_episodes(self, data: list[dict]) -> list[Episode]:
        """Parse episode data from the episodes table."""
        episodes = []

        for row in data:
            # Extract episode number from title (e.g., "EP001 - Title")
            title = row.get("title", "Unknown")
            ep_number = None
            if title.startswith("EP"):
                parts = title.split(" - ", 1)
                if parts:
                    ep_number = parts[0]

            episode = Episode(
                id=str(row.get("id", "")),
                title=title,
                episode_number=ep_number,
                duration=row.get("duration_seconds"),
                published_at=row.get("published_at"),
                transcript_text=row.get("raw_transcript"),
                has_word_timestamps=False,  # raw_transcript is plain text
            )
            episodes.append(episode)

        return episodes

    def get_transcript(self, episode_id: str) -> Transcript | None:
        """
        Get transcript for an episode, converted to our Transcript format.

        Args:
            episode_id: Episode ID (UUID) or episode number (e.g., EP001)

        Returns:
            Transcript object or None if not found
        """
        try:
            # Try by exact ID first
            response = (
                self.client.table("episodes")
                .select("*")
                .eq("id", episode_id)
                .single()
                .execute()
            )
            if response.data:
                return self._convert_to_transcript(response.data)
        except Exception:
            pass

        # Try searching by episode number in title
        try:
            response = (
                self.client.table("episodes")
                .select("*")
                .ilike("title", f"{episode_id}%")
                .single()
                .execute()
            )
            if response.data:
                return self._convert_to_transcript(response.data)
        except Exception:
            pass

        console.print(f"[yellow]Transcript not found for: {episode_id}[/yellow]")
        return None

    def _convert_to_transcript(self, data: dict) -> Transcript:
        """Convert Supabase row to Transcript object."""
        segments = []

        # Check if we have structured segments with timestamps
        if "segments" in data and data["segments"]:
            raw_segments = data["segments"]
            if isinstance(raw_segments, str):
                raw_segments = json.loads(raw_segments)

            for seg in raw_segments:
                words = []
                if "words" in seg:
                    for w in seg["words"]:
                        words.append(Word(
                            word=w.get("word", w.get("text", "")),
                            start=float(w.get("start", 0)),
                            end=float(w.get("end", 0)),
                            score=float(w.get("score", w.get("confidence", 1.0))),
                        ))

                segments.append(Segment(
                    text=seg.get("text", ""),
                    start=float(seg.get("start", 0)),
                    end=float(seg.get("end", 0)),
                    words=words,
                    speaker=seg.get("speaker"),
                ))

        # Fallback: create segments from plain text (raw_transcript)
        else:
            text = data.get("raw_transcript", data.get("transcript", ""))
            if not text:
                console.print("[yellow]Warning: No transcript text found[/yellow]")
                return Transcript(
                    segments=[],
                    language=data.get("language", "es"),
                    duration=0,
                    source_file=f"supabase://{data.get('id', 'unknown')}",
                )

            duration = float(data.get("duration_seconds", data.get("duration", 3600)) or 3600)

            # Split by paragraphs (double newlines) or sentences
            import re
            # Try paragraphs first, then sentences
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            if len(paragraphs) < 5:
                # Fall back to sentence splitting
                paragraphs = re.split(r'(?<=[.!?])\s+', text)

            # Estimate timing (rough approximation based on word count)
            total_words = len(text.split())
            words_per_second = total_words / duration if duration > 0 else 2.5
            current_time = 0

            for para in paragraphs:
                if not para.strip():
                    continue

                # Estimate duration based on word count
                para_words = len(para.split())
                para_duration = para_words / words_per_second if words_per_second > 0 else 10

                segments.append(Segment(
                    text=para.strip(),
                    start=current_time,
                    end=current_time + para_duration,
                    words=[],  # No word-level timestamps for plain text
                ))
                current_time += para_duration

        return Transcript(
            segments=segments,
            language=data.get("language", "es"),
            duration=float(data.get("duration_seconds", data.get("duration", 0)) or 0),
            source_file=f"supabase://{data.get('id', 'unknown')}",
        )

    def display_episodes(self, episodes: list[Episode]) -> None:
        """Display episodes in a rich table."""
        if not episodes:
            console.print("[yellow]No episodes found.[/yellow]")
            return

        table = Table(title="📻 Available Episodes", show_header=True)
        table.add_column("ID", style="dim", width=10)
        table.add_column("Episode", width=8)
        table.add_column("Title", width=40)
        table.add_column("Transcript", width=12)

        for ep in episodes:
            has_transcript = "✅" if ep.transcript_text else "❌"
            table.add_row(
                ep.id[:10] if len(ep.id) > 10 else ep.id,
                ep.episode_number or "-",
                ep.title[:38] + "..." if len(ep.title) > 40 else ep.title,
                has_transcript,
            )

        console.print(table)


def list_episodes(limit: int = 20) -> list[Episode]:
    """Convenience function to list episodes."""
    client = SupabaseClient()
    episodes = client.list_episodes(limit=limit)
    client.display_episodes(episodes)
    return episodes


def get_transcript(episode_id: str) -> Transcript | None:
    """Convenience function to get a transcript."""
    client = SupabaseClient()
    return client.get_transcript(episode_id)
