"""
Prompt Manager for loading custom prompt overrides from the file system.

Allows users to place .txt files in `PODCAST_DIR/prompts/` to override 
the default system prompts defined in `src.curation.prompts`.
"""

import logging
from pathlib import Path
from typing import Optional

from src.config import settings
from src.curation import prompts as default_prompts

logger = logging.getLogger(__name__)

class PromptManager:
    """Manages loading of custom prompts."""
    
    def __init__(self, podcast_dir: Optional[Path] = None):
        self.podcast_dir = podcast_dir or settings.podcast_dir
        self.prompts_dir = self.podcast_dir / "prompts"
        
    def _load_override(self, filename: str) -> Optional[str]:
        """Try to load a prompt override from disk."""
        if not self.prompts_dir.exists():
            return None
            
        file_path = self.prompts_dir / filename
        if file_path.exists():
            try:
                content = file_path.read_text(encoding="utf-8").strip()
                if content:
                    logger.info(f"Loaded custom prompt from {file_path}")
                    return content
            except Exception as e:
                logger.error(f"Failed to read custom prompt {file_path}: {e}")
        
        return None

    def get_finder_prompt(self) -> str:
        """Get Finder Agent prompt."""
        override = self._load_override("finder_prompt.txt")
        return override or default_prompts.FINDER_USER_TEMPLATE

    def get_critic_prompt(self) -> str:
        """Get Critic Agent prompt."""
        override = self._load_override("critic_prompt.txt")
        return override or default_prompts.CRITIC_USER_TEMPLATE

    def get_ranker_prompt(self) -> str:
        """Get Ranker Agent prompt."""
        override = self._load_override("ranker_prompt.txt")
        return override or default_prompts.RANKER_USER_TEMPLATE

    def get_caption_prompt(self) -> str:
        """Get Caption Generator prompt."""
        override = self._load_override("caption_prompt.txt")
        return override or default_prompts.CAPTION_GENERATOR_USER
