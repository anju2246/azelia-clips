"""Teaser and Intro Script Generator for podcast episodes.

Generates:
1. Adelantos (teasers): Short clips (15-30s) to build anticipation
2. Intro Script: AI-generated text for host to read

Usage:
    from src.curation.teaser_generator import TeaserIntroGenerator
    
    generator = TeaserIntroGenerator()
    result = generator.generate(transcript, episode_id, guest_name)
    
    # Access results
    teasers = result["teasers"]
    intro_script = result["intro_script"]
"""

import json
from dataclasses import dataclass
from typing import Optional

from rich.console import Console

from src.asr.transcriber import Transcript
from src.llm_provider import get_llm
from src.curation.teaser_intro import (
    TEASER_FINDER_SYSTEM,
    TEASER_FINDER_USER,
    INTRO_SCRIPT_SYSTEM,
    INTRO_SCRIPT_USER,
    format_transcript_for_teaser,
    summarize_transcript_for_intro,
    extract_topics_from_transcript,
)

console = Console()


@dataclass
class TeaserClip:
    """A teaser/adelanto clip."""
    start_time: float
    end_time: float
    hook: str
    reason: str
    intrigue_level: int = 8
    
    @property
    def duration(self) -> float:
        return self.end_time - self.start_time
    
    def to_dict(self) -> dict:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "hook": self.hook,
            "reason": self.reason,
            "intrigue_level": self.intrigue_level,
        }


@dataclass
class IntroScript:
    """Generated intro script for the host."""
    text: str
    estimated_duration: int
    key_topics: list[str]
    guest_highlights: list[str]
    
    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "estimated_duration_seconds": self.estimated_duration,
            "key_topics": self.key_topics,
            "guest_highlights": self.guest_highlights,
        }


class TeaserIntroGenerator:
    """Generate teasers and intro scripts for podcast episodes."""
    
    def __init__(
        self,
        teaser_min_duration: int = 15,
        teaser_max_duration: int = 30,
        temperature: float = 0.4,
    ):
        self.teaser_min_duration = teaser_min_duration
        self.teaser_max_duration = teaser_max_duration
        self.temperature = temperature
    
    def generate(
        self,
        transcript: Transcript,
        episode_id: str = "",
        guest_name: str = "",
        episode_title: str = "",
        generate_teasers: bool = True,
        generate_intro: bool = True,
    ) -> dict:
        """
        Generate teasers and/or intro script.
        
        Args:
            transcript: Full episode transcript
            episode_id: Episode ID (e.g., "EP001")
            guest_name: Name of the guest
            episode_title: Suggested episode title
            generate_teasers: Whether to generate teasers
            generate_intro: Whether to generate intro script
        
        Returns:
            Dict with "teasers" and/or "intro_script"
        """
        result = {}
        
        if generate_teasers:
            console.print("\n[cyan]🎯 Generating teasers (adelantos)...[/cyan]")
            teasers = self._generate_teasers(transcript)
            result["teasers"] = [t.to_dict() for t in teasers]
            console.print(f"[green]✓[/green] Generated {len(teasers)} teasers")
        
        if generate_intro:
            console.print("\n[cyan]📝 Generating intro script...[/cyan]")
            intro = self._generate_intro_script(
                transcript, episode_id, guest_name, episode_title
            )
            result["intro_script"] = intro.to_dict()
            console.print(f"[green]✓[/green] Intro script ready ({intro.estimated_duration}s)")
        
        return result
    
    def _generate_teasers(self, transcript: Transcript) -> list[TeaserClip]:
        """Generate teaser clips using LLM."""
        # Format transcript for teaser identification
        formatted = format_transcript_for_teaser(transcript)
        
        # Build prompt
        system = TEASER_FINDER_SYSTEM.format(
            min_duration=self.teaser_min_duration,
            max_duration=self.teaser_max_duration,
        )
        user = TEASER_FINDER_USER.format(
            min_duration=self.teaser_min_duration,
            max_duration=self.teaser_max_duration,
            transcript=formatted,
        )
        
        # Call LLM
        llm = get_llm()
        response = llm.chat(system, user, temperature=self.temperature)
        
        # Parse response
        teasers = self._parse_teaser_response(response, transcript.duration)
        
        return teasers
    
    def _generate_intro_script(
        self,
        transcript: Transcript,
        episode_id: str,
        guest_name: str,
        episode_title: str,
    ) -> IntroScript:
        """Generate intro script using LLM."""
        # Summarize transcript
        summary = summarize_transcript_for_intro(transcript)
        topics = extract_topics_from_transcript(transcript)
        
        # Build prompt
        system = INTRO_SCRIPT_SYSTEM
        user = INTRO_SCRIPT_USER.format(
            episode_id=episode_id,
            guest_name=guest_name or "Invitado",
            episode_title=episode_title or f"Episodio {episode_id}",
            transcript_summary=summary,
            main_topics="\n".join(f"- {t}" for t in topics),
        )
        
        # Call LLM
        llm = get_llm()
        response = llm.chat(system, user, temperature=self.temperature)
        
        # Parse response
        intro = self._parse_intro_response(response)
        
        return intro
    
    def _parse_teaser_response(self, response: str, max_duration: float) -> list[TeaserClip]:
        """Parse LLM response for teasers."""
        teasers = []
        
        try:
            # Extract JSON from response
            data = self._extract_json(response)
            
            for item in data.get("teasers", []):
                start = item.get("start_time", 0)
                end = item.get("end_time", 0)
                
                # Validate timestamps
                if start >= end or start < 0 or end > max_duration:
                    continue
                
                # Validate duration
                duration = end - start
                if duration < self.teaser_min_duration or duration > self.teaser_max_duration:
                    continue
                
                teasers.append(TeaserClip(
                    start_time=start,
                    end_time=end,
                    hook=item.get("hook", ""),
                    reason=item.get("why", item.get("reason", "")),
                    intrigue_level=item.get("intrigue_level", 8),
                ))
        
        except Exception as e:
            console.print(f"[yellow]⚠️ Error parsing teasers: {e}[/yellow]")
        
        return teasers
    
    def _parse_intro_response(self, response: str) -> IntroScript:
        """Parse LLM response for intro script."""
        try:
            data = self._extract_json(response)
            
            return IntroScript(
                text=data.get("intro_script", ""),
                estimated_duration=data.get("estimated_duration_seconds", 35),
                key_topics=data.get("key_topics", []),
                guest_highlights=data.get("guest_highlights", []),
            )
        
        except Exception as e:
            console.print(f"[yellow]⚠️ Error parsing intro: {e}[/yellow]")
            return IntroScript(
                text="Error generando guión",
                estimated_duration=0,
                key_topics=[],
                guest_highlights=[],
            )
    
    def _extract_json(self, text: str) -> dict:
        """Extract JSON from LLM response."""
        import re
        
        # Try to find JSON between ```json and ```
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if json_match:
            return json.loads(json_match.group(1))
        
        # Try to find JSON between { and }
        brace_match = re.search(r'\{[\s\S]*\}', text)
        if brace_match:
            return json.loads(brace_match.group(0))
        
        # Last resort: try parsing the whole thing
        return json.loads(text)


def generate_teasers_and_intro(
    transcript: Transcript,
    episode_id: str = "",
    guest_name: str = "",
    episode_title: str = "",
) -> dict:
    """Convenience function to generate both teasers and intro script."""
    generator = TeaserIntroGenerator()
    return generator.generate(
        transcript=transcript,
        episode_id=episode_id,
        guest_name=guest_name,
        episode_title=episode_title,
    )
