"""Batch processor for generating clips from podcast episodes.

Reads episodes from external drive, processes through full pipeline,
and saves clips directly to external drive in organized structure.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from packages.clips.transcription.transcriber import Transcript

from rich.console import Console
from rich.table import Table

from packages.core.utils import run_ffmpeg, validate_video

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
    external_drive/Backup Inminente/EP###/clips/
        ├── clip_01.mp4
        ├── clip_01_caption.txt
        ├── clip_02.mp4
        ├── clip_02_caption.txt
        └── ...
    """
    
    def __init__(
        self,
        external_drive_path: str | Path | None = None,
        clips_per_episode: int | None = None,  # DEPRECATED: No longer limits clips. All clips meeting score threshold are processed.
        min_duration: int = 30,
        max_duration: int = 180,  # Up to 3 min with manual review for >90s
        min_score: int = 70,  # Minimum virality score threshold (clips below this are skipped)
        use_supabase: bool = False,  # NEW: Use Supabase transcripts instead of WhisperX
        clip_id: int | None = None,  # NEW: Specify a single clip to re-process (1-indexed)
        transcription_config: dict | None = None, # NEW: Configuration for transcription source
        auth_token: str | None = None, # NEW: User token for community data sync
        user_id: str | None = None, # NEW: User ID for telemetry reporting
    ):
        from packages.core.config import settings
        self.base_path = Path(external_drive_path) if external_drive_path else settings.podcast_dir
        self.clips_per_episode = clips_per_episode
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.min_score = min_score
        self.use_supabase = use_supabase
        self.target_clip_id = clip_id
        self.auth_token = auth_token
        self.user_id = user_id or "anonymous"
        
        # Initialize Transcription Driver
        from packages.clips.transcription.driver import TranscriptionDriver
        self.transcription_config = transcription_config or {}
        self.transcription_driver = TranscriptionDriver.get_source_from_config(self.transcription_config)
        
        # Initialize Analytics Sync
        from server.services.analytics import AnalyticsSync
        self.analytics_sync = AnalyticsSync(auth_token=auth_token)
        
        if not self.base_path.exists():
            raise FileNotFoundError(
                f"⚠️ External drive not accessible: {self.base_path}\n"
                f"   Please connect the external hard drive and ensure the symlink exists:\n"
                r"   ln -s /Volumes/[DiskName]/Backup\ Inminente external_drive/Backup\ Inminente"
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
            
            # Parse episode number from folder name (e.g., "EP108 - Title")
            folder_name = folder.name
            if not folder_name.startswith("EP"):
                continue
            
            try:
                # Extract number: "EP108 - Title" -> 108
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
        from server.workers.job_store import get_job_store
        store = get_job_store() if job_id else None
        
        from packages.clips.transcription.transcriber import Transcript
        from packages.clips.curation.pipeline import CurationPipeline
        from packages.clips.vision.reframer import reframe_video
        from packages.clips.subtitles.generator import SubtitleGenerator
        from packages.core.services.telemetry import telemetry
        
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
        
        if self.use_supabase:
            console.print(f"[dim]   Loading transcript from Supabase...[/dim]")
            from server.sources.supabase_transcripts import get_transcript_from_supabase
            transcript = get_transcript_from_supabase(f"EP{episode.episode_number:03d}")
            
            if transcript is None:
                # Fallback to local or re-transcribe
                console.print(f"[yellow]   Supabase transcript not found, falling back to local...[/yellow]")
                if episode.transcript_path and episode.transcript_path.exists():
                    transcript = Transcript.load(episode.transcript_path)
                else:
                    console.print(f"[dim]   Transcribing episode (this takes time)...[/dim]")
                    transcript = self._transcribe_video(episode.video_path, job_id=job_id)
                    transcript.save(episode.episode_folder / "transcript.json")
        else:
            # Traditional mode: local transcript or WhisperX
            if episode.transcript_path and episode.transcript_path.exists():
                console.print(f"[dim]   Loading existing transcript...[/dim]")
                transcript = Transcript.load(episode.transcript_path)
            else:
                console.print(f"[dim]   Transcribing episode (this takes time)...[/dim]")
                ep_id_str = f"EP{episode.episode_number:03d}"
                transcript = self._transcribe_video(episode.video_path, job_id=job_id, episode_id=ep_id_str)
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
                from packages.clips.curation.models import CuratedClip
                data = json.load(f)
                curated_clips = [CuratedClip.model_validate(d) for d in data]
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
            
            curator = CurationPipeline()
            from packages.core.config import settings
            
            # Local Intelligence: Fetch user's personalized patterns (ephemeral, in-memory only)
            from packages.core.services.local_intelligence import local_intelligence
            from packages.clips.curation.models import CurationConfig
            li_patterns = local_intelligence.get_user_patterns(self.user_id)
            
            curation_config = CurationConfig(
                podcast_name=settings.podcast_name,
                high_retention_patterns=li_patterns.get("high_retention_patterns", []),
                preferred_clip_formats=li_patterns.get("preferred_clip_formats", []),
            )
            
            curated_clips = curator.curate(
                transcript,
                top_n=None,  # Get ALL clips, not limited to clips_per_episode
                min_duration=self.min_duration,
                max_duration=self.max_duration,
                episode_number=episode.episode_number,
                podcast_name=settings.podcast_name,
                progress_callback=curation_progress,
                pause_callback=check_pause,
                config=curation_config,
            )
            
            # Save curation results for future re-processing ONLY if we found clips
            # This prevents caching a complete API failure (which returns 0 clips)
            if curated_clips:
                with open(curation_path, "w") as f:
                    json.dump([c.model_dump() for c in curated_clips], f, indent=2, ensure_ascii=False)
                console.print(f"[dim]   Curation saved to {curation_path.name}[/dim]")
            else:
                console.print(f"[yellow]   No clips found, skipping cache save.[/yellow]")
        
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
        
        # Track curation metrics using telemetry
        try:
            avg_score = sum(c.virality_score.total for c in valid_clips) / len(valid_clips) if valid_clips else 0.0
            categories = list({c.category for c in valid_clips if hasattr(c, 'category')})
            telemetry.track_curation_metrics(
                user_id=self.user_id,
                num_clips_found=len(valid_clips),
                avg_virality_score=avg_score,
                top_topics=categories,
                duration_seconds=getattr(transcript, 'duration', None),
            )
        except Exception as e:
            console.print(f"[dim]Telemetry tracking warning: {e}[/dim]")
        
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
                    
                    # 3b. High-precision transcription and diarization strictly for this clip
                    # (As per user request, we process each clip independently to guarantee high quality word-level timestamps and diarization)
                    clip_transcript = self._transcribe_clip(raw_clip)
                    
                    # 3c. Create split-screen with tracking
                    # Passes the clip-specific diarization into the FaceTracker
                    split_clip = tmp_path / "split.mp4"
                    reframe_video(
                        video_path=str(raw_clip),
                        output_path=str(split_clip),
                        pre_cut=True,  # Clip already extracted, don't seek again
                        speaker_segments=clip_transcript.segments,
                    )
                    
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
                    
                    # 3g. Sync to Community Intelligence (if approved & enabled)
                    if is_approved and self.analytics_sync.Enabled:
                        try:
                            clip_data = {
                                "clip_hash": f"EP{episode.episode_number}_{i}_{int(clip.start_time)}",
                                "video_title": clip.title,
                                "duration": clip.duration,
                                "hook_type": clip.category,
                                "style": "split_screen_hybrid",
                                "score": clip.virality_score.total
                            }
                            self.analytics_sync.sync_clip(clip_data)
                        except Exception as e:
                            console.print(f"[yellow]   ⚠️ Sync warning: {e}[/yellow]")
                            
                    # 3h. Telemetry: Send anonymous clip signals
                    try:
                        telemetry.track_clip_performance(
                            user_id=self.user_id,
                            predicted_score=clip.virality_score.total,
                            hook_type=getattr(clip, 'category', None),
                            duration_seconds=clip.duration,
                            word_count=len(clip_transcript.text.split()) if clip_transcript else None
                        )
                    except Exception as e:
                        pass
                    
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
    
    def _transcribe_video(self, video_path: Path, job_id: str = None, episode_id: str = None) -> "Transcript":
        """Transcribe using the configured driver (Local, AssemblyAI, or Supabase)."""
        from packages.clips.transcription.supabase import SupabaseSource
        
        # Determine resource (Path or ID)
        resource = str(video_path)
        if isinstance(self.transcription_driver, SupabaseSource):
            if episode_id:
                resource = episode_id
            else:
                console.print("[yellow]Warning: SupabaseSource requires episode_id, using filename as fallback[/yellow]")
                resource = video_path.stem
        
        # Progress updates
        if job_id:
            from server.workers.job_store import get_job_store
            store = get_job_store()
            store.update_progress(job_id, 20, "🎤 Obteniendo transcripción...")
            # The provided change was syntactically incorrect and used undefined variables (clip, ep, settings).
            # Assuming the intent was to pass podcast_name to the transcription config if applicable,
            # but the current transcription driver doesn't directly support it.
            # The original code for transcription is kept as is, as the requested change
            # cannot be applied syntactically or logically in this specific method.
            # If the intent was to add a new parameter to get_transcript, that would require
            # modifying the get_transcript signature and its implementations.
            # The instruction "Pass settings.podcast_name" is too vague without a clear target function.
            # The provided code snippet for the change was malformed.
            # Therefore, no change is made to the _transcribe_video method based on the provided snippet.
            
        try:
            return self.transcription_driver.get_transcript(resource, **self.transcription_config)
        except Exception as e:
            console.print(f"[red]Transcription failed: {e}[/red]")
            raise e
    
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
    use_supabase: bool = False,
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
        external_drive_path="external_drive/Backup Inminente",
        clip_id=clip_id,
        min_score=min_score,
        use_supabase=use_supabase,
    )
    return processor.run(start, end, dry_run)


if __name__ == "__main__":
    import sys
    
    # Simple CLI
    dry_run = "--dry-run" in sys.argv
    preview_mode = "--preview" in sys.argv
    from_preview = "--from-preview" in sys.argv
    use_supabase = "--use-supabase" in sys.argv
    
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
            from packages.clips.curation.models import CuratedClip
            curation_path = ep.episode_folder / "curation.json"
            
            if curation_path.exists():
                console.print(f"[green]✓[/green] Using existing curation")
                with open(curation_path, "r") as f:
                    curated_clips = [CuratedClip.model_validate(d) for d in json.load(f)]
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

    run_batch(start=start, end=end, dry_run=dry_run, clip_id=clip_id, min_score=min_score, use_supabase=use_supabase)

