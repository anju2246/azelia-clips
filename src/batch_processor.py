"""Batch processor for generating clips from podcast episodes.

Reads episodes from external drive, processes through full pipeline,
and saves clips directly to external drive in organized structure.
"""

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from src.utils import run_ffmpeg, validate_video

console = Console()


@dataclass
class EpisodeConfig:
    """Configuration for a single episode to process."""
    episode_number: int
    episode_folder: Path
    video_path: Path
    transcript_path: Optional[Path] = None
    
    @property
    def clips_folder(self) -> Path:
        """Output folder for clips."""
        return self.episode_folder / "clips"


class BatchProcessor:
    """
    Process episodes in batch, saving clips directly to external drive.
    
    Structure:
    episodes/EP###/clips/
        ├── clip_01.mp4
        ├── clip_01_caption.txt
        ├── clip_02.mp4
        ├── clip_02_caption.txt
        └── ...
    """
    
    def __init__(
        self,
        external_drive_path: str = "episodes",
        clips_per_episode: int | None = None,  # DEPRECATED: No longer limits clips. All clips meeting score threshold are processed.
        min_duration: int = 30,
        max_duration: int = 180,  # Up to 3 min with manual review for >90s
        min_score: int = 70,  # Minimum virality score threshold (clips below this are skipped)
        min_score: int = 70,  # Minimum virality score threshold (clips below this are skipped)
        clip_id: int | None = None,  # NEW: Specify a single clip to re-process (1-indexed)
    ):
        self.base_path = Path(external_drive_path)
        self.clips_per_episode = clips_per_episode
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.min_score = min_score
        self.target_clip_id = clip_id
        
        if not self.base_path.exists():
            raise FileNotFoundError(
                f"⚠️ External drive not accessible: {self.base_path}\n"
                f"   Please connect the external hard drive and ensure the symlink exists:\n"
                r"   ln -s /Volumes/[DiskName]/Backup\ Podcast episodes"
            )
    
    def discover_episodes(self, start: int = 1, end: int = 999) -> list[EpisodeConfig]:
        """
        Discover episodes in the backup folder.
        
        Args:
            start: First episode number to include
            end: Last episode number to include
            
        Returns:
            List of EpisodeConfig for found episodes
        """
        episodes = []
        
        for folder in sorted(self.base_path.iterdir()):
            if not folder.is_dir():
                continue
            
            # Parse episode number from folder name (e.g., "EP001 - Title")
            folder_name = folder.name
            if not folder_name.startswith("EP"):
                continue
            
            try:
                # Extract number: "EP001 - Title" -> 108
                ep_num_str = folder_name.split(" ")[0].replace("EP", "")
                ep_num = int(ep_num_str)
            except (ValueError, IndexError):
                continue
            
            if ep_num < start or ep_num > end:
                continue
            
            # Find video file
            video_path = folder / "video.mp4"
            if not video_path.exists():
                # Try other common names
                for name in ["video.mp4", "*.mp4"]:
                    matches = list(folder.glob(name))
                    if matches:
                        video_path = matches[0]
                        break
            
            if not video_path.exists():
                console.print(f"[yellow]Warning: No video found in {folder.name}[/yellow]")
                continue
            
            # Check for existing transcript
            transcript_path = folder / "transcript.json"
            if not transcript_path.exists():
                transcript_path = None
            
            episodes.append(EpisodeConfig(
                episode_number=ep_num,
                episode_folder=folder,
                video_path=video_path,
                transcript_path=transcript_path,
            ))
        
        return episodes
    
    def process_episode(
        self, 
        episode: EpisodeConfig, 
        start_from_clip: int = 0,
        job_id: str = None,
    ) -> int:
        """
        Process a single episode through the full pipeline.
        
        Args:
            episode: Episode configuration
            start_from_clip: Skip clips before this index (for resume)
            job_id: Job ID for progress tracking (optional)
        
        Returns:
            Number of clips generated
        """
        # Note: .env is loaded automatically by src.config.settings
        
        # Import job store for pause checking
        from src.job_store import get_job_store
        store = get_job_store() if job_id else None
        
        from src.asr.transcriber import Transcript
        from src.curation.curator_v2 import MultiAgentCurator
        from src.vision.split_screen import create_split_screen_tracked
        from src.subtitles.generator import SubtitleGenerator
        
        console.print(f"\n[bold blue]Processing EP{episode.episode_number:03d}[/bold blue]")
        if store and job_id:
            store.update_progress(job_id, 25, "Fase 1: Validando archivo de video...")
        
        # Step 0: Validate video before processing (fail fast)
        video_info = validate_video(episode.video_path)
        
        if store and job_id:
            store.update_progress(job_id, 27, "Fase 2: Creando directorios...")
            
        if not video_info['valid']:
            console.print(f"[red]✗ Video validation failed:[/red]")
            for error in video_info['errors']:
                console.print(f"[red]   - {error}[/red]")
            return 0
        
        console.print(f"[dim]   Video: {video_info['width']}x{video_info['height']} @ {video_info['fps']:.1f}fps, {video_info['duration']:.0f}s[/dim]")
        
        # Create clips folder
        episode.clips_folder.mkdir(exist_ok=True)
        
        if store and job_id:
            store.update_progress(job_id, 29, "Fase 3: Cargando transcripción local...")
            
        # Step 1: Get transcript
        # DUAL PIPELINE: Use Supabase for curation (with speaker timing)
        #                WhisperX only for final clip transcription (word-level)
        
        # Load transcript (local or re-transcribe)
            if episode.transcript_path and episode.transcript_path.exists():
                console.print(f"[dim]   Loading existing transcript...[/dim]")
                transcript = Transcript.load(episode.transcript_path)
            else:
                console.print(f"[dim]   Transcribing episode (this takes time)...[/dim]")
                transcript = self._transcribe_video(episode.video_path, job_id=job_id)
                # Save transcript for future use
                transcript_out = episode.episode_folder / "transcript.json"
                transcript.save(transcript_out)
        
        if store and job_id:
            store.update_progress(job_id, 33, "Fase 4: Preparando curación por IA...")
            
        # Step 2: Curate clips (multi-agent pipeline)
        if store and job_id:
            store.update_progress(job_id, 35, "Iniciando curación por IA (esto puede tardar)...")
        
        curation_path = episode.episode_folder / "curation.json"
        
        if curation_path.exists():
            console.print(f"[green]✓[/green] Using existing curation from {curation_path.name}")
            with open(curation_path, "r") as f:
                from src.curation.curator_v2 import CuratedClipV2
                data = json.load(f)
                curated_clips = [CuratedClipV2.from_dict(d) for d in data]
        else:
            console.print(f"[dim]   Running multi-agent curation (finding ALL valid clips)...[/dim]")
            
            def curation_progress(current, total, msg):
                if store and job_id:
                    # Curation stage is the bulk of the 30-70% range
                    pct = (current / total) * 40
                    store.update_progress(job_id, int(30 + pct), msg)
            
            def check_pause():
                if store and job_id:
                    curr = store.get_job(job_id)
                    return curr.status == 'paused' if curr else False
                return False
            
            curator = MultiAgentCurator()
            curated_clips = curator.curate_chunked(
                transcript,
                top_n=None,  # Get ALL clips, not limited to clips_per_episode
                min_duration=self.min_duration,
                max_duration=self.max_duration,
                episode_number=episode.episode_number,
                progress_callback=curation_progress,
                pause_callback=check_pause
            )
            
            # Save curation results for future re-processing
            with open(curation_path, "w") as f:
                json.dump([c.to_dict() for c in curated_clips], f, indent=2, ensure_ascii=False)
            console.print(f"[dim]   Curation saved to {curation_path.name}[/dim]")
        
        if not curated_clips:
            console.print(f"[yellow]   No clips found for EP{episode.episode_number}[/yellow]")
            return 0
        
        console.print(f"[dim]   Found {len(curated_clips)} total clips from curation[/dim]")
        
        # Filter clips by score threshold
        # This is where we actually decide which clips to process
        AUTO_APPROVE_SCORE = 80
        
        valid_clips = [c for c in curated_clips if c.virality_score.total >= self.min_score]
        skipped = len(curated_clips) - len(valid_clips)
        if skipped > 0:
            console.print(f"[dim]   Filtered: {len(valid_clips)} clips with score >= {self.min_score} (skipped {skipped} below threshold)[/dim]")
        
        if not valid_clips:
            console.print(f"[yellow]   No clips with score >= {self.min_score} for EP{episode.episode_number}[/yellow]")
            return 0
        
        # Sort by score (best first) for processing order
        valid_clips.sort(key=lambda c: c.virality_score.total, reverse=True)
        console.print(f"[green]✓[/green] Processing {len(valid_clips)} clips that meet quality criteria (score >= {self.min_score})")
        
        # Clip ID filtering (for re-processing)
        target_clip_id = getattr(self, 'target_clip_id', None)
        if target_clip_id is not None:
            if 1 <= target_clip_id <= len(valid_clips):
                valid_clips = [valid_clips[target_clip_id - 1]]
                console.print(f"[bold cyan]🎯 Re-processing only Clip {target_clip_id}[/bold cyan]")
            else:
                console.print(f"[red]Error: Clip {target_clip_id} not found in curation results (1-{len(valid_clips)})[/red]")
                return 0
        
        # Create approved/review subfolders
        approved_folder = episode.clips_folder / "approved"
        review_folder = episode.clips_folder / "review"
        approved_folder.mkdir(exist_ok=True)
        review_folder.mkdir(exist_ok=True)
        
        # Step 3: Process each clip
        clips_generated = 0
        
        # If resuming, skip already processed clips
        if start_from_clip > 0:
            console.print(f"[cyan]▶️ Resuming from clip {start_from_clip + 1}[/cyan]")
        
        # Update job store with total clips count
        if store and job_id:
            store.set_total_clips(job_id, len(valid_clips))
        
        for i, clip in enumerate(valid_clips, 1):
            # Skip already processed clips when resuming
            if i <= start_from_clip:
                console.print(f"[dim]   Skipping clip_{i:02d} (already processed)[/dim]")
                continue
            
            # Check for pause request
            if store and job_id:
                current_job = store.get_job(job_id)
                if current_job and current_job.status == 'paused':
                    console.print(f"[yellow]⏸️ Job paused at clip {i-1}/{len(valid_clips)}[/yellow]")
                    return clips_generated
            
            score = clip.virality_score.total
            is_approved = score >= AUTO_APPROVE_SCORE
            target_folder = approved_folder if is_approved else review_folder
            status_icon = "✓" if is_approved else "📋"
            
            clip_name = f"clip_{i:02d}"
            console.print(f"[dim]   Processing {clip_name} ({clip.start_time:.0f}s-{clip.end_time:.0f}s) score={score} {status_icon}[/dim]")
            
            if store and job_id:
                pct = 70 + (i / len(valid_clips)) * 30
                store.update_progress(job_id, int(pct), f"Generando {clip_name}/{len(valid_clips)} ({status_icon})")
            
            # ✅ AUTO-RESUME: Check if clip already exists
            final_path_approved = approved_folder / f"{clip_name}.mp4"
            final_path_review = review_folder / f"{clip_name}.mp4"
            
            if final_path_approved.exists() or final_path_review.exists():
                console.print(f"[dim]   ⏩ Skipping {clip_name} (already exists)[/dim]")
                # Update progress tracking
                if store and job_id:
                    # We treat existing clips as "complete" for the progress bar
                    current_generated = clips_generated + (1 if final_path_approved.exists() else 0) # Approximate
                    store.update_clip_progress(
                        job_id,
                        clip_index=i,
                        clips_generated=current_generated, # This might be slightly off if we don't track total previously generated, but acceptable for UI
                        message=f"Clip {i} ya existe, saltando..."
                    )
                continue
            
            try:
                # Use temp files for intermediate processing
                with tempfile.TemporaryDirectory() as tmp_dir:
                    tmp_path = Path(tmp_dir)
                    
                    # 3a. Extract clip from source
                    raw_clip = tmp_path / "raw.mp4"
                    self._extract_clip(
                        episode.video_path,
                        raw_clip,
                        clip.start_time,
                        clip.end_time,
                    )
                    
                    # 3b. Create split-screen with tracking
                    # Always use hybrid mode (diarization + lip sync calibration)
                    # FIX: pre_cut=True because raw_clip is already extracted (avoids double-cut sync bug)
                    split_clip = tmp_path / "split.mp4"
                    create_split_screen_tracked(
                        video_path=str(raw_clip),
                        output_path=str(split_clip),
                        use_hybrid=True,
                        pre_cut=True,  # Clip already extracted, don't seek again
                    )
                    
                    # 3c. Get transcript for subtitles
                    # OPTIMIZATION: Reuse full transcript if it has word-level timestamps
                    # This avoids redundant transcription (~40 min saved per episode)
                    has_word_timestamps = any(len(seg.words) > 0 for seg in transcript.segments)
                    
                    if has_word_timestamps:
                        # Slice the full transcript instead of re-transcribing
                        clip_transcript = transcript.slice(clip.start_time, clip.end_time)
                        console.print(f"[dim]     Using transcript slice ({len(clip_transcript.segments)} segments)[/dim]")
                    else:
                        # Supabase transcripts don't have word-level → need WhisperX
                        clip_transcript = self._transcribe_clip(raw_clip)
                    
                    # 3d. Generate subtitles
                    subs_path = tmp_path / "subs.ass"
                    generator = SubtitleGenerator(style='splitscreen')
                    generator.generate_word_by_word(
                        clip_transcript,
                        str(subs_path),
                        words_per_line=5,
                        animation='cumulative'
                    )
                    
                    # 3e. Burn subtitles and save to appropriate folder
                    final_path = target_folder / f"{clip_name}.mp4"
                    self._burn_subtitles(split_clip, subs_path, final_path)
                    
                    # 3f. Save caption to text file
                    caption_path = target_folder / f"{clip_name}_caption.txt"
                    caption_content = f"{clip.social_caption}\n\n{' '.join(clip.caption_hashtags)}"
                    caption_path.write_text(caption_content, encoding='utf-8')
                    
                    clips_generated += 1
                    folder_name = "approved" if is_approved else "review"
                    console.print(f"[green]   ✓ {clip_name} saved to {folder_name}/[/green]")
                    
                    # Update job progress (for pause/resume)
                    if store and job_id:
                        store.update_clip_progress(
                            job_id,
                            clip_index=i,  # 1-indexed becomes the "completed up to" index
                            clips_generated=clips_generated,
                            message=f"Procesado clip {i}/{len(valid_clips)}",
                        )
                    
            except Exception as e:
                console.print(f"[red]   ✗ Error processing {clip_name}: {e}[/red]")
                
                # Cleanup even on error
                import torch
                import gc
                
                if torch.backends.mps.is_available():
                    torch.mps.empty_cache()
                
                gc.collect()
                continue
            
            # Successful clip cleanup
            import torch
            import gc
            
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
                torch.mps.synchronize()
            
            gc.collect()
        
        return clips_generated
    
    def _extract_clip(self, source: Path, output: Path, start: float, end: float) -> None:
        """Extract a clip segment using FFmpeg."""
        duration = end - start
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", str(source),
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            str(output)
        ]
        run_ffmpeg(cmd, timeout=300)  # 5 min max for clip extraction
    
    def _burn_subtitles(self, video: Path, subs: Path, output: Path) -> None:
        """Burn subtitles into video using FFmpeg."""
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video),
            "-vf", f"ass={subs}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            str(output)
        ]
        run_ffmpeg(cmd, timeout=300)  # 5 min max for subtitle burning
    
    def _transcribe_video(self, video_path: Path, job_id: str = None) -> "Transcript":
        """Transcribe a full video using MLX Whisper with progress reporting."""
        import mlx_whisper
        from src.asr.transcriber import Transcript, Segment, Word
        
        # Stage-based progress updates
        if job_id:
            from src.job_store import get_job_store
            store = get_job_store()
            store.update_progress(job_id, 15, "🎧 Transcribiendo con MLX Whisper...")
        
        # Use MLX optimized transcription
        if job_id:
            store.update_progress(job_id, 20, "🎤 Transcribiendo audio... (esto puede tomar varios minutos)")
        
        result = mlx_whisper.transcribe(
            str(video_path),
            path_or_hf_repo="mlx-community/whisper-large-v3-turbo",
            word_timestamps=True,
            language="es"
        )
        
        if job_id:
            store.update_progress(job_id, 70, "✅ Transcripción completa, procesando resultados...")
        
        segments = []
        for seg in result["segments"]:
            words = [
                Word(word=w["word"], start=w["start"], end=w["end"], score=w.get("probability", 1.0))
                for w in seg.get("words", [])
            ]
            segments.append(Segment(
                text=seg["text"].strip(),
                start=seg["start"],
                end=seg["end"],
                words=words,
            ))
        
        if job_id:
            store.update_progress(job_id, 75, f"✓ {len(segments)} segmentos transcritos")
        
        return Transcript(
            segments=segments,
            language="es",
            duration=result["segments"][-1]["end"] if result["segments"] else 0,
            source_file=str(video_path),
        )
    
    def _transcribe_clip(self, clip_path: Path, job_id: str = None) -> "Transcript":
        """Transcribe a short clip for subtitles."""
        return self._transcribe_video(clip_path, job_id)
    
    def run(
        self,
        start_episode: int = 1,
        end_episode: int = 999,
        dry_run: bool = False,
    ) -> dict:
        """
        Run batch processing on a range of episodes.
        
        Args:
            start_episode: First episode to process
            end_episode: Last episode to process
            dry_run: If True, only discover episodes without processing
            
        Returns:
            Summary dict with stats
        """
        console.print(f"\n[bold]🎬 Batch Clip Processor[/bold]")
        console.print(f"[dim]   Source: {self.base_path}[/dim]")
        console.print(f"[dim]   Episodes: {start_episode}-{end_episode}[/dim]")
        console.print(f"[dim]   Clips per episode: {self.clips_per_episode}[/dim]")
        
        # Discover episodes
        episodes = self.discover_episodes(start_episode, end_episode)
        console.print(f"\n[green]Found {len(episodes)} episodes to process[/green]")
        
        if dry_run:
            table = Table(title="Episodes Found")
            table.add_column("EP#", style="cyan")
            table.add_column("Folder")
            table.add_column("Video")
            table.add_column("Transcript")
            
            for ep in episodes:
                table.add_row(
                    f"{ep.episode_number:03d}",
                    ep.episode_folder.name[:40],
                    "✓" if ep.video_path.exists() else "✗",
                    "✓" if ep.transcript_path else "–",
                )
            
            console.print(table)
            return {"episodes_found": len(episodes), "dry_run": True}
        
        # Process episodes
        total_clips = 0
        processed = 0
        errors = []
        
        for ep in episodes:
            try:
                clips = self.process_episode(ep)
                total_clips += clips
                processed += 1
            except Exception as e:
                console.print(f"[red]Error processing EP{ep.episode_number}: {e}[/red]")
                errors.append((ep.episode_number, str(e)))
        
        # Summary
        console.print(f"\n[bold green]✓ Batch complete![/bold green]")
        console.print(f"   Episodes processed: {processed}/{len(episodes)}")
        console.print(f"   Total clips generated: {total_clips}")
        if errors:
            console.print(f"   Errors: {len(errors)}")
        
        return {
            "episodes_found": len(episodes),
            "episodes_processed": processed,
            "total_clips": total_clips,
            "errors": errors,
        }


def run_batch(
    start: int = 1,
    end: int = 999,
    dry_run: bool = False,
    clip_id: int | None = None,
    min_score: int = 70,
) -> dict:
    """
    Convenience function to run batch processing.
    
    Args:
        start: First episode number
        end: Last episode number
        clips_per_episode: Number of clips to generate per episode
        dry_run: If True, only show what would be processed
        clip_id: ID of a single clip to process
        
    Returns:
        Processing results summary
    """
    processor = BatchProcessor(
        external_drive_path="episodes",
        clip_id=clip_id,
        min_score=min_score,
    )
    return processor.run(start, end, dry_run)


if __name__ == "__main__":
    import sys
    
    # Simple CLI
    dry_run = "--dry-run" in sys.argv
    preview_mode = "--preview" in sys.argv
    from_preview = "--from-preview" in sys.argv
    
    # Parse episode range (default: start=7 because EP001-EP006 don't have video)
    start = 7
    end = 999
    clip_id = None
    min_score = 70
    
    for arg in sys.argv[1:]:
        if arg.startswith("--start="):
            start = int(arg.split("=")[1])
        elif arg.startswith("--end="):
            end = int(arg.split("=")[1])
        elif arg.startswith("--clip-id="):
            clip_id = int(arg.split("=")[1])
        elif arg.startswith("--min-score="):
            min_score = int(arg.split("=")[1])
    
    if preview_mode:
        # ============================================
        # PREVIEW MODE: Human-in-the-loop
        # Runs curation only, exports editable preview
        # ============================================
        console.print("\n[bold cyan]🔍 PREVIEW MODE[/bold cyan]")
        console.print("[dim]   Running curation only, exporting preview for review...[/dim]\n")
        
        processor = BatchProcessor(min_score=min_score)
        episodes = processor.discover_episodes(start, end)
        
        for ep in episodes:
            console.print(f"\n[bold blue]EP{ep.episode_number:03d}[/bold blue]")
            
            # Load or run curation
            from src.curation.curator_v2 import CuratedClipV2
            curation_path = ep.episode_folder / "curation.json"
            
            if curation_path.exists():
                console.print(f"[green]✓[/green] Using existing curation")
                with open(curation_path, "r") as f:
                    curated_clips = [CuratedClipV2.from_dict(d) for d in json.load(f)]
            else:
                console.print("[dim]   Running curation...[/dim]")
                # Would need to load transcript and run curator here
                console.print("[yellow]   No curation.json found. Run without --preview first.[/yellow]")
                continue
            
            # Export editable preview
            preview_path = ep.episode_folder / "preview_candidates.json"
            preview_data = {
                "episode": f"EP{ep.episode_number:03d}",
                "instructions": "Edit 'approved': true/false for each clip. Adjust timestamps if needed.",
                "min_score_filter": min_score,
                "clips": []
            }
            
            for i, clip in enumerate(curated_clips, 1):
                preview_data["clips"].append({
                    "id": i,
                    "approved": clip.virality_score.total >= min_score,
                    "score": clip.virality_score.total,
                    "title": clip.title,
                    "start_time": clip.start_time,
                    "end_time": clip.end_time,
                    "duration": clip.duration,
                    "category": clip.category,
                    "summary": clip.summary,
                    "review_notes": "",  # You can add notes here
                })
            
            with open(preview_path, "w") as f:
                json.dump(preview_data, f, indent=2, ensure_ascii=False)
            
            console.print(f"[green]✓[/green] Preview exported: {preview_path.name}")
            console.print(f"   Total clips: {len(curated_clips)}")
            console.print(f"   Auto-approved: {len([c for c in curated_clips if c.virality_score.total >= min_score])}")
        
        console.print("\n[bold green]✓ Preview complete![/bold green]")
        console.print("[dim]   Edit preview_candidates.json, then run with --from-preview[/dim]")
        sys.exit(0)
    
    if from_preview:
        console.print("\n[bold cyan]📋 FROM-PREVIEW MODE[/bold cyan]")
        console.print("[yellow]   Not yet implemented. For now, edit curation.json directly.[/yellow]")
        sys.exit(0)

    run_batch(start=start, end=end, dry_run=dry_run, clip_id=clip_id, min_score=min_score)

