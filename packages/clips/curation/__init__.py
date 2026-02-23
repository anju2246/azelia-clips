"""Curation module for AI-powered clip selection.

Uses MultiAgentCurator (v2) as the primary curator.
Includes TeaserIntroGenerator for adelantos and intro scripts.
"""

from packages.clips.curation.pipeline import CurationPipeline
from packages.clips.curation.models import CuratedClip, ViralityScore
from packages.clips.curation.clip_extractor import ClipExtractor
from packages.clips.curation.teaser_generator import TeaserIntroGenerator, TeaserClip, IntroScript

# Primary exports
__all__ = [
    "CurationPipeline",
    "CuratedClip",
    "ViralityScore",
    "ClipExtractor",
    "TeaserIntroGenerator",
    "TeaserClip",
    "IntroScript",
    # Backwards compatibility alias
    "ClipCurator",
]

# Backwards compatibility: ClipCurator is now CurationPipeline
ClipCurator = CurationPipeline
