"""Advanced AI-powered clip curator using multi-agent pipeline (Finder→Critic→Ranker)."""

import json
import math
import re
import time
from pathlib import Path
from dataclasses import dataclass, field

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from src.asr.transcriber import Transcript
from src.llm_provider import get_llm
from src.curation.signals import TextAnalyzer, AudioAnalyzer, StructuralAnalyzer
from src.curation.prompts import (
    FINDER_SYSTEM, FINDER_USER_TEMPLATE,
    CRITIC_SYSTEM, CRITIC_USER_TEMPLATE,
    RANKER_SYSTEM, RANKER_USER_TEMPLATE,
    CAPTION_GENERATOR_SYSTEM, CAPTION_GENERATOR_USER,
)

console = Console()

class CurationLogger:
    """Logs curation data for AI self-improvement."""
    
    def __init__(self, log_dir: str = "data"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.log_file = self.log_dir / "community_logs.jsonl"
        
    def log_event(self, event_type: str, data: dict):
        """Append a log entry to the JSONL file."""
        entry = {
            "timestamp": time.time(),
            "event": event_type,
            "data": data
        }
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

# Global logger
curation_logger = CurationLogger()


@dataclass
class ViralityScoreV2:
    """Enhanced virality scoring with 10 dimensions."""
    # Text-based (40 pts max)
    hook_strength: int = 0
    quotability: int = 0
    storytelling: int = 0
    controversy: int = 0
    
    # Audio-based (30 pts max)
    energy_level: int = 0
    pacing: int = 0
    emotional_arc: int = 0
    
    # Structural (30 pts max)
    standalone_clarity: int = 0
    segment_completeness: int = 0
    optimal_duration: int = 0
    
    @property
    def total(self) -> int:
        return sum([
            self.hook_strength, self.quotability, 
            self.storytelling, self.controversy,
            self.energy_level, self.pacing, self.emotional_arc,
            self.standalone_clarity, self.segment_completeness,
            self.optimal_duration
        ])
    
    @property
    def text_score(self) -> int:
        return self.hook_strength + self.quotability + self.storytelling + self.controversy
    
    @property
    def audio_score(self) -> int:
        return self.energy_level + self.pacing + self.emotional_arc
    
    @property
    def structural_score(self) -> int:
        return self.standalone_clarity + self.segment_completeness + self.optimal_duration
    
    def to_dict(self) -> dict:
        return {
            "hook_strength": self.hook_strength,
            "quotability": self.quotability,
            "storytelling": self.storytelling,
            "controversy": self.controversy,
            "energy_level": self.energy_level,
            "pacing": self.pacing,
            "emotional_arc": self.emotional_arc,
            "standalone_clarity": self.standalone_clarity,
            "segment_completeness": self.segment_completeness,
            "optimal_duration": self.optimal_duration,
            "total": self.total,
        }

    @staticmethod
    def from_dict(data: dict) -> 'ViralityScoreV2':
        return ViralityScoreV2(
            hook_strength=data.get("hook_strength", 0),
            quotability=data.get("quotability", 0),
            storytelling=data.get("storytelling", 0),
            controversy=data.get("controversy", 0),
            energy_level=data.get("energy_level", 0),
            pacing=data.get("pacing", 0),
            emotional_arc=data.get("emotional_arc", 0),
            standalone_clarity=data.get("standalone_clarity", 0),
            segment_completeness=data.get("segment_completeness", 0),
            optimal_duration=data.get("optimal_duration", 0),
        )


@dataclass
class CuratedClipV2:
    """A curated clip with enhanced metadata."""
    start_time: float
    end_time: float
    title: str
    summary: str
    virality_score: ViralityScoreV2
    category: str
    suggested_hashtags: list[str] = field(default_factory=list)
    social_caption: str = ""
    caption_hashtags: list[str] = field(default_factory=list)
    pending_review: bool = False  # True if clip needs manual approval
    review_reason: str = ""  # Reason for pending review
    
    @property
    def duration(self) -> float:
        return self.end_time - self.start_time
    
    def to_dict(self) -> dict:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "title": self.title,
            "summary": self.summary,
            "virality_score": self.virality_score.to_dict(),
            "category": self.category,
            "suggested_hashtags": self.suggested_hashtags,
            "social_caption": self.social_caption,
            "caption_hashtags": self.caption_hashtags,
            "pending_review": self.pending_review,
            "review_reason": self.review_reason,
        }

    @staticmethod
    def from_dict(data: dict) -> 'CuratedClipV2':
        return CuratedClipV2(
            start_time=data["start_time"],
            end_time=data["end_time"],
            title=data["title"],
            summary=data["summary"],
            virality_score=ViralityScoreV2.from_dict(data["virality_score"]),
            category=data["category"],
            suggested_hashtags=data.get("suggested_hashtags", []),
            social_caption=data.get("social_caption", ""),
            caption_hashtags=data.get("caption_hashtags", []),
            pending_review=data.get("pending_review", False),
            review_reason=data.get("review_reason", ""),
        )


class MultiAgentCurator:
    """
    Advanced clip curator using 3-agent pipeline:
    1. FINDER: Identifies all potential clip candidates
    2. CRITIC: Evaluates and filters weak candidates
    3. RANKER: Assigns final scores and ranks top clips
    """
    
    def __init__(
        self,
        temperature: float = 0.3,
    ):
        self.temperature = temperature
        
        # Get LLM provider (Claude Sonnet 4.5 → Gemini 3 Flash → Groq fallback)
        self._llm = get_llm()
        
        # Initialize signal analyzers
        self.text_analyzer = TextAnalyzer()
        self.audio_analyzer = AudioAnalyzer()
        self.structural_analyzer = StructuralAnalyzer()
    
    def _format_transcript(self, transcript: Transcript) -> str:
        """Format transcript with timestamps for LLM."""
        lines = []
        for seg in transcript.segments:
            timestamp = f"[{seg.start:.1f}s - {seg.end:.1f}s]"
            speaker = f"[{seg.speaker}]" if seg.speaker else ""
            lines.append(f"{timestamp} {speaker} {seg.text}")
        return "\n".join(lines)
    
    def _extract_signals_summary(self, transcript: Transcript) -> str:
        """Extract and format signals for LLM context."""
        lines = ["### High-Signal Moments Detected:"]
        
        # Text signals
        text_windows = self.text_analyzer.find_high_signal_windows(
            transcript, window_seconds=45, min_score=12
        )
        if text_windows:
            lines.append("\n**Text Signals:**")
            for start, end, sig in text_windows[:10]:
                patterns = ", ".join(sig.detected_patterns[:3]) if sig.detected_patterns else "none"
                lines.append(f"- [{start:.1f}s-{end:.1f}s] hook={sig.hook_score} story={sig.storytelling_score} | {patterns}")
        
        # Audio signals
        audio_windows = self.audio_analyzer.analyze_transcript_segments(transcript, window_seconds=45)
        high_energy = [(s, e, sig) for s, e, sig in audio_windows if sig.pacing_score >= 7]
        if high_energy:
            lines.append("\n**High-Energy Moments:**")
            for start, end, sig in high_energy[:5]:
                lines.append(f"- [{start:.1f}s-{end:.1f}s] WPS={sig.words_per_second:.1f} pacing={sig.pacing_score}")
        
        # Structural signals
        struct_windows = self.structural_analyzer.find_complete_segments(transcript, min_score=20)
        if struct_windows:
            lines.append("\n**Complete Segments:**")
            for start, end, sig in struct_windows[:5]:
                lines.append(f"- [{start:.1f}s-{end:.1f}s] completeness={sig.completeness_score} standalone={sig.standalone_score}")
        
        return "\n".join(lines)
    
    def _apply_performance_bonus(self, clip: 'CuratedClipV2') -> 'CuratedClipV2':
        """
        Apply bonus based on general social media best practices.
        
        
        """
        bonus = 0
        
        # === DURATION BONUS (based on real YouTube data) ===
        if 30 <= clip.duration <= 40:
            bonus += 5  # Optimal: 50-90% retention rate
        elif 40 < clip.duration <= 60:
            bonus += 3  # Good: 30-45% retention
        elif 25 <= clip.duration < 30:
            bonus += 2  # Slightly short but can work
        elif 60 < clip.duration <= 90:
            bonus += 0  # Neutral
        elif clip.duration > 90:
            bonus -= 3  # Penalty: drops to 24% retention
        
        # === CATEGORY BONUS (emotional/story = best retention) ===
        category_lower = clip.category.lower() if clip.category else ""
        if 'emotional' in category_lower:
            bonus += 4  # Best engagement
        elif 'story' in category_lower:
            bonus += 4  # Best engagement
        elif 'insight' in category_lower:
            bonus += 1  # Decent but lower retention
        
        # === TOPIC BONUS (based on top performers) ===
        title_lower = clip.title.lower() if clip.title else ""
        summary_lower = clip.summary.lower() if clip.summary else ""
        combined_text = title_lower + " " + summary_lower
        
        # Career change themes (59% retention - top performer!)
        career_keywords = ["carrera", "equivoqué", "trabajo", "profesión", "cambiar de rumbo"]
        if any(kw in combined_text for kw in career_keywords):
            bonus += 3
        
        # Inner child/nostalgia themes (45% retention)
        nostalgia_keywords = ["niño", "infancia", "cuando era pequeño", "nostalgia", "interior"]
        if any(kw in combined_text for kw in nostalgia_keywords):
            bonus += 2
        
        # Legacy/purpose themes (high engagement)
        legacy_keywords = ["recordar", "legado", "propósito", "sentido de vida"]
        if any(kw in combined_text for kw in legacy_keywords):
            bonus += 2
        
        # === Apply bonus to optimal_duration score (capped at 10) ===
        clip.virality_score.optimal_duration = max(
            0, 
            min(10, clip.virality_score.optimal_duration + bonus)
        )
        
        return clip

    
    def _call_agent(self, system: str, user: str, agent_name: str, max_retries: int = 2) -> str:
        """Call an agent using multi-provider LLM with automatic fallback and retry."""
        for attempt in range(max_retries + 1):
            try:
                return self._llm.chat(
                    system_prompt=system,
                    user_message=user,
                    temperature=self.temperature,
                )
            except Exception as e:
                if attempt < max_retries:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    console.print(f"[yellow]Agent {agent_name} retry {attempt+1}/{max_retries} in {wait_time}s...[/yellow]")
                    time.sleep(wait_time)
                else:
                    console.print(f"[red]Agent {agent_name} FAILED after {max_retries+1} attempts: {e}[/red]")
                    raise RuntimeError(f"Agent {agent_name} failed: {e}")
        
        return "{}"  # Fallback (should not reach here)
    
    def _parse_json(self, text: str) -> dict:
        """Extract JSON from response robustly, preserving newlines in string values."""
        # 1. Try regex for code blocks first
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            # 2. Heuristic: Find first { and last }
            start = text.find("{")
            end = text.rfind("}")
            
            if start != -1 and end != -1:
                json_str = text[start : end + 1]
            else:
                json_str = text.strip()
        
        # 3. Try parsing directly first (preserves \n in strings)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
        
        # 4. Normalize ONLY problematic whitespace outside strings
        # Replace actual newlines between JSON tokens (not inside strings)
        json_str = re.sub(r'(?<!\\)\n\s*', ' ', json_str)
        
        # 5. Remove trailing commas before ] or }
        json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
        
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            console.print(f"[red]Failed to parse JSON:[/red] {str(e)[:80]}")
            return {}
    
    def _sanitize_timestamp(self, value: any, max_duration: float) -> float | None:
        """Sanitize timestamp value. Returns None if invalid."""
        try:
            ts = float(value)
            if ts < 0 or ts > max_duration or not math.isfinite(ts):
                return None
            return ts
        except (ValueError, TypeError):
            return None
    
    def _validate_clip_duration(
        self,
        start_time: float,
        end_time: float,
        min_duration: int,
        max_duration: int,
        clip_title: str = "",
        virality_score: int = 0,
    ) -> str:
        """
        Validate that a clip's duration is within acceptable range.
        
        Args:
            start_time: Clip start timestamp
            end_time: Clip end timestamp
            min_duration: Minimum allowed duration
            max_duration: Maximum allowed duration
            clip_title: Optional title for logging
            virality_score: Total virality score (for edge-case decisions)
            
        Returns:
            'valid' - clip is within range
            'pending' - clip is outside range but may be worth reviewing
            'invalid' - clip should be discarded
        """
        duration = end_time - start_time
        
        # Clips way too short (<50% of min) are always invalid
        if duration < min_duration * 0.5:
            console.print(
                f"[red]✗ Rejecting clip '{clip_title[:30]}' - "
                f"Duration {duration:.1f}s is too short[/red]"
            )
            return 'invalid'
        
        # Clips way too long (> 180s / 3 min) are always invalid
        if duration > 180:
            console.print(
                f"[red]✗ Rejecting clip '{clip_title[:30]}' - "
                f"Duration {duration:.1f}s exceeds 3 min limit[/red]"
            )
            return 'invalid'
        
        # Clips within user-defined valid range
        if min_duration <= duration <= max_duration:
            return 'valid'
        
        # Clips above max but under 180s -> pending review (longer but could be valuable)
        if duration > max_duration:
            console.print(
                f"[cyan]📋 Clip '{clip_title[:30]}' ({duration:.1f}s) - "
                f"Long clip (>{max_duration}s), marked for MANUAL REVIEW[/cyan]"
            )
            return 'pending'
        
        # Short clips with good score -> pending review
        if duration < min_duration and virality_score >= 50:
            console.print(
                f"[cyan]📋 Clip '{clip_title[:30]}' ({duration:.1f}s) - "
                f"Short but high score ({virality_score}pts), marked for MANUAL REVIEW[/cyan]"
            )
            return 'pending'
        
        # Short clips with low score -> discard
        console.print(
            f"[yellow]⚠ Discarding clip '{clip_title[:30]}' - "
            f"Duration {duration:.1f}s and score {virality_score}pts too low for review[/yellow]"
        )
        return 'invalid'
    
    def _deduplicate_clips(
        self,
        clips: list[CuratedClipV2],
        overlap_threshold: float = 0.5,
    ) -> list[CuratedClipV2]:
        """
        Remove duplicate clips that overlap significantly (from chunk overlap).
        When two clips overlap by more than threshold, keep the one with higher score.
        
        Args:
            clips: List of clips (may contain duplicates from overlapping chunks)
            overlap_threshold: Minimum overlap ratio to consider as duplicate (0.5 = 50%)
            
        Returns:
            Deduplicated list of clips
        """
        if len(clips) <= 1:
            return clips
        
        # Sort by start_time
        sorted_clips = sorted(clips, key=lambda c: c.start_time)
        unique_clips = []
        
        for clip in sorted_clips:
            is_duplicate = False
            
            for i, existing in enumerate(unique_clips):
                # Calculate overlap
                overlap_start = max(clip.start_time, existing.start_time)
                overlap_end = min(clip.end_time, existing.end_time)
                overlap_duration = max(0, overlap_end - overlap_start)
                
                # Check if overlap exceeds threshold for either clip
                clip_overlap_ratio = overlap_duration / clip.duration if clip.duration > 0 else 0
                existing_overlap_ratio = overlap_duration / existing.duration if existing.duration > 0 else 0
                
                if clip_overlap_ratio > overlap_threshold or existing_overlap_ratio > overlap_threshold:
                    # Keep the one with higher score
                    if clip.virality_score.total > existing.virality_score.total:
                        unique_clips[i] = clip
                        console.print(f"[dim]   Dedup: Replaced '{existing.title[:20]}' with '{clip.title[:20]}' (higher score)[/dim]")
                    # Mark as duplicate regardless of whether we replaced
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                unique_clips.append(clip)
        
        if len(clips) != len(unique_clips):
            console.print(f"[dim]   Deduplication: {len(clips)} → {len(unique_clips)} clips[/dim]")
        
        return unique_clips
    
    def _generate_captions(
        self,
        clips: list[CuratedClipV2],
        transcript: "Transcript",
        episode_number: int = 0,
        guest_name: str = "",
    ) -> list[CuratedClipV2]:
        """
        Generate social media captions for clips SEQUENTIALLY.
        This runs after ranking, one clip at a time to avoid rate limits.
        
        Args:
            clips: List of curated clips
            transcript: Original transcript for text extraction
            episode_number: Episode number for CTA
            guest_name: Name of the guest (or empty if host solo)
            
        Returns:
            Clips with social_caption populated
        """
        if not clips:
            return clips
        
        console.print(f"\n[dim]   Stage 4: Generating captions for {len(clips)} clips...[/dim]")
        
        for i, clip in enumerate(clips):
            # Get clip text from transcript
            clip_text = ""
            for seg in transcript.segments:
                if seg.end > clip.start_time and seg.start < clip.end_time:
                    clip_text += seg.text + " "
            clip_text = clip_text.strip()[:500]  # Limit text length
            
            # Format prompt
            prompt = CAPTION_GENERATOR_USER.format(
                episode_number=episode_number,
                clip_title=clip.title,
                clip_summary=clip.summary,
                clip_category=clip.category,
                clip_text=clip_text,
            )
            
            # Generate caption (SEQUENTIAL - one at a time)
            response = self._call_agent(
                CAPTION_GENERATOR_SYSTEM,
                prompt,
                f"CAPTION-{i+1}"
            )
            
            # Parse response
            data = self._parse_json(response)
            if data:
                clip.social_caption = data.get("caption", "")
                clip.caption_hashtags = data.get("hashtags", [])
            
            console.print(f"[dim]   Caption {i+1}/{len(clips)} generated[/dim]")
        
        return clips
    
    def _chunk_transcript(
        self,
        transcript: Transcript,
        max_chars: int = 6000,  # ~1500 tokens, safe for 12k limit
        overlap_seconds: int = 120,  # 2 min overlap to avoid losing clips at boundaries
    ) -> list[Transcript]:
        """
        Split transcript into smaller chunks that fit within token limits.
        Each chunk overlaps with the previous one by `overlap_seconds` to ensure
        clips that span chunk boundaries aren't lost.
        
        Args:
            transcript: Full transcript
            max_chars: Max characters per chunk
            overlap_seconds: Seconds of overlap between chunks
            
        Returns:
            List of Transcript objects (chunks)
        """
        chunks = []
        current_segments = []
        current_chars = 0
        overlap_segments = []  # Segments to carry over to next chunk
        
        for seg in transcript.segments:
            seg_text = f"[{seg.start:.1f}s - {seg.end:.1f}s] {seg.text}"
            seg_chars = len(seg_text)
            
            if current_chars + seg_chars > max_chars and current_segments:
                # Create chunk transcript
                chunk_duration = current_segments[-1].end - current_segments[0].start
                chunk = Transcript(
                    segments=current_segments.copy(),
                    language=transcript.language,
                    duration=chunk_duration,
                    source_file=transcript.source_file,
                )
                chunks.append(chunk)
                
                # Find overlap segments (last ~2 min of this chunk)
                overlap_start_time = current_segments[-1].end - overlap_seconds
                overlap_segments = [
                    s for s in current_segments 
                    if s.start >= overlap_start_time
                ]
                
                # Start new chunk with overlap
                current_segments = overlap_segments.copy()
                current_chars = sum(
                    len(f"[{s.start:.1f}s - {s.end:.1f}s] {s.text}") 
                    for s in current_segments
                )
            
            current_segments.append(seg)
            current_chars += seg_chars
        
        # Add final chunk
        if current_segments:
            chunk_duration = current_segments[-1].end - current_segments[0].start
            chunk = Transcript(
                segments=current_segments.copy(),
                language=transcript.language,
                duration=chunk_duration,
                source_file=transcript.source_file,
            )
            chunks.append(chunk)
        
        return chunks
    
    def curate_chunked(
        self,
        transcript: Transcript,
        top_n: int | None = None,
        min_duration: int = 25,
        max_duration: int = 90,
        episode_number: int = 0,
        guest_name: str = "",
        progress_callback: callable = None,
        pause_callback: callable = None,
    ) -> list[CuratedClipV2]:
        """
        Curate a long transcript by processing in chunks.
        
        Args:
            transcript: Full transcript (any length)
            top_n: Number of top clips to display (None = all valid clips)
                   Note: Returns ALL clips that pass validation, not just top_n.
                   Actual filtering by score happens in batch_processor.
            min_duration: Minimum clip duration
            max_duration: Maximum clip duration
            
        Returns:
            List of CuratedClipV2 sorted by score (all valid clips, not limited to top_n)
        """
        # Check if chunking is needed (~6000 chars = ~10 minutes of transcript)
        transcript_text = self._format_transcript(transcript)
        if len(transcript_text) <= 6000:
            return self.curate(transcript, top_n, min_duration, max_duration)
        
        console.print(f"\n[blue]🧠[/blue] Multi-Agent Curation Pipeline (Chunked)")
        console.print(f"[dim]   Provider: {self._llm.providers[0]['name']} | Target: {top_n} clips | {min_duration}-{max_duration}s[/dim]")
        
        # Split into chunks
        chunks = self._chunk_transcript(transcript, max_chars=6000)
        console.print(f"[dim]   Transcript split into {len(chunks)} chunks[/dim]")
        
        if progress_callback:
            progress_callback(0, len(chunks), f"Curation: Initializing {len(chunks)} chunks...")
        
        all_clips = []
        
        for i, chunk in enumerate(chunks):
            # Check for pause
            if pause_callback and pause_callback():
                console.print(f"[yellow]   Curation paused by user at chunk {i+1}/{len(chunks)}[/yellow]")
                return all_clips
                
            console.print(f"\n[dim]   Processing chunk {i+1}/{len(chunks)}...[/dim]")
            if progress_callback:
                progress_callback(i + 1, len(chunks), f"Curation: Chunk {i+1}/{len(chunks)}")
            
            # Extract signals for chunk
            signals_summary = self._extract_signals_summary(chunk)
            transcript_text = self._format_transcript(chunk)
            
            # Run FINDER only on each chunk
            finder_prompt = FINDER_USER_TEMPLATE.format(
                min_duration=min_duration,
                max_duration=max_duration,
                language=transcript.language,
                signals_summary=signals_summary,
                transcript=transcript_text,
            )
            finder_response = self._call_agent(FINDER_SYSTEM, finder_prompt, f"FINDER-{i+1}")
            
            # LOGGING: Data Collection
            curation_logger.log_event("finder_agent", {
                "chunk_index": i,
                "input_prompt": finder_prompt,  # Contains transcript + signals
                "output_response": finder_response
            })
            
            finder_data = self._parse_json(finder_response)
            candidates = finder_data.get("candidates", [])
            
            if not candidates:
                continue
            
            # Run CRITIC on chunk candidates
            critic_prompt = CRITIC_USER_TEMPLATE.format(
                candidates_json=json.dumps(candidates, indent=2),
                transcript=transcript_text,
                min_duration=min_duration,
                max_duration=max_duration,
            )
            critic_response = self._call_agent(CRITIC_SYSTEM, critic_prompt, f"CRITIC-{i+1}")
            
            # LOGGING
            curation_logger.log_event("critic_agent", {
                "chunk_index": i,
                "input_candidates": candidates,
                "output_response": critic_response
            })

            critic_data = self._parse_json(critic_response)
            approved = critic_data.get("approved", [])
            
            if approved:
                # Run RANKER on approved clips from this chunk
                ranker_prompt = RANKER_USER_TEMPLATE.format(
                    approved_json=json.dumps(approved, indent=2),
                    transcript=transcript_text,
                    signals_summary=signals_summary,
                    top_n=len(approved),  # Get ALL approved clips from this chunk
                )
                ranker_response = self._call_agent(RANKER_SYSTEM, ranker_prompt, f"RANKER-{i+1}")
                
                # LOGGING
                curation_logger.log_event("ranker_agent", {
                    "chunk_index": i,
                    "input_prompt": ranker_prompt,
                    "output_response": ranker_response
                })
                
                ranker_data = self._parse_json(ranker_response)
                ranked_clips = ranker_data.get("ranked_clips", [])
                
                # Parse clips from this chunk
                for clip_data in ranked_clips:
                    try:
                        # Sanitize timestamps first
                        start_time = self._sanitize_timestamp(
                            clip_data.get("start_time"), 
                            transcript.duration
                        )
                        end_time = self._sanitize_timestamp(
                            clip_data.get("end_time"), 
                            transcript.duration
                        )
                        
                        if start_time is None or end_time is None or end_time <= start_time:
                            console.print(f"[yellow]Skipping clip with invalid timestamps[/yellow]")
                            continue
                        
                        score_data = clip_data.get("virality_score", {})
                        score = ViralityScoreV2(
                            hook_strength=score_data.get("hook_strength", 0),
                            quotability=score_data.get("quotability", 0),
                            storytelling=score_data.get("storytelling", 0),
                            controversy=score_data.get("controversy", 0),
                            energy_level=score_data.get("energy_level", 0),
                            pacing=score_data.get("pacing", 0),
                            emotional_arc=score_data.get("emotional_arc", 0),
                            standalone_clarity=score_data.get("standalone_clarity", 0),
                            segment_completeness=score_data.get("segment_completeness", 0),
                            optimal_duration=score_data.get("optimal_duration", 0),
                        )
                        
                        clip = CuratedClipV2(
                            start_time=start_time,
                            end_time=end_time,
                            title=clip_data.get("title", "Untitled"),
                            summary=clip_data.get("summary", ""),
                            virality_score=score,
                            category=clip_data.get("category", "insight"),
                            suggested_hashtags=clip_data.get("suggested_hashtags", []),
                        )
                        
                        # Validate duration before adding
                        validation_status = self._validate_clip_duration(
                            clip.start_time,
                            clip.end_time,
                            min_duration,
                            max_duration,
                            clip.title,
                            clip.virality_score.total,
                        )
                        
                        if validation_status == 'invalid':
                            continue
                        elif validation_status == 'pending':
                            clip.pending_review = True
                            clip.review_reason = f"Duration {clip.duration:.1f}s outside {min_duration}-{max_duration}s range"
                        
                        # Apply YouTube performance-based bonus
                        clip = self._apply_performance_bonus(clip)
                        
                        all_clips.append(clip)
                    except (KeyError, ValueError):
                        continue
        
        # Deduplicate clips (remove duplicates from chunk overlap)
        all_clips = self._deduplicate_clips(all_clips)
        
        # Final ranking: sort by score
        all_clips.sort(key=lambda c: c.virality_score.total, reverse=True)
        
        # FIX: If top_n is None or 0, return ALL valid clips
        # Otherwise, limit to top_n but still return all that pass validation
        # The actual filtering by score threshold happens in batch_processor
        if top_n and top_n > 0:
            # Limit to top_n for display, but note that batch_processor will filter by score anyway
            display_clips = all_clips[:top_n]
        else:
            # Return all clips that passed validation
            display_clips = all_clips
        
        # Generate captions (SEQUENTIAL - after all ranking is done)
        if episode_number > 0:
            display_clips = self._generate_captions(display_clips, transcript, episode_number, guest_name)
        
        # Display results
        self._display_results(display_clips)
        
        # Return ALL clips (not just top_n) so batch_processor can filter by score threshold
        # This allows finding all clips that meet criteria, not just a fixed number
        return all_clips
    
    def curate(
        self,
        transcript: Transcript,
        top_n: int | None = None,
        min_duration: int = 25,
        max_duration: int = 90,
        episode_number: int = 0,
        guest_name: str = "",
    ) -> list[CuratedClipV2]:
        """
        Run the full multi-agent curation pipeline.
        
        Args:
            transcript: Transcript to analyze
            top_n: Number of top clips to display (None = all valid clips)
                   Note: Returns ALL clips that pass validation, not just top_n.
                   Actual filtering by score happens in batch_processor.
            min_duration: Minimum clip duration
            max_duration: Maximum clip duration
            
        Returns:
            List of CuratedClipV2 sorted by score (all valid clips, not limited to top_n)
        """
        console.print(f"\n[blue]🧠[/blue] Multi-Agent Curation Pipeline")
        console.print(f"[dim]   Provider: {self._llm.providers[0]['name']} | Target: {top_n} clips | {min_duration}-{max_duration}s[/dim]")
        
        # Extract signals
        console.print(f"[dim]   Extracting signals...[/dim]")
        signals_summary = self._extract_signals_summary(transcript)
        transcript_text = self._format_transcript(transcript)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            # STAGE 1: FINDER
            task = progress.add_task("Stage 1/3: FINDER identifying candidates...", total=None)
            
            finder_prompt = FINDER_USER_TEMPLATE.format(
                min_duration=min_duration,
                max_duration=max_duration,
                language=transcript.language,
                signals_summary=signals_summary,
                transcript=transcript_text,
            )
            finder_response = self._call_agent(FINDER_SYSTEM, finder_prompt, "FINDER")
            finder_data = self._parse_json(finder_response)
            candidates = finder_data.get("candidates", [])
            
            progress.update(task, description=f"Stage 1/3: Found {len(candidates)} candidates")
            
            if not candidates:
                console.print("[yellow]FINDER found no candidates[/yellow]")
                return []
            
            # STAGE 2: CRITIC
            progress.update(task, description="Stage 2/3: CRITIC evaluating...")
            
            critic_prompt = CRITIC_USER_TEMPLATE.format(
                candidates_json=json.dumps(candidates, indent=2),
                transcript=transcript_text,
                min_duration=min_duration,
                max_duration=max_duration,
            )
            critic_response = self._call_agent(CRITIC_SYSTEM, critic_prompt, "CRITIC")
            critic_data = self._parse_json(critic_response)
            approved = critic_data.get("approved", [])
            rejected = critic_data.get("rejected", [])
            
            progress.update(task, description=f"Stage 2/3: Approved {len(approved)}, rejected {len(rejected)}")
            
            if not approved:
                console.print("[yellow]CRITIC rejected all candidates[/yellow]")
                return []
            
            # STAGE 3: RANKER
            progress.update(task, description="Stage 3/3: RANKER scoring...")
            
            ranker_prompt = RANKER_USER_TEMPLATE.format(
                approved_json=json.dumps(approved, indent=2),
                transcript=transcript_text,
                signals_summary=signals_summary,
                top_n=top_n,
            )
            ranker_response = self._call_agent(RANKER_SYSTEM, ranker_prompt, "RANKER")
            ranker_data = self._parse_json(ranker_response)
            ranked_clips = ranker_data.get("ranked_clips", [])
            
            progress.update(task, description=f"Stage 3/3: Ranked {len(ranked_clips)} clips")
        
        # Parse into CuratedClipV2 objects
        # Process ALL ranked clips, not just top_n (filtering happens later)
        clips = []
        for clip_data in ranked_clips:
            try:
                # Sanitize timestamps first
                start_time = self._sanitize_timestamp(
                    clip_data.get("start_time"), 
                    transcript.duration
                )
                end_time = self._sanitize_timestamp(
                    clip_data.get("end_time"), 
                    transcript.duration
                )
                
                if start_time is None or end_time is None or end_time <= start_time:
                    console.print(f"[yellow]Skipping clip with invalid timestamps[/yellow]")
                    continue
                
                score_data = clip_data.get("virality_score", {})
                score = ViralityScoreV2(
                    hook_strength=score_data.get("hook_strength", 0),
                    quotability=score_data.get("quotability", 0),
                    storytelling=score_data.get("storytelling", 0),
                    controversy=score_data.get("controversy", 0),
                    energy_level=score_data.get("energy_level", 0),
                    pacing=score_data.get("pacing", 0),
                    emotional_arc=score_data.get("emotional_arc", 0),
                    standalone_clarity=score_data.get("standalone_clarity", 0),
                    segment_completeness=score_data.get("segment_completeness", 0),
                    optimal_duration=score_data.get("optimal_duration", 0),
                )
                
                clip = CuratedClipV2(
                    start_time=start_time,
                    end_time=end_time,
                    title=clip_data.get("title", "Untitled"),
                    summary=clip_data.get("summary", ""),
                    virality_score=score,
                    category=clip_data.get("category", "insight"),
                    suggested_hashtags=clip_data.get("suggested_hashtags", []),
                )
                
                # Validate duration before adding
                validation_status = self._validate_clip_duration(
                    clip.start_time,
                    clip.end_time,
                    min_duration,
                    max_duration,
                    clip.title,
                    clip.virality_score.total,
                )
                
                if validation_status == 'invalid':
                    continue
                elif validation_status == 'pending':
                    clip.pending_review = True
                    clip.review_reason = f"Duration {clip.duration:.1f}s outside {min_duration}-{max_duration}s range"
                
                # Apply YouTube performance-based bonus
                clip = self._apply_performance_bonus(clip)
                
                clips.append(clip)
            except (KeyError, ValueError) as e:
                console.print(f"[yellow]Skipping malformed clip:[/yellow] {e}")
        
        # Sort by score (best first)
        clips.sort(key=lambda c: c.virality_score.total, reverse=True)
        
        # FIX: If top_n is None or 0, return ALL valid clips
        # Otherwise, limit display to top_n but still return all that pass validation
        if top_n and top_n > 0:
            # Limit display to top_n for readability
            display_clips = clips[:top_n]
        else:
            # Return all clips that passed validation
            display_clips = clips
        
        # Generate captions (SEQUENTIAL - after all ranking is done)
        if episode_number > 0:
            display_clips = self._generate_captions(display_clips, transcript, episode_number, guest_name)
        
        # Display results
        self._display_results(display_clips)
        
        # Return ALL clips (not just top_n) so batch_processor can filter by score threshold
        # This allows finding all clips that meet criteria, not just a fixed number
        return clips
    
    def _display_results(self, clips: list[CuratedClipV2]) -> None:
        """Display results in rich table."""
        if not clips:
            console.print("[yellow]No clips found.[/yellow]")
            return
        
        table = Table(title="🎬 Multi-Agent Curated Clips", show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=3)
        table.add_column("Status", justify="center", width=8)
        table.add_column("Score", justify="center", width=6)
        table.add_column("Duration", justify="center", width=8)
        table.add_column("Title", width=30)
        table.add_column("Time", width=15)
        
        pending_count = 0
        for i, clip in enumerate(clips, 1):
            score = clip.virality_score.total
            score_color = "green" if score >= 70 else "yellow" if score >= 50 else "red"
            
            # Status indicator
            if clip.pending_review:
                status = "[cyan]📋 REVIEW[/cyan]"
                pending_count += 1
            else:
                status = "[green]✓[/green]"
            
            table.add_row(
                str(i),
                status,
                f"[{score_color}]{score}[/{score_color}]",
                f"{clip.duration:.0f}s",
                clip.title[:28] + "..." if len(clip.title) > 30 else clip.title,
                f"{clip.start_time:.1f}s-{clip.end_time:.1f}s",
            )
        
        console.print(table)
        
        if pending_count > 0:
            console.print(f"\n[green]✓[/green] Pipeline complete: {len(clips)} clips ({len(clips) - pending_count} ready, [cyan]{pending_count} pending manual review[/cyan])")
        else:
            console.print(f"\n[green]✓[/green] Pipeline complete: {len(clips)} clips curated")


def curate_transcript_v2(
    transcript: Transcript | str,
    top_n: int = 10,
) -> list[CuratedClipV2]:
    """
    Convenience function for multi-agent curation.
    
    Args:
        transcript: Transcript object or path to JSON
        top_n: Number of clips to extract
        
    Returns:
        List of CuratedClipV2 objects
    """
    from pathlib import Path
    
    if isinstance(transcript, (str, Path)):
        transcript = Transcript.load(Path(transcript))
    
    curator = MultiAgentCurator()
    return curator.curate(transcript, top_n=top_n)
