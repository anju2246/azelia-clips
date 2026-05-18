import json
from typing import List, Optional
from rich.console import Console

from packages.clips.transcription.transcriber import Transcript
from packages.core.llm_provider import get_llm
from packages.clips.curation.prompts import CRITIC_SYSTEM
from packages.clips.curation.prompt_manager import PromptManager
from packages.clips.curation.models import FinderCandidate, CriticResponse, CriticClip, CurationConfig

# Optional import only used as a default value in the constructor type hint.
# Keeping it here keeps the existing top-level imports intact.

console = Console()

def _format_feedback_memory(max_disagreements: int = 12, max_agreements: int = 6) -> str:
    """Pull user feedback from the JobStore and turn it into a prompt block.

    Strategy:
    - Disagreements are the corrections — the user telling the Critic
      "you were wrong to kill these". Prioritize them (more recent first,
      up to max_disagreements).
    - Agreements act as positive reinforcement — fewer needed.
    - Empty notes are dropped; the textual note IS the signal. A verdict
      without a note is just a click; we don't want to teach from clicks.

    The Critic is told to apply these as soft guidance, not hard rules,
    so it doesn't blindly reverse every decision similar to a single
    user disagreement.
    """
    try:
        from server.workers.job_store import get_job_store
    except Exception:
        return ""  # server module not on the path (e.g. running CLI-only)

    try:
        rows = get_job_store().get_all_critic_feedback()
    except Exception:
        return ""
    if not rows:
        return ""

    disagreements = [
        r for r in rows
        if r.get("user_verdict") == "disagree" and (r.get("user_note") or "").strip()
    ][:max_disagreements]
    agreements = [
        r for r in rows
        if r.get("user_verdict") == "agree" and (r.get("user_note") or "").strip()
    ][:max_agreements]

    if not disagreements and not agreements:
        return ""

    parts: list[str] = [
        "## User Feedback Memory",
        "",
        "The following are examples from PRIOR runs where the user reviewed your",
        "decisions and explained whether you got them right or wrong. Treat them",
        "as soft guidance, not hard rules — apply the same reasoning when you see",
        "similar candidates today, but don't blindly reverse a decision just",
        "because one prior case looked similar.",
    ]

    if disagreements:
        parts.append("")
        parts.append("### Cases where the user DISAGREED with your rejection")
        parts.append("(you were too strict — be more permissive with similar clips)")
        for r in disagreements:
            title = (r.get("title") or "(untitled clip)").strip()
            reasoning = (r.get("critic_reasoning") or "").strip()
            note = (r.get("user_note") or "").strip()
            ep = r.get("episode_id") or ""
            parts.append(
                f"- [{ep}] \"{title}\" — you rejected it saying: \"{reasoning}\". "
                f"User said: \"{note}\""
            )

    if agreements:
        parts.append("")
        parts.append("### Cases where the user AGREED with your rejection")
        parts.append("(you got it right — keep rejecting clips that match this pattern)")
        for r in agreements:
            title = (r.get("title") or "(untitled clip)").strip()
            reasoning = (r.get("critic_reasoning") or "").strip()
            note = (r.get("user_note") or "").strip()
            ep = r.get("episode_id") or ""
            parts.append(
                f"- [{ep}] \"{title}\" — you rejected it saying: \"{reasoning}\". "
                f"User confirmed: \"{note}\""
            )

    return "\n".join(parts)


class CriticAgent:
    """
    Critic Agent: Evaluates and filters weak candidates proposed by the Finder.
    Discards clips that lack standalone clarity, resolve poorly, or have little value.
    """
    def __init__(self, temperature: float = 0.3):
        self.temperature = temperature
        self._llm = get_llm()
        self.prompt_manager = PromptManager()
        # Last full CriticResponse, so the pipeline can persist the rejected
        # candidates alongside the approved ones (the user reviews both in
        # the UI and can give feedback on each rejection).
        self.last_response: Optional[CriticResponse] = None

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
        max_duration: int = 90,
        config: Optional[CurationConfig] = None,
    ) -> List[CriticClip]:
        """Critiques the candidates and returns only the approved ones."""
        if not candidates:
            return []

        config = config or CurationConfig()
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
            from packages.core.taxonomy import language_label as _lang_label
            formatted_system_prompt = CRITIC_SYSTEM.format(
                min_duration=min_duration,
                max_duration=max_duration,
                podcast_context=config.get_podcast_context_block(),
                output_language=_lang_label(config.language),
                user_feedback_memory=_format_feedback_memory(),
            )
            
            response_raw = self._llm.chat(
                system_prompt=formatted_system_prompt,
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

            # Persist the full response so callers can save approved+rejected
            # to disk for UI review and user feedback.
            self.last_response = response_obj

            # Surface rejected clips with reasoning. Otherwise a Critic that
            # eats 16/18 candidates looks like a silent bug — the user has
            # no way to tell whether the Critic was right or just harsh.
            approved = response_obj.approved_only
            rejected = [c for c in response_obj.approved_clips if not c.approved]
            if rejected:
                console.print(
                    f"[yellow]✗ Critic rejected {len(rejected)}/"
                    f"{len(response_obj.approved_clips)} candidates:[/yellow]"
                )
                for i, c in enumerate(rejected, 1):
                    dur = c.end_time - c.start_time
                    title = (c.title or "(no title)")[:60]
                    reason = (c.reasoning or "(no reason)")[:90]
                    console.print(
                        f"  [dim]{i:>2}. [{c.start_time:.0f}-{c.end_time:.0f}s "
                        f"·{dur:.0f}s] {title} — {reason}[/dim]"
                    )
            return approved
            
        except Exception as e:
            console.print(f"[red]Failed to run CriticAgent: {e}[/red]")
            console.print("[yellow]Fallback: all candidates marked as NOT approved — manual review required.[/yellow]")
            return [
                CriticClip(
                    start_time=c.start_time,
                    end_time=c.end_time,
                    title=c.title,
                    summary=c.summary,
                    reasoning="Critic agent failed — manual review required",
                    approved=False
                ) for c in candidates
            ]
