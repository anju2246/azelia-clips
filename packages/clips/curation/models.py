from typing import List, Optional
from pydantic import BaseModel, Field, model_validator

# ==========================================
# Configuration Models (Personal Intelligence / IC)
# ==========================================

class CurationConfig(BaseModel):
    """
    Configuration for the curation pipeline.
    This replaces hardcoded rules (like 'Inminente' specific analytics) with a dynamic structure.
    - Community Tier: Powered by 'Personal Intelligence' (auto-learns from user's local SQLite).
    - Pro Tier: Powered by Global Collective Intelligence (retrieved from cloud).
    """
    podcast_name: str = Field(default="Podcast", description="Name of the podcast")
    guest_name: str = Field(default="", description="Name of the guest (if applicable)")
    target_audience: str = Field(default="General", description="Target audience of the content")

    # Podcast identity fields (from profiles table, collected in onboarding).
    # All optional — absent fields mean we fall back to generic viral heuristics.
    # Values are normalized via packages/core/taxonomy.py before reaching this
    # model, so interpolation into PostgREST filters downstream is safe.
    content_niche: str = Field(default="", description="User's niche id (e.g., business, comedy, health_fitness).")
    user_role: str = Field(default="", description="Role: host, producer, solo creator, etc.")
    primary_goal: str = Field(default="", description="Primary goal: audience_growth, revenue, community, etc.")
    region: str = Field(default="", description="ISO 3166-1 alpha-2 country code.")
    episode_format: str = Field(default="", description="Episode format: solo, interview, panel, narrative.")
    language: str = Field(default="", description="ISO 639-1 language code of the podcast content.")
    is_pro_tier: bool = Field(default=False, description="True if user has an active Pro subscription. Gates podintel_public signals.")
    user_cohort_hash: str = Field(default="", description="One-way hash of user id — keys creator_self signals.")

    # Intelligence Driven Parameters
    high_retention_patterns: List[str] = Field(
        default_factory=list,
        description="List of hook patterns proven to work well for this specific podcast/brand."
    )
    preferred_clip_formats: List[str] = Field(
         default_factory=list,
         description="Formats the audience prefers (e.g., 'Controversial debates', 'Personal vulnerability')."
    )
    brand_voice: str = Field(default="Casual, authentic and engaging", description="The brand's voice and tone.")

    def has_podcast_identity(self) -> bool:
        return any([self.content_niche, self.primary_goal, self.episode_format])

    def get_podcast_context_block(self) -> str:
        """Return the podcast-identity block injected into agent prompts.

        One single English version — the prompt itself is English, and the
        top-of-prompt `Respond in {output_language}` instruction makes the
        LLM translate the podcast-context reasoning to the user's language
        in its output. Keeping this in English avoids mixing languages
        inside the system prompt, which was confusing Claude on non-Spanish
        podcasts in the previous implementation.
        Returns empty string when no identity fields are set.
        """
        if not self.has_podcast_identity():
            return ""

        parts = []
        if self.content_niche:
            parts.append(f"niche: {self.content_niche}")
        if self.episode_format:
            parts.append(f"episode format: {self.episode_format}")
        if self.region:
            parts.append(f"region: {self.region}")
        if self.primary_goal:
            parts.append(f"primary goal: {self.primary_goal}")

        header = "## Podcast context\n"
        body = "This podcast is about " + ", ".join(parts) + "."
        guidance = (
            "\nPrioritize clips that fit this podcast's topic identity. "
            "Deprioritize generic viral moments (jokes, tangents, off-topic stories) "
            "that would not serve an audience coming for this niche. "
            "A clip that is 'viral' but off-topic for this podcast should be rejected."
        )
        return header + body + guidance

    def get_intelligence_prompt_addendum(self) -> str:
        """Returns a formatted string of the intelligence rules to append to system prompts."""
        lines = []

        podcast_ctx = self.get_podcast_context_block()
        if podcast_ctx:
            lines.append(podcast_ctx)
            lines.append("")

        if self.high_retention_patterns:
            lines.append("## Proven High-Retention Patterns:")
            lines.append("Based on historical data, these patterns work best for this content:")
            for p in self.high_retention_patterns:
                lines.append(f"- {p}")

        if self.preferred_clip_formats:
            lines.append("\n## Preferred Audience Formats:")
            for f in self.preferred_clip_formats:
                lines.append(f"- {f}")

        return "\n".join(lines)

class ViralityScore(BaseModel):
    """Enhanced virality scoring with 10 dimensions."""
    # Text-based (40 pts max)
    hook_strength: int = Field(default=0, ge=0, le=10, description="Strength of the hook (0-10)")
    quotability: int = Field(default=0, ge=0, le=10, description="How quotable the clip is (0-10)")
    storytelling: int = Field(default=0, ge=0, le=10, description="Narrative arc and structure (0-10)")
    controversy: int = Field(default=0, ge=0, le=10, description="Discussion-provoking potential (0-10)")
    
    # Audio-based (30 pts max)
    energy_level: int = Field(default=0, ge=0, le=10, description="Speaker energy and passion (0-10)")
    pacing: int = Field(default=0, ge=0, le=10, description="Rhythm, pauses, and flow (0-10)")
    emotional_arc: int = Field(default=0, ge=0, le=10, description="Emotional depth and variation (0-10)")
    
    # Structural (30 pts max)
    standalone_clarity: int = Field(default=0, ge=0, le=10, description="Ability to be understood without context (0-10)")
    segment_completeness: int = Field(default=0, ge=0, le=10, description="Resolves its own premise (0-10)")
    optimal_duration: int = Field(default=0, ge=0, le=10, description="Has the ideal length for its content (0-10)")

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


class CuratedClip(BaseModel):
    """A curated clip with enhanced metadata."""
    start_time: float = Field(..., description="Start time in seconds")
    end_time: float = Field(..., description="End time in seconds")
    title: str = Field(..., description="Catchy title for the clip")
    hook_text: str = Field(default="", description="On-screen hook text for the first N seconds; empty falls back to title at render")
    summary: str = Field(..., description="Brief summary of the clip content")
    virality_score: ViralityScore = Field(default_factory=ViralityScore, description="Detailed virality score dimensions")
    category: str = Field(default="insight", description="e.g., insight, story, funny, controversial")
    suggested_hashtags: List[str] = Field(default_factory=list, description="List of hashtags")
    social_caption: str = Field(default="", description="Generated social media caption")
    caption_hashtags: List[str] = Field(default_factory=list, description="Hashtags specific to the generated caption")
    pending_review: bool = Field(default=False, description="True if clip needs manual approval")
    review_reason: str = Field(default="", description="Reason for pending review")

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

# ==========================================
# LLM Validation Models
# ==========================================

class FinderCandidate(BaseModel):
    """Single candidate clip proposed by the Finder agent."""
    start_time: float = Field(..., description="Start timestamp of the clip in seconds")
    end_time: float = Field(..., description="End timestamp of the clip in seconds")
    title: Optional[str] = Field(default=None, description="Catchy working title for the clip")
    summary: Optional[str] = Field(default=None, description="Brief one-sentence summary of what the clip is about")
    reasoning: Optional[str] = Field(default=None, description="Why this makes a good clip")

    # Support older LLM responses that use 'reason' instead of 'reasoning'
    @model_validator(mode='before')
    @classmethod
    def coerce_legacy_fields(cls, data):
        if isinstance(data, dict):
            # Map 'reason' -> 'reasoning' if reasoning is missing
            if not data.get('reasoning') and data.get('reason'):
                data['reasoning'] = data.pop('reason')
            # Auto-generate title from reasoning if missing
            if not data.get('title'):
                reason = data.get('reasoning') or data.get('reason', '')
                data['title'] = (reason[:60].strip() + '...') if len(reason) > 60 else reason
            # Auto-generate summary from reasoning if missing
            if not data.get('summary'):
                data['summary'] = data.get('reasoning', '')
        return data

class FinderResponse(BaseModel):
    """Structured response expected from the Finder agent."""
    candidates: List[FinderCandidate] = Field(..., description="List of proposed clip candidates")

class CriticClip(BaseModel):
    """Critic's assessment of a candidate clip."""
    start_time: float = Field(..., description="Start timestamp")
    end_time: float = Field(..., description="End timestamp")
    title: Optional[str] = Field(default=None, description="Catchy title")
    summary: Optional[str] = Field(default=None, description="Brief summary")
    reasoning: Optional[str] = Field(default=None, description="Why it was approved or rejected")
    approved: bool = Field(..., description="True if the clip is good enough to proceed")

    @model_validator(mode='before')
    @classmethod
    def coerce_legacy_fields(cls, data):
        if isinstance(data, dict):
            # Map approval_reason / rejection_reason -> reasoning
            if not data.get('reasoning'):
                data['reasoning'] = data.get('approval_reason') or data.get('rejection_reason', '')
            # Infer approved from which key is present if missing
            if 'approved' not in data:
                data['approved'] = bool(data.get('approval_reason'))
            # Auto-fill title/summary if missing
            if not data.get('title'):
                r = data.get('reasoning', '')
                data['title'] = (r[:60].strip() + '...') if len(r) > 60 else r
            if not data.get('summary'):
                data['summary'] = data.get('reasoning', '')
        return data

class CriticResponse(BaseModel):
    """Structured response expected from the Critic agent."""
    approved_clips: List[CriticClip] = Field(default_factory=list)

    @model_validator(mode='before')
    @classmethod
    def coerce_legacy_format(cls, data):
        """Map old {approved:[...], rejected:[...]} -> {approved_clips:[...]}"""
        if isinstance(data, dict) and 'approved_clips' not in data:
            approved = data.get('approved', [])
            rejected = data.get('rejected', [])
            if approved or rejected:
                clips = []
                for c in approved:
                    c['approved'] = True
                    clips.append(c)
                for c in rejected:
                    c['approved'] = False
                    clips.append(c)
                data['approved_clips'] = clips
        return data

    @property
    def approved_only(self) -> List[CriticClip]:
        return [c for c in self.approved_clips if c.approved]

class RankerResponse(BaseModel):
    """Structured response expected from the Ranker agent."""
    ranked_clips: List[CuratedClip] = Field(..., description="List of ranked clips with full virality scoring")

class CaptionResponse(BaseModel):
    """Structured response expected from the Caption Generator agent."""
    caption: str = Field(..., description="The viral social media caption")
    hashtags: List[str] = Field(..., description="3-5 highly relevant hashtags without the # symbol")
