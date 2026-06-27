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


def _episode_segments_for_clip(
    episode_folder: Path, start_time: float, end_time: float
) -> list[dict]:
    """Return episode-level speaker segments overlapping the clip window,
    shifted to clip-local timestamps (so the face tracker sees t=0 at
    the start of the clip, matching the pre-cut raw_clip file).

    Returns [] if there are no saved labels (preflight wasn't run, or
    user explicitly skipped). The pipeline then falls back to per-clip
    diarization as before.
    """
    labels_path = episode_folder / "speaker_face_labels.json"
    segs_path = episode_folder / ".identification" / "episode_speaker_segments.json"
    if not labels_path.exists() or not segs_path.exists():
        return []
    try:
        labels = json.loads(labels_path.read_text())
        if labels.get("_skipped"):
            return []
        segs = json.loads(segs_path.read_text())
    except Exception:
        return []
    out: list[dict] = []
    for s in segs:
        seg_start = float(s.get("start", 0))
        seg_end = float(s.get("end", 0))
        # Clamp to the clip window and shift to clip-local timestamps.
        a = max(seg_start, start_time)
        b = min(seg_end, end_time)
        if b <= a:
            continue
        out.append({
            "start": a - start_time,
            "end": b - start_time,
            "speaker": s.get("speaker", ""),
        })
    return out


class BatchProcessor:
    """
    Process episodes in batch, saving clips directly to the podcast folder.

    Structure (under settings.podcast_dir):
        EP###/
            clips/
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
        review_brief: bool | None = None, # NEW: per-job override for the brief gate (None = user setting)
        template_id: str | None = None, # NEW: clip template to apply (None = profile default)
    ):
        from packages.core.config import settings
        self.base_path = Path(external_drive_path) if external_drive_path else settings.podcast_dir
        self.template_id = template_id
        self.clips_per_episode = clips_per_episode
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.min_score = min_score
        self.use_supabase = use_supabase
        self.target_clip_id = clip_id
        self.auth_token = auth_token
        self.user_id = user_id or "anonymous"
        self.review_brief = review_brief
        
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
                f"⚠️ Podcast folder not accessible: {self.base_path}\n"
                f"   Set PODCAST_DIR in Settings to your episode library "
                f"(or AZELIA_DATA_DIR if using a custom data root)."
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
        
        return self._dispatch_after_curation(
            episode, valid_clips, job_id, start_from_clip
        )

    # ── Human-in-the-loop brief gate ─────────────────────────────────────────

    def _dispatch_after_curation(self, episode, valid_clips, job_id, start_from_clip):
        """After curation: open the brief gate (if enabled) or render directly.

        Gate ON  → park the job at `awaiting_brief` and return (no rendering).
        Gate OFF → render the filtered list exactly as before (no regression).
        """
        if self._brief_gate_open(job_id, start_from_clip, episode):
            return self._open_brief_gate(episode, job_id)
        return self.process_clips(
            episode, valid_clips, job_id=job_id, start_from_clip=start_from_clip
        )

    def _brief_gate_enabled(self) -> bool:
        """Whether the brief gate is active. Per-job override wins; otherwise the
        user setting REVIEW_BRIEF_BEFORE_PROCESSING, defaulting ON."""
        override = getattr(self, "review_brief", None)
        if override is not None:
            return bool(override)
        try:
            from packages.core.config import settings
            return bool(getattr(settings, "review_brief_before_processing", True))
        except Exception:
            return True  # default ON

    def _brief_gate_open(self, job_id, start_from_clip, episode) -> bool:
        """True if we should pause for the brief now — not on resume, not if the
        user already approved this episode's brief."""
        if not job_id or start_from_clip > 0:
            return False
        if not self._brief_gate_enabled():
            return False
        from packages.clips.curation.brief_builder import load_session
        try:
            session = load_session(episode.episode_folder)
        except Exception:
            session = None
        if session is not None and session.status == "approved":
            return False
        return True

    def _open_brief_gate(self, episode, job_id) -> int:
        """Build + persist the brief session and park the job awaiting review."""
        from packages.clips.curation.brief_builder import build_session, save_session
        from server.workers.job_store import get_job_store
        episode_id = f"EP{episode.episode_number:03d}"
        session = build_session(
            episode.episode_folder, episode_id, min_score=self.min_score
        )
        session.job_id = job_id
        save_session(episode.episode_folder, session)
        selected = sum(1 for c in session.candidates if c.selected)
        get_job_store().update_progress(
            job_id,
            68,
            f"Esperando tu revisión del brief ({selected} clips listos)…",
            status="awaiting_brief",
        )
        console.print(
            f"[cyan]⏸️ Brief gate abierto: {len(session.candidates)} candidatos, "
            f"{selected} seleccionados[/cyan]"
        )
        return 0

    # ── Render ───────────────────────────────────────────────────────────────

    def process_clips(self, episode, clips, job_id=None, start_from_clip=0) -> int:
        """Render exactly the given list of clips (extract → reframe → subtitles → export).

        Decoupled from curation so the brief-approve flow can render only the
        user-approved subset, while the gate-OFF path renders the filtered list.
        """
        from server.workers.job_store import get_job_store
        store = get_job_store() if job_id else None
        AUTO_APPROVE_SCORE = 80

        # Create approved/review subfolders
        approved_folder = episode.clips_folder / "approved"
        review_folder = episode.clips_folder / "review"
        approved_folder.mkdir(parents=True, exist_ok=True)
        review_folder.mkdir(parents=True, exist_ok=True)

        clips_generated = 0

        if start_from_clip > 0:
            console.print(f"[cyan]▶️ Resuming from clip {start_from_clip + 1}[/cyan]")

        if store and job_id:
            store.set_total_clips(job_id, len(clips))

        for i, clip in enumerate(clips, 1):
            # Skip already processed clips when resuming
            if i <= start_from_clip:
                console.print(f"[dim]   Skipping clip_{i:02d} (already processed)[/dim]")
                continue

            # In-process abort check — set by /pause and /cancel.
            if self._aborted():
                console.print(f"[yellow]⏸️ Pipeline aborted at clip {i-1}/{len(clips)} (pause/cancel)[/yellow]")
                return clips_generated

            # Belt-and-suspenders: also poll the JobStore in case the abort
            # event was missed (e.g. process restart between pause and resume).
            if store and job_id:
                current_job = store.get_job(job_id)
                if current_job and current_job.status in ('paused', 'cancelled'):
                    console.print(f"[yellow]⏸️ Job {current_job.status} at clip {i-1}/{len(clips)}[/yellow]")
                    return clips_generated

            score = clip.virality_score.total
            is_approved = score >= AUTO_APPROVE_SCORE
            target_folder = approved_folder if is_approved else review_folder
            status_icon = "✓" if is_approved else "📋"

            clip_name = f"clip_{i:02d}"
            console.print(f"[dim]   Processing {clip_name} ({clip.start_time:.0f}s-{clip.end_time:.0f}s) score={score} {status_icon}[/dim]")

            if store and job_id:
                pct = 70 + (i / len(clips)) * 30
                store.update_progress(job_id, int(pct), f"Generando {clip_name}/{len(clips)} ({status_icon})")

            # ✅ AUTO-RESUME: Check if clip already exists
            final_path_approved = approved_folder / f"{clip_name}.mp4"
            final_path_review = review_folder / f"{clip_name}.mp4"

            if final_path_approved.exists() or final_path_review.exists():
                console.print(f"[dim]   ⏩ Skipping {clip_name} (already exists)[/dim]")
                if store and job_id:
                    current_generated = clips_generated + (1 if final_path_approved.exists() else 0)
                    store.update_clip_progress(
                        job_id,
                        clip_index=i,
                        clips_generated=current_generated,
                        message=f"Clip {i} ya existe, saltando..."
                    )
                continue

            generated = self._render_one_clip(
                episode, clip, clip_name, target_folder, is_approved, i, len(clips)
            )
            clips_generated += generated

            # Update job progress (for pause/resume)
            if generated and store and job_id:
                store.update_clip_progress(
                    job_id,
                    clip_index=i,  # 1-indexed becomes the "completed up to" index
                    clips_generated=clips_generated,
                    message=f"Procesado clip {i}/{len(clips)}",
                )

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

    def _render_one_clip(
        self, episode, clip, clip_name, target_folder, is_approved, i, total
    ) -> int:
        """Render a single clip end-to-end. Returns 1 on success, 0 on failure."""
        from packages.clips.vision.reframer import reframe_video
        from packages.clips.subtitles.generator import SubtitleGenerator
        from packages.clips.templates.render import template_to_render_plan
        import torch
        import gc

        # Resolve the clip template once (profile default when template_id is None).
        from packages.core.config import settings
        from packages.clips.templates.store import TemplateStore
        plan = template_to_render_plan(
            TemplateStore(settings.templates_dir()).resolve(self.template_id)
        )

        try:
            # Use temp files for intermediate processing
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)

                # 3a. Extract clip from source
                raw_clip = tmp_path / "raw.mp4"
                self._extract_clip(
                    episode.video_path, raw_clip, clip.start_time, clip.end_time
                )

                # 3b. High-precision transcription/diarization for this clip only.
                voice_centroids = self._episode_voice_centroids(episode.episode_folder)
                clip_transcript = self._transcribe_clip(
                    raw_clip, voice_centroids=voice_centroids
                )

                # 3c. Reframe per the template's layout (split-screen or full-screen)
                split_clip = tmp_path / "split.mp4"
                reframe_video(
                    video_path=str(raw_clip),
                    output_path=str(split_clip),
                    pre_cut=True,  # Clip already extracted, don't seek again
                    speaker_segments=clip_transcript.segments,
                    episode_folder=episode.episode_folder,
                    layout_type=plan.layout_type,
                    wide_height_ratio=plan.wide_height_ratio,
                )

                # 3d. Generate subtitles from the template's style
                subs_path = tmp_path / "subs.ass"
                generator = SubtitleGenerator(style=plan.style)
                generator.generate_word_by_word(
                    clip_transcript, str(subs_path),
                    words_per_line=plan.words_per_line, animation=plan.animation,
                    intro_title=plan.intro_title, clip_title=getattr(clip, "title", ""),
                )

                # 3e. Burn subtitles (+ optional logo / progress bar) and save
                final_path = target_folder / f"{clip_name}.mp4"
                self._burn_subtitles(
                    split_clip, subs_path, final_path,
                    branding=plan.branding,
                    progress_bar=getattr(plan, "progress_bar", None),
                    data_dir=settings.data_dir,
                    duration=clip.end_time - clip.start_time,
                )

                # 3e-bis. Concatenate intro/outro bumpers around the clip (T12).
                self._apply_bumpers(
                    final_path, getattr(plan, "bumpers", None), settings.data_dir, tmp_path
                )

                # 3f. Save caption to text file
                caption_path = target_folder / f"{clip_name}_caption.txt"
                caption_content = f"{clip.social_caption}\n\n{' '.join(clip.caption_hashtags)}"
                caption_path.write_text(caption_content, encoding='utf-8')

                folder_name = "approved" if is_approved else "review"
                console.print(f"[green]   ✓ {clip_name} saved to {folder_name}/[/green]")

            # Successful clip cleanup
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
                torch.mps.synchronize()
            gc.collect()
            return 1

        except Exception as e:
            console.print(f"[red]   ✗ Error processing {clip_name}: {e}[/red]")
            try:
                if torch.backends.mps.is_available():
                    torch.mps.empty_cache()
            except Exception:
                pass
            gc.collect()
            return 0

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

    def _burn_subtitles(
        self, video: Path, subs: Path, output: Path,
        branding=None, progress_bar=None, data_dir=None, duration=None,
    ) -> None:
        """Burn subtitles into video using FFmpeg with libass.

        Uses the imageio-ffmpeg bundled binary from the venv (compiled with
        libass) to avoid issues with the default Homebrew FFmpeg which lacks
        the ass/subtitles filters. Optionally overlays a branding logo (T10)
        and a progress bar (T11) via the pure command builder.
        """
        import shutil, os, tempfile
        from packages.clips.templates.ffmpeg_filters import build_burn_command

        ffmpeg_exe = self._get_ffmpeg_exe()

        # Copy the .ass to /tmp with a safe name to avoid AVFilter path-escaping issues
        fd, safe_subs_str = tempfile.mkstemp(suffix=".ass", dir="/tmp")
        os.close(fd)
        shutil.copy2(str(subs), safe_subs_str)
        try:
            cmd = build_burn_command(
                ffmpeg_exe, str(video), safe_subs_str, str(output),
                branding=branding, progress_bar=progress_bar,
                data_dir=data_dir, duration=duration,
            )
            run_ffmpeg(cmd, timeout=300)
        finally:
            try:
                os.unlink(safe_subs_str)
            except Exception:
                pass


    def _apply_bumpers(self, clip_path: Path, bumpers, data_dir, tmp_path: Path) -> None:
        """Concatenate intro/outro bumpers around the rendered clip in place.

        No-op when there are no bumpers. Missing bumper files are skipped with a
        console warning (non-fatal). On any concat failure the original clip is
        kept untouched.
        """
        if bumpers is None:
            return
        import shutil
        from packages.clips.templates.bumpers import (
            build_concat_command,
            build_concat_plan,
            needs_concat,
        )

        inputs, warnings = build_concat_plan(bumpers, str(clip_path), data_dir)
        for which in warnings:
            console.print(f"[yellow]   ⚠ bumper {which} no encontrado; se omite[/yellow]")
        if not needs_concat(inputs):
            return

        stitched = tmp_path / "with_bumpers.mp4"
        cmd = build_concat_command(self._get_ffmpeg_exe(), inputs, str(stitched))
        try:
            run_ffmpeg(cmd, timeout=300)
            shutil.move(str(stitched), str(clip_path))
        except Exception as e:
            console.print(f"[yellow]   ⚠ no se pudieron añadir bumpers ({e}); se deja el clip sin ellos[/yellow]")

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

    def _episode_voice_centroids(self, episode_folder: Path) -> dict | None:
        """Load `voice_embeddings.json` for the episode if it exists.

        Returns the {SPEAKER_NN: [192-D list]} dict (raw JSON shape) so
        the LocalWhisperSource can use it to relabel per-clip ECAPA. We
        only load if the user has actually labeled this episode (i.e.,
        speaker_face_labels.json present and not _skipped).
        """
        labels_path = episode_folder / "speaker_face_labels.json"
        emb_path = episode_folder / ".identification" / "voice_embeddings.json"
        if not labels_path.exists() or not emb_path.exists():
            return None
        try:
            labels = json.loads(labels_path.read_text())
            if labels.get("_skipped"):
                return None
            return json.loads(emb_path.read_text())
        except Exception:
            return None

    def _transcribe_clip(self, clip_path: Path, job_id: str = None, voice_centroids: dict | None = None) -> "Transcript":
        """Transcribe a short extracted clip for word-level subtitles.

        ALWAYS uses local Whisper. Never the user-Supabase source — that one
        looks up transcripts by episode_id, and per-clip temp files don't
        have an episode_id. The episode-level transcription_driver is only
        for the full episode (where the user keeps their canonical transcripts).

        When voice_centroids are provided (the episode has L3 labels),
        the diarizer relabels per-clip windows directly against the
        saved fingerprints, producing STABLE episode-level SPEAKER_NN
        labels that match the labels file. Without them, we pin to
        k=2 — podcast clips are almost always 2-person dialogue, and
        ECAPA silhouette auto-detect over-clusters on short audio.
        """
        from packages.clips.transcription.local_whisper import LocalWhisperSource

        # Re-create the source if the centroid context changed — this
        # only happens when transitioning between labeled / unlabeled
        # episodes within a single batch run.
        cache_key = id(voice_centroids) if voice_centroids else "default"
        if getattr(self, "_local_whisper_clip_key", None) != cache_key:
            if voice_centroids:
                self._local_whisper_clip_source = LocalWhisperSource(
                    voice_centroids=voice_centroids,
                )
            else:
                self._local_whisper_clip_source = LocalWhisperSource(num_speakers_hint=2)
            self._local_whisper_clip_key = cache_key
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
    # Pass external_drive_path=None so BatchProcessor falls back to
    # settings.podcast_dir — the user-configurable library root that the
    # onboarding wizard writes to secrets.env. Avoids the old hardcoded
    # path that only worked on a specific machine.
    processor = BatchProcessor(
        external_drive_path=None,
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

