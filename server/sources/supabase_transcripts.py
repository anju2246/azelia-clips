"""Supabase transcript source with utterances and speaker labels.

DATA SOURCE REFERENCE:
=======================
This module fetches transcripts from Supabase with the following structure:

TABLE: episodes
- id: Episode ID (e.g., "EP097", "EP108")
- title: Episode title
- guest_name: Guest name
- duration_seconds: Episode duration
- raw_transcript: Full text (no timestamps)

TABLE: utterances
- episode_id: Reference to episodes.id
- speaker: "A" or "B" (host vs guest)
- start_time: Start timestamp in seconds
- end_time: End timestamp in seconds
- text: Utterance content
- confidence: Confidence score
- utterance_index: Order in transcript

ENVIRONMENT VARIABLES:
- SUPABASE_URL: Project URL
- SUPABASE_KEY: Anon/service key
"""

from dataclasses import dataclass
from typing import Any

from rich.console import Console

from packages.clips.transcription.transcriber import Segment, Transcript
from packages.core.config import settings

console = Console()


@dataclass
class Utterance:
    """A single utterance from Supabase with speaker and timing."""
    speaker: str       # "A" or "B"
    text: str
    start_time: float
    end_time: float
    confidence: float = 1.0

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


def get_supabase_client():
    """Get Supabase client for the transcript DB (separate project from Azelia DB)."""
    from supabase import create_client

    url = settings.transcript_supabase_url
    key = settings.transcript_supabase_key

    if not url or not key:
        raise ValueError(
            "Transcript DB credentials required. Set TRANSCRIPT_SUPABASE_URL and "
            "TRANSCRIPT_SUPABASE_KEY in .env"
        )

    return create_client(url, key)


def get_episode_utterances(episode_id: str) -> list[Utterance]:
    """
    Fetch all utterances for an episode from Supabase.

    Args:
        episode_id: Episode ID (e.g., "EP097")

    Returns:
        List of Utterance objects sorted by start_time
    """
    client = get_supabase_client()

    console.print(f"[blue]📡[/blue] Fetching utterances for {episode_id} from Supabase...")

    response = (
        client.table("utterances")
        .select("*")
        .eq("episode_id", episode_id)
        .order("start_time")
        .execute()
    )

    if not response.data:
        console.print(f"[yellow]No utterances found for {episode_id}[/yellow]")
        return []

    utterances = []
    for row in response.data:
        start = row.get("start_time")
        end = row.get("end_time")

        # Skip rows without timestamps
        if start is None or end is None:
            continue

        utterances.append(Utterance(
            speaker=row.get("speaker", "A"),
            text=row.get("text", ""),
            start_time=float(start),
            end_time=float(end),
            confidence=float(row.get("confidence", 1.0)),
        ))

    # Sort by start time
    utterances.sort(key=lambda u: u.start_time)

    console.print(f"[green]✓[/green] Loaded {len(utterances)} utterances ({utterances[-1].end_time:.0f}s total)")

    return utterances


def utterances_to_transcript(
    utterances: list[Utterance],
    episode_id: str,
    duration: float | None = None,
) -> Transcript:
    """
    Convert Supabase utterances to our Transcript format.

    Args:
        utterances: List of Utterance objects
        episode_id: Episode ID for source reference
        duration: Total duration (auto-detected if None)

    Returns:
        Transcript object compatible with curator
    """
    if not utterances:
        return Transcript(
            segments=[],
            language="es",
            duration=0,
            source_file=f"supabase://{episode_id}",
        )

    # Map speaker A/B to SPEAKER_00/SPEAKER_01
    speaker_map = {"A": "SPEAKER_00", "B": "SPEAKER_01"}

    MAX_SEG_DURATION = 60.0  # Finder needs ~30s chunks to detect viral moments

    segments = []
    for utt in utterances:
        speaker = speaker_map.get(utt.speaker, utt.speaker)
        seg_duration = utt.end_time - utt.start_time

        if seg_duration <= MAX_SEG_DURATION:
            segments.append(Segment(
                text=utt.text,
                start=utt.start_time,
                end=utt.end_time,
                words=[],
                speaker=speaker,
            ))
        else:
            # Split long utterances into ~30s sub-segments proportionally
            words = utt.text.split()
            if not words:
                continue
            words_per_sec = len(words) / seg_duration
            chunk_size = max(1, int(30 * words_per_sec))
            t = utt.start_time
            for i in range(0, len(words), chunk_size):
                chunk_words = words[i: i + chunk_size]
                chunk_dur = len(chunk_words) / words_per_sec
                segments.append(Segment(
                    text=" ".join(chunk_words),
                    start=round(t, 3),
                    end=round(min(t + chunk_dur, utt.end_time), 3),
                    words=[],
                    speaker=speaker,
                ))
                t += chunk_dur

    # Auto-detect duration from last utterance
    if duration is None:
        duration = max(u.end_time for u in utterances)

    return Transcript(
        segments=segments,
        language="es",
        duration=duration,
        source_file=f"supabase://{episode_id}",
    )


def get_episode_metadata(episode_id: str) -> dict[str, Any] | None:
    """
    Get episode metadata from Supabase.

    Args:
        episode_id: Episode ID

    Returns:
        Dict with title, guest_name, duration_seconds, etc.
    """
    client = get_supabase_client()

    try:
        response = (
            client.table("episodes")
            .select("*")
            .eq("id", episode_id)
            .single()
            .execute()
        )
        return response.data
    except Exception:
        # Try searching by title pattern
        try:
            response = (
                client.table("episodes")
                .select("*")
                .ilike("title", f"%{episode_id}%")
                .single()
                .execute()
            )
            return response.data
        except Exception:
            return None


def get_transcript_from_supabase(episode_id: str) -> Transcript | None:
    """
    Main function: Get complete transcript from Supabase.

    Args:
        episode_id: Episode ID (e.g., "EP097")

    Returns:
        Transcript object or None if not found
    """
    # Get metadata first
    metadata = get_episode_metadata(episode_id)
    duration = float(metadata.get("duration_seconds", 0)) if metadata else None

    # Get utterances
    utterances = get_episode_utterances(episode_id)
    if not utterances:
        return None

    # Convert to transcript
    transcript = utterances_to_transcript(utterances, episode_id, duration)

    console.print(f"[dim]   Duration: {transcript.duration:.0f}s | Segments: {len(transcript.segments)}[/dim]")

    return transcript


def upload_transcript(
    transcript: Transcript,
    episode_id: str,
    episode_title: str | None = None,
    guest_name: str | None = None,
) -> bool:
    """
    Upload a local transcript to Supabase (episodes + utterances).

    Args:
        transcript: Transcript object to upload
        episode_id: Episode ID (e.g., "EP108")
        episode_title: Optional title for the episode
        guest_name: Optional guest name

    Returns:
        True if successful
    """
    client = get_supabase_client()

    console.print(f"[bold blue]🚀 Uploading {episode_id} to Supabase...[/bold blue]")

    # 1. Upsert Episode
    episode_data = {
        "id": episode_id,
        "duration_seconds": transcript.duration,
        "raw_transcript": transcript.get_text_in_range(0, transcript.duration),
    }
    if episode_title:
        episode_data["title"] = episode_title
    if guest_name:
        episode_data["guest_name"] = guest_name

    try:
        client.table("episodes").upsert(episode_data).execute()
        console.print("[green]   ✓[/green] Episode metadata synced")
    except Exception as e:
        console.print(f"[red]   ✗ Failed to sync episode: {e}[/red]")
        return False

    # 2. Clear existing utterances
    try:
        client.table("utterances").delete().eq("episode_id", episode_id).execute()
        console.print("[dim]   ✓[/dim] Cleared existing utterances")
    except Exception as e:
        console.print(f"[red]   ✗ Failed to clear utterances: {e}[/red]")
        return False

    # 3. Prepare Utterances
    utterances_data = []
    # Map speakers: SPEAKER_00 -> A, SPEAKER_01 -> B
    speaker_map = {"SPEAKER_00": "A", "SPEAKER_01": "B"}

    for i, seg in enumerate(transcript.segments):
        speaker_label = speaker_map.get(seg.speaker, "A") # Default to A

        # If speaker is already A or B (manually edited), keep it
        if seg.speaker in ["A", "B"]:
            speaker_label = seg.speaker

        utterances_data.append({
            "episode_id": episode_id,
            "speaker": speaker_label,
            "text": seg.text,
            "start_time": seg.start,
            "end_time": seg.end,
            "confidence": 1.0, # Whisper doesn't give segment confidence easily
            "utterance_index": i
        })

    # 4. Insert in batches
    BATCH_SIZE = 100
    total_uploaded = 0

    # Import tqdm for progress bar if available, else simple print
    try:
        from tqdm import tqdm
        iterator = tqdm(range(0, len(utterances_data), BATCH_SIZE), desc="   Uploading utterances")
    except ImportError:
        iterator = range(0, len(utterances_data), BATCH_SIZE)

    try:
        for i in iterator:
            batch = utterances_data[i : i + BATCH_SIZE]
            client.table("utterances").insert(batch).execute()
            total_uploaded += len(batch)

        console.print(f"[green]   ✓[/green] Successfully uploaded {total_uploaded} utterances")
        return True

    except Exception as e:
        console.print(f"[red]   ✗ Failed to upload utterances batch: {e}[/red]")
        return False
