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

# Length controls so the prompt never grows into a book regardless of how
# much feedback the user has logged. The first two limit the example COUNT;
# the third caps any single field's length; the fourth is the hard char
# ceiling on the whole memory block — if we hit it we stop adding examples,
# never silently overflow.
_MAX_DISAGREEMENTS = 8
_MAX_AGREEMENTS = 4
_MAX_FIELD_CHARS = 220
_MAX_MEMORY_CHARS = 2800


def _trunc(text: str | None, max_chars: int = _MAX_FIELD_CHARS) -> str:
    """Truncate noisy fields so one long note can't blow up the prompt."""
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _format_feedback_memory() -> tuple[str, list[int]]:
    """Pull UNCONSUMED user feedback from the JobStore and turn it into a
    prompt block. Returns the prompt block plus the row IDs that were
    actually included so the caller can mark them consumed after a
    successful Critic run.

    Strategy:
    - Only feedback the Critic has NEVER been told about (consumed_at IS
      NULL). Once a row is consumed, it stays out of future prompts —
      lessons aren't re-shown every run.
    - Disagreements are the corrections; agreements are reinforcement.
      We surface both but cap disagreements higher (8) than agreements (4).
    - Empty notes are dropped — a verdict without a note is just a click.
    - Total block is hard-capped at _MAX_MEMORY_CHARS. Hitting the ceiling
      stops adding examples; remaining unconsumed rows wait for the next
      run.
    """
    try:
        from server.workers.job_store import get_job_store
    except Exception:
        return "", []  # server module not on the path (CLI use)

    try:
        rows = get_job_store().get_unconsumed_critic_feedback(limit=24)
    except Exception:
        return "", []
    if not rows:
        return "", []

    # Filter to rows that actually carry signal (verdict + note).
    rows = [
        r for r in rows
        if r.get("user_verdict") in ("agree", "disagree")
        and (r.get("user_note") or "").strip()
    ]
    if not rows:
        return "", []

    disagreements = [r for r in rows if r["user_verdict"] == "disagree"][:_MAX_DISAGREEMENTS]
    agreements = [r for r in rows if r["user_verdict"] == "agree"][:_MAX_AGREEMENTS]

    header = [
        "## User Feedback Memory (new since your last review)",
        "",
        "The user reviewed your prior decisions and gave you targeted feedback",
        "you haven't seen before. Treat each item as soft guidance: apply the",
        "same reasoning when you see similar candidates today, but don't",
        "blindly reverse a decision just because one prior case looked similar.",
    ]
    parts: list[str] = list(header)
    used_ids: list[int] = []
    char_budget = _MAX_MEMORY_CHARS - sum(len(p) + 1 for p in header)

    def _try_add(line: str, row_id: int) -> bool:
        nonlocal char_budget
        cost = len(line) + 1
        if cost > char_budget:
            return False
        parts.append(line)
        used_ids.append(row_id)
        char_budget -= cost
        return True

    stopped_early = False

    if disagreements:
        parts.append("")
        parts.append("### Cases where the user DISAGREED with your rejection")
        parts.append("(you were too strict — be more permissive with similar clips)")
        char_budget -= sum(len(p) + 1 for p in parts[-3:])
        for r in disagreements:
            title = _trunc(r.get("title")) or "(untitled clip)"
            reasoning = _trunc(r.get("critic_reasoning"))
            note = _trunc(r.get("user_note"))
            ep = r.get("episode_id") or ""
            line = (
                f"- [{ep}] \"{title}\" — you rejected it saying: \"{reasoning}\". "
                f"User said: \"{note}\""
            )
            if not _try_add(line, int(r["id"])):
                stopped_early = True
                break

    if agreements and not stopped_early:
        parts.append("")
        parts.append("### Cases where the user AGREED with your rejection")
        parts.append("(you got it right — keep rejecting clips that match this pattern)")
        char_budget -= sum(len(p) + 1 for p in parts[-3:])
        for r in agreements:
            title = _trunc(r.get("title")) or "(untitled clip)"
            reasoning = _trunc(r.get("critic_reasoning"))
            note = _trunc(r.get("user_note"))
            ep = r.get("episode_id") or ""
            line = (
                f"- [{ep}] \"{title}\" — you rejected it saying: \"{reasoning}\". "
                f"User confirmed: \"{note}\""
            )
            if not _try_add(line, int(r["id"])):
                break

    if not used_ids:
        return "", []
    return "\n".join(parts), used_ids


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

            # Pull unconsumed feedback. `feedback_ids` are the rows actually
            # included in the prompt — we mark exactly those as consumed
            # ONLY after the LLM call succeeds. If the call errors out or
            # we hit the fallback path, the feedback stays unconsumed and
            # will be tried again next run.
            feedback_memory, feedback_ids = _format_feedback_memory()
            formatted_system_prompt = CRITIC_SYSTEM.format(
                min_duration=min_duration,
                max_duration=max_duration,
                podcast_context=config.get_podcast_context_block(),
                output_language=_lang_label(config.language),
                user_feedback_memory=feedback_memory,
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

            # Mark the feedback rows we just used as consumed so the next
            # Critic run only sees NEW feedback. Done here (after the LLM
            # call succeeded) so a transient LLM error doesn't burn the
            # user's notes — they stay queued for the next attempt.
            if feedback_ids:
                try:
                    from server.workers.job_store import get_job_store
                    marked = get_job_store().mark_critic_feedback_consumed(feedback_ids)
                    if marked:
                        console.print(
                            f"[dim]   Marked {marked} feedback note(s) as consumed.[/dim]"
                        )
                except Exception as e:
                    console.print(
                        f"[yellow]   Could not mark feedback consumed: {e}[/yellow]"
                    )

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
