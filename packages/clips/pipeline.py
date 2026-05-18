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


def _load_user_profile_context(user_id: str | None) -> dict:
    """Profile context disabled in local-first MVP (no central profiles DB).

    Returns empty dict — Curation pipeline falls back to generic heuristics.
    Re-introduce in v0.2 reading from local SettingsForm (Workspace tab).
    """
    return {}


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

        # Analytics sync removed in local-first MVP (no central DB)
        self.analytics_sync = None

        # Abort signal — pipeline polls this between heavy steps to honor
        # pause / cancel without crashing concurrent MLX workers.
        # Set by the /pause and /cancel endpoints via server.dependencies.
        self.abort_event = None
        
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
    
    def _aborted(self) -> bool:
        """True if pause/cancel was triggered for this job — used to short-circuit
        the render loop between heavy steps so concurrent MLX workers can't collide."""
        return bool(self.abort_event and self.abort_event.is_set())

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

        # Attach the per-job abort_event so checkpoints can detect pause/cancel.
        # Falls back to no-op if dependencies module isn't available (e.g. CLI).
        if job_id and not self.abort_event:
            try:
                from server.dependencies import get_abort_event
                self.abort_event = get_abort_event(job_id)
            except Exception:
                self.abort_event = None

        # Register this thread as the active job so ffmpeg subprocesses spawned
        # during clip rendering are killable via kill_job_subprocesses(job_id)
        # from the /pause and /cancel endpoints — instant abort, not "wait for
        # the current clip to finish".
        if job_id:
            from packages.core.process_registry import set_active_job
            set_active_job(job_id)
        
        from packages.clips.transcription.transcriber import Transcript
        from packages.clips.curation.pipeline import CurationPipeline
        from packages.clips.vision.reframer import reframe_video
        from packages.clips.subtitles.generator import SubtitleGenerator
        # telemetry removed in local-first MVP

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
            # Honest progress label — reflects which transcript source is being tried first.
            store.update_progress(
                job_id,
                29,
                "Fetching transcript from your Supabase…" if self.use_supabase else "Loading transcript…",
            )

        # Step 1: Get transcript
        # If the user has their own Supabase configured for transcripts, try
        # that first. Falls through to local/WhisperX on any failure (not found,
        # DNS error, auth, anything) so a misconfigured/down Supabase never
        # blocks the pipeline.
        transcript = None
        if self.use_supabase:
            console.print("[dim]   Loading transcript from your Supabase…[/dim]")
            try:
                from server.sources.supabase_transcripts import get_transcript_from_supabase
                transcript = get_transcript_from_supabase(f"EP{episode.episode_number:03d}")
                if transcript is None:
                    console.print("[yellow]   Not found in your Supabase — falling back to local.[/yellow]")
                    if store and job_id:
                        store.update_progress(job_id, 30, "Supabase miss — using local transcript")
            except Exception as e:
                console.print(f"[yellow]   Supabase fetch failed ({type(e).__name__}: {str(e)[:80]}) — falling back to local.[/yellow]")
                if store and job_id:
                    store.update_progress(job_id, 30, "Supabase error — using local transcript")
                transcript = None

        if transcript is None:
            # Traditional mode: local transcript or WhisperX
            if episode.transcript_path and episode.transcript_path.exists():
                console.print(f"[dim]   Loading existing transcript...[/dim]")
                transcript = Transcript.load(episode.transcript_path)
            else:
                console.print(f"[dim]   Transcribing episode (this takes time)...[/dim]")
                ep_id_str = f"EP{episode.episode_number:03d}"
                transcript = self._transcribe_video(episode.video_path, job_id=job_id, episode_id=ep_id_str)
                if transcript is None:
                    raise RuntimeError(
                        f"Could not obtain a transcript for {ep_id_str}: "
                        "no Supabase row, no local transcript.json, and Whisper returned nothing."
                    )
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

            # Local Intelligence removed in local-first MVP (no central learning).
            from packages.clips.curation.models import CurationConfig
            li_patterns = {"high_retention_patterns": [], "preferred_clip_formats": []}

            # Podcast identity — pulled from profiles so the agents can be
            # podcast-aware instead of applying generic viral heuristics.
            profile_ctx = _load_user_profile_context(self.user_id)

            # Auto-detect episode language. Whisper sets `transcript.language`
            # during transcription; for transcripts loaded from JSON or the
            # API path that may be the schema default, so we fall back to a
            # text-based detector. The user-level override in the profile
            # (Settings → Advanced) wins over both — that's the escape hatch
            # for bilingual podcasts that want to force one output language.
            from packages.core.utils import detect_language as _detect_lang
            episode_language = (profile_ctx.get("language") or "").strip()
            if not episode_language:
                episode_language = (getattr(transcript, "language", "") or "").strip().lower()
            if not episode_language or episode_language == "es":
                # `es` is the schema default in Transcript — re-detect to
                # avoid mislabelling English/other-language transcripts as ES.
                detected = _detect_lang(transcript.full_text, fallback="")
                if detected:
                    episode_language = detected
            episode_language = episode_language or "en"

            curation_config = CurationConfig(
                podcast_name=settings.podcast_name,
                high_retention_patterns=li_patterns.get("high_retention_patterns", []),
                preferred_clip_formats=li_patterns.get("preferred_clip_formats", []),
                content_niche=profile_ctx.get("content_niche", ""),
                user_role=profile_ctx.get("user_role", ""),
                primary_goal=profile_ctx.get("primary_goal", ""),
                region=profile_ctx.get("region", ""),
                episode_format=profile_ctx.get("episode_format", ""),
                language=episode_language,
                is_pro_tier=bool(profile_ctx.get("is_pro_tier", False)),
                user_cohort_hash=profile_ctx.get("cohort_hash", ""),
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

            # Persist the Critic's full decision (approved + rejected) so the
            # Review UI can show the user WHY clips were cut and collect
            # feedback ("agree" / "disagree") that can later be fed back into
            # the Critic prompt.
            try:
                last = getattr(curator.critic, "last_response", None)
                if last is not None and last.approved_clips:
                    decisions_path = episode.episode_folder / "critic_decisions.json"
                    decisions_path.write_text(
                        json.dumps(
                            [c.model_dump() for c in last.approved_clips],
                            indent=2,
                            ensure_ascii=False,
                        )
                    )
                    rejected_n = sum(1 for c in last.approved_clips if not c.approved)
                    console.print(
                        f"[dim]   Critic decisions saved ({rejected_n} rejected) → "
                        f"{decisions_path.name}[/dim]"
                    )
            except Exception as e:
                console.print(
                    f"[yellow]   Could not save critic_decisions.json: {e}[/yellow]"
                )
        
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
        
        # Telemetry removed in local-first MVP — metrics stay local in JobStore.
        
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

            # In-process abort check — set by /pause and /cancel.
            # Surfaces faster than the JobStore poll below because no DB round-trip.
            if self._aborted():
                console.print(f"[yellow]⏸️ Pipeline aborted at clip {i-1}/{len(valid_clips)} (pause/cancel)[/yellow]")
                return clips_generated

            # Belt-and-suspenders: also poll the JobStore in case the abort
            # event was missed (e.g. process restart between pause and resume).
            if store and job_id:
                current_job = store.get_job(job_id)
                if current_job and current_job.status in ('paused', 'cancelled'):
                    console.print(f"[yellow]⏸️ Job {current_job.status} at clip {i-1}/{len(valid_clips)}[/yellow]")
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
                    
                    # Community Intelligence sync + clip telemetry removed in local-first MVP.


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

        # Clear the active-job marker so subprocesses spawned by unrelated
        # work in this thread later (unlikely but possible) aren't registered
        # under a job that has finished.
        if job_id:
            try:
                from packages.core.process_registry import set_active_job
                set_active_job(None)
            except Exception:
                pass

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
    
    @staticmethod
    def _get_ffmpeg_exe() -> str:
        """Return the best available FFmpeg binary.
        
        Prefers the imageio-ffmpeg bundled binary (compiled with libass)
        over the system FFmpeg (Homebrew default lacks libass).
        """
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            return "ffmpeg"

    def _burn_subtitles(self, video: Path, subs: Path, output: Path) -> None:
        """Burn subtitles into video using FFmpeg with libass.
        
        Uses the imageio-ffmpeg bundled binary from the venv (compiled with
        libass) to avoid issues with the default Homebrew FFmpeg which lacks
        the ass/subtitles filters.
        """
        import shutil, os, tempfile

        ffmpeg_exe = self._get_ffmpeg_exe()

        # Copy the .ass to /tmp with a safe name to avoid AVFilter path-escaping issues
        fd, safe_subs_str = tempfile.mkstemp(suffix=".ass", dir="/tmp")
        os.close(fd)
        shutil.copy2(str(subs), safe_subs_str)
        try:
            cmd = [
                ffmpeg_exe, "-y",
                "-i", str(video),
                "-vf", f"ass={safe_subs_str}",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                str(output)
            ]
            run_ffmpeg(cmd, timeout=300)
        finally:
            try:
                os.unlink(safe_subs_str)
            except Exception:
                pass


    def _transcribe_video(self, video_path: Path, job_id: str = None, episode_id: str = None) -> "Transcript":
        """Transcribe the full episode video using the configured driver.

        The driver may be local Whisper, AssemblyAI, or the user's own
        Supabase (transcripts pulled by episode_id).
        """
        resource = str(video_path)
        if job_id:
            from server.workers.job_store import get_job_store
            store = get_job_store()
            store.update_progress(job_id, 20, "🎤 Obteniendo transcripción...")
        try:
            return self.transcription_driver.get_transcript(resource, **self.transcription_config)
        except Exception as e:
            console.print(f"[red]Transcription failed: {e}[/red]")
            raise e

    def _transcribe_clip(self, clip_path: Path, job_id: str = None) -> "Transcript":
        """Transcribe a short extracted clip for word-level subtitles.

        ALWAYS uses local Whisper. Never the user-Supabase source — that one
        looks up transcripts by episode_id, and per-clip temp files don't
        have an episode_id. The episode-level transcription_driver is only
        for the full episode (where the user keeps their canonical transcripts).

        We pin the diarizer to num_speakers=2 for per-clip slices. On 30-90s
        of audio, ECAPA's silhouette-based auto-detect often picks k=3 from
        acoustic drift in a single speaker (different breathing pace, mic
        proximity changes, etc.), creating a phantom SPEAKER_NN whose
        segments are actually one of the real speakers. That phantom maps
        to a face via the bijective matcher's surplus-fallback, and when
        the phantom's segments fire the camera shows the WRONG person.
        Forcing k=2 is the right product call: podcast clips are almost
        always 2-person dialogue. Multi-person panels would still suffer
        but the episode-level transcript path keeps auto-detect for those.
        """
        from packages.clips.transcription.local_whisper import LocalWhisperSource

        if not hasattr(self, "_local_whisper_clip_source"):
            self._local_whisper_clip_source = LocalWhisperSource(num_speakers_hint=2)
        try:
            return self._local_whisper_clip_source.get_transcript(str(clip_path))
        except Exception as e:
            console.print(f"[red]Clip transcription failed: {e}[/red]")
            raise e
    
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

