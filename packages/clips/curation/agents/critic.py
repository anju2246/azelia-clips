import json
from typing import List
from rich.console import Console

from packages.clips.transcription.transcriber import Transcript
from packages.core.llm_provider import get_llm
from packages.clips.curation.prompts import CRITIC_SYSTEM
from packages.clips.curation.prompt_manager import PromptManager
from packages.clips.curation.models import FinderCandidate, CriticResponse, CriticClip

console = Console()

class CriticAgent:
    """
    Critic Agent: Evaluates and filters weak candidates proposed by the Finder.
    Discards clips that lack standalone clarity, resolve poorly, or have little value.
    """
    def __init__(self, temperature: float = 0.3):
        self.temperature = temperature
        self._llm = get_llm()
        self.prompt_manager = PromptManager()

    def _format_transcript(self, transcript: Transcript) -> str:
        lines = []
        for seg in transcript.segments:
            timestamp = f"[{seg.start:.1f}s - {seg.end:.1f}s]"
            speaker = f"[{seg.speaker}]" if seg.speaker else ""
            lines.append(f"{timestamp} {speaker} {seg.text}")
        return "\n".join(lines)

    def evaluate_candidates(
        self, 
        candidates: List[FinderCandidate], 
        transcript: Transcript,
        min_duration: int = 25,
        max_duration: int = 90
    ) -> List[CriticClip]:
        """Critiques the candidates and returns only the approved ones."""
        if not candidates:
            return []
            
        transcript_text = self._format_transcript(transcript)
        
        # Convert candidates to JSON string for the prompt
        candidates_json = json.dumps([c.model_dump() for c in candidates], indent=2)
        
        critic_template = self.prompt_manager.get_critic_prompt()
        critic_prompt = critic_template.format(
            candidates_json=candidates_json,
            transcript=transcript_text,
            min_duration=min_duration,
            max_duration=max_duration,
        )
        
        try:
            response_raw = self._llm.chat(
                system_prompt=CRITIC_SYSTEM,
                user_message=critic_prompt,
                temperature=self.temperature,
                response_format=CriticResponse
            )
            
            if isinstance(response_raw, str):
                import re
                json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response_raw)
                raw_json = json_match.group(1).strip() if json_match else response_raw.strip()
                parsed_dict = json.loads(raw_json)
                response_obj = CriticResponse(**parsed_dict)
            else:
                response_obj = response_raw if isinstance(response_raw, CriticResponse) else CriticResponse(**json.loads(response_raw.model_dump_json()))
                
            return response_obj.approved_only
            
        except Exception as e:
            console.print(f"[red]Failed to run CriticAgent: {e}[/red]")
            # Fallback: if critic fails, approve all candidates to avoid losing data
            return [
                CriticClip(
                    start_time=c.start_time,
                    end_time=c.end_time,
                    title=c.title,
                    summary=c.summary,
                    reasoning="Critic failed, auto-approved",
                    approved=True
                ) for c in candidates
            ]
