"""Curation module for AI-powered clip selection.

Uses MultiAgentCurator (v2) as the primary curator.
Includes TeaserIntroGenerator for adelantos and intro scripts.
"""

from src.curation.curator_v2 import MultiAgentCurator, CuratedClipV2, ViralityScoreV2
from src.curation.clip_extractor import ClipExtractor
from src.curation.teaser_generator import TeaserIntroGenerator, TeaserClip, IntroScript

# Primary exports
__all__ = [
    "MultiAgentCurator",
    "CuratedClipV2",
    "ViralityScoreV2",
    "ClipExtractor",
    "TeaserIntroGenerator",
    "TeaserClip",
    "IntroScript",
    # Backwards compatibility alias
    "ClipCurator",
]

# Backwards compatibility: ClipCurator is now MultiAgentCurator
ClipCurator = MultiAgentCurator
