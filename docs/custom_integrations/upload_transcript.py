import argparse
import json
import os
from pathlib import Path
from typing import List, Dict, Any

try:
    from supabase import create_client, Client
except ImportError:
    print("Error: 'supabase' library not found. Install it with: pip install supabase")
    exit(1)

def upload_transcript(
    file_path: str,
    episode_id: str,
    url: str,
    key: str,
    confidence_default: float = 1.0
):
    """
    Uploads a Whisper-style JSON transcript to a Supabase database.
    Expected JSON structure: { "segments": [ { "start": 0.0, "end": 1.0, "text": "Hi", "speaker": "A" }, ... ] }
    """
    
    # Initialize Client
    supabase: Client = create_client(url, key)
    
    # Load JSON
    path = Path(file_path)
    if not path.exists():
        print(f"Error: File not found: {file_path}")
        return

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    segments = data.get("segments", [])
    if not segments:
        print("Warning: No segments found in JSON.")
        return

    print(f"Uploading {len(segments)} utterances for Episode {episode_id}...")

    # Prepare Utterances
    utterances_to_insert = []
    for seg in segments:
        # Handle different Whisper formats (local vs API often differ slightly)
        start = seg.get("start")
        end = seg.get("end")
        text = seg.get("text", "").strip()
        speaker = seg.get("speaker", "SPEAKER_00") # Default if diarization missing
        
        if start is not None and end is not None and text:
            utterances_to_insert.append({
                "episode_id": episode_id,
                "speaker": speaker,
                "text": text,
                "start_time": start,
                "end_time": end,
                "confidence": seg.get("confidence", confidence_default)
            })

    # Upsert Episode (Metadata) - Optional
    try:
        supabase.table("episodes").upsert({
            "id": episode_id,
            "title": path.stem, # Use filename as title default
        }).execute()
    except Exception as e:
        print(f"Warning inserting episode metadata (ignorable): {e}")

    # Batch Insert Utterances (Supabase limits batch sizes, usually 1000 is safe)
    batch_size = 1000
    for i in range(0, len(utterances_to_insert), batch_size):
        batch = utterances_to_insert[i:i+batch_size]
        try:
            supabase.table("utterances").insert(batch).execute()
            print(f"Processed batch {i} - {i+len(batch)}")
        except Exception as e:
            print(f"Error inserting batch: {e}")
            return

    print(f"✅ Successfully uploaded transcript for {episode_id}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload transcript JSON to Supabase")
    parser.add_argument("file", help="Path to transcript.json")
    parser.add_argument("--episode_id", required=True, help="Unique Episode ID (e.g. EP097)")
    parser.add_argument("--url", help="Supabase URL (or set SUPABASE_URL env var)")
    parser.add_argument("--key", help="Supabase Key (or set SUPABASE_KEY env var)")
    
    args = parser.parse_args()
    
    url = args.url or os.getenv("SUPABASE_URL")
    key = args.key or os.getenv("SUPABASE_KEY")
    
    if not url or not key:
        print("Error: Supabase URL and Key are required (via arguments or env vars).")
        exit(1)
        
    upload_transcript(args.file, args.episode_id, url, key)
