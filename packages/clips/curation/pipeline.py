import json
from typing import List
from rich.console import Console

from packages.clips.transcription.transcriber import Transcript
from packages.clips.curation.models import CuratedClip
from packages.clips.curation.agents.finder import FinderAgent
from packages.clips.curation.agents.critic import CriticAgent
from packages.clips.curation.agents.ranker import RankerAgent

console = Console()

class CurationPipeline:
    """
    Orchestrates the 3-agent curation pipeline:
    1. Finder: Map-Reduce candidate generation.
    2. Critic: Filtering weak candidates.
    3. Ranker: Final scoring and caption generation.
    """
    def __init__(self, temperature: float = 0.3):
        self.finder = FinderAgent(temperature)
        self.critic = CriticAgent(temperature)
        self.ranker = RankerAgent(temperature)
        
    def _validate_clip_duration(
        self,
        clip: CuratedClip,
        min_duration: int,
        max_duration: int
    ) -> str:
        """Validates duration limits and sets pending review status if needed."""
        duration = clip.duration
        
        # Too short (< 50% min) or too long (> 3 min) are dead invalid
        if duration < min_duration * 0.5:
            return 'invalid'
        if duration > 180:
            return 'invalid'
            
        # Perfect
        if min_duration <= duration <= max_duration:
            return 'valid'
            
        # Over max but under 180s = Review
        if duration > max_duration:
            clip.pending_review = True
            clip.review_reason = f"Duration {duration:.1f}s > {max_duration}s."
            return 'pending'
            
        # Too short but high score = Review
        if duration < min_duration and clip.virality_score.total >= 50:
            clip.pending_review = True
            clip.review_reason = f"Duration {duration:.1f}s < {min_duration}s but high score."
            return 'pending'
            
        return 'invalid'

    def _apply_performance_bonus(self, clip: CuratedClip) -> CuratedClip:
        """Applies Inminente YouTube analytics performance heuristics."""
        bonus = 0
        
        # DURATION BONUS
        if 30 <= clip.duration <= 40: bonus += 5
        elif 40 < clip.duration <= 60: bonus += 3
        elif 25 <= clip.duration < 30: bonus += 2
        elif clip.duration > 90: bonus -= 3
        
        # CATEGORY BONUS
        cat = clip.category.lower()
        if 'emotional' in cat or 'story' in cat: bonus += 4
        elif 'insight' in cat: bonus += 1
        
        # TOPIC BONUS
        combined_text = (clip.title + " " + clip.summary).lower()
        if any(kw in combined_text for kw in ["carrera", "equivoqué", "trabajo", "profesión", "cambiar de rumbo"]):
            bonus += 3
        if any(kw in combined_text for kw in ["niño", "infancia", "cuando era pequeño", "nostalgia", "interior"]):
            bonus += 2
        if any(kw in combined_text for kw in ["recordar", "legado", "propósito", "sentido de vida"]):
            bonus += 2
            
        # Apply bonus safely
        clip.virality_score.optimal_duration = max(0, min(10, clip.virality_score.optimal_duration + bonus))
        return clip

    def curate(
        self,
        transcript: Transcript,
        top_n: int = None,
        min_duration: int = 25,
        max_duration: int = 90,
        episode_number: int = 0,
        guest_name: str = "",
        podcast_name: str = "Podcast",
        progress_callback=None,
        pause_callback=None
    ) -> List[CuratedClip]:
        
        console.print(f"\n[blue]🧠[/blue] Multi-Agent Pipeline (Phase 2 Architecture)")
        
        # 1. FINDER
        candidates = self.finder.find_candidates(
            transcript, min_duration, max_duration, progress_callback, pause_callback
        )
        if not candidates:
            console.print("[yellow]Phase 1 (Finder) found no candidates.[/yellow]")
            return []
            
        console.print(f"[green]✓ Finder proposed {len(candidates)} candidates.[/green]")

        # 2. CRITIC
        approved_critics = self.critic.evaluate_candidates(
            candidates, transcript, min_duration, max_duration
        )
        if not approved_critics:
            console.print("[yellow]Phase 2 (Critic) rejected all candidates.[/yellow]")
            return []
            
        console.print(f"[green]✓ Critic approved {len(approved_critics)} candidates.[/green]")

        # 3. RANKER
        # Need top_n logic inside ranker, or we ask ranker to score all approved clips and we sort them
        ranked_clips = self.ranker.rank_clips(approved_critics, transcript, top_n=len(approved_critics))
        
        # Post-Processing
        final_clips = []
        for clip in ranked_clips:
            # Re-sanitize timestamps and duration validation
            if clip.end_time <= clip.start_time:
                continue
                
            val_status = self._validate_clip_duration(clip, min_duration, max_duration)
            if val_status == 'invalid':
                continue
                
            clip = self._apply_performance_bonus(clip)
            final_clips.append(clip)
            
        # Sort by total score
        final_clips.sort(key=lambda c: c.virality_score.total, reverse=True)
        
        # Keep all valid clips or slice top_n
        if top_n and top_n > 0:
            final_clips = final_clips[:top_n]
            
        # Cap captions to only the exported/top ones to save tokens
        if episode_number > 0 and final_clips:
            final_clips = self.ranker.generate_captions(
                final_clips, transcript, episode_number, guest_name, podcast_name
            )
            
        return final_clips
