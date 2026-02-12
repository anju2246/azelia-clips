import json
import os
import argparse
from pathlib import Path
from typing import List, Dict, Any

try:
    from supabase import create_client, Client
except ImportError:
    print("Error: 'supabase' library needed. Install with: pip install supabase")
    exit(1)

from rich.console import Console
from rich.progress import track

console = Console()

# ════════════════════════════════════════════════
# CONFIGURATION
# ════════════════════════════════════════════════
# It's recommended to set these as env vars, or hardcode here for quick usage
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") # Use SERVICE ROLE key for writing!

if not SUPABASE_URL or not SUPABASE_KEY:
    console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables required.[/red]")
    console.print("Export them or edit this script.")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def upload_episode(file_path: Path, episode_num: int, title: str) -> None:
    """Read transcript JSON and upload to Supabase."""
    
    if not file_path.exists():
        console.print(f"[red]File not found: {file_path}[/red]")
        return

    console.print(f"[bold blue]Processing Episode {episode_num}: {title}[/bold blue]")
    
    # 1. Read JSON
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 2. Extract Segments
    # Support different formats (Whisper, AssemblyAI, or raw list)
    segments = []
    
    if isinstance(data, list):
        segments = data # Assuming raw segment list
    elif "segments" in data:
        segments = data["segments"] # Whisper style
    elif "utterances" in data:
        segments = data["utterances"] # AssemblyAI style (sometimes)
    elif "results" in data and "utterances" in data["results"]:
         segments = data["results"]["utterances"] # Another variant
         
    if not segments:
        console.print("[red]Could not find segments/utterances in JSON structure.[/red]")
        return
        
    console.print(f"   Found {len(segments)} segments.")

    # 3. Create Episode Record
    try:
        ep_data = {
            "episode_number": episode_num,
            "title": title,
            "published_at": None # Optional
        }
        res = supabase.table("episodes").insert(ep_data).execute()
        episode_id = res.data[0]['id']
        console.print(f"   [green]✓[/green] Episode created (ID: {episode_id})")
    except Exception as e:
        console.print(f"   [red]Error creating episode: {e}[/red]")
        return

    # 4. Prepare Utterances
    utterances_to_insert = []
    for seg in segments:
        # Normalize fields
        start = seg.get("start") or seg.get("start_time") # Handle varied naming
        end = seg.get("end") or seg.get("end_time")
        text = seg.get("text")
        speaker = seg.get("speaker", "Unknown")
        
        # WhisperX often puts speaker in 'speaker', AssemblyAI in 'speaker' label
        # If no speaker, try to infer or leave generic
        
        utterances_to_insert.append({
            "episode_id": episode_id,
            "speaker": speaker,
            "text": text.strip(),
            "start_time": float(start),
            "end_time": float(end)
        })

    # 5. Batch Insert Utterances (Supabase limits batch size usually)
    BATCH_SIZE = 100
    console.print(f"   Uploading {len(utterances_to_insert)} utterances in batches...")
    
    total_uploaded = 0
    try:
        status_bar = track(range(0, len(utterances_to_insert), BATCH_SIZE), description="Uploading...")
        for i in status_bar:
            batch = utterances_to_insert[i:i + BATCH_SIZE]
            supabase.table("utterances").insert(batch).execute()
            total_uploaded += len(batch)
            
        console.print(f"   [bold green]✓ Success! Uploaded {total_uploaded} utterances.[/bold green]")
        
    except Exception as e:
        console.print(f"   [red]Error inserting utterances: {e}[/red]")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload transcript JSON to Supabase")
    parser.add_argument("file", type=Path, help="Path to transcript.json")
    parser.add_argument("--episode-num", type=int, required=True, help="Episode Number (e.g. 101)")
    parser.add_argument("--title", type=str, required=True, help="Episode Title")
    
    args = parser.parse_args()
    
    upload_episode(args.file, args.episode_num, args.title)
