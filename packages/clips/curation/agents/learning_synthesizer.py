"""Distil user feedback into a compact, persistent set of Critic learnings.

The Critic has two memory layers:
1. **Short-term** — unconsumed feedback rows, fed verbatim to the prompt
   exactly once each (handled in critic.py).
2. **Long-term** — this module's output: a small set of durable rules
   stored in `critic_learnings`. Always injected on every Critic run.

Without this synthesis step, "learning" would only persist for the
single run that consumed each note — LLMs are stateless. With it, the
Critic accumulates durable guidance over time WITHOUT the prompt
growing forever: the LLM is told to keep the list under MAX_LEARNINGS
and to merge or drop rules as new evidence comes in.

Triggered by `critic.py` immediately after a successful Critic call
that consumed any feedback. Each run = ONE extra LLM call, which is
acceptable in exchange for a Critic that genuinely improves over time.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from packages.core.llm_provider import get_llm

logger = logging.getLogger(__name__)

# Bounded forever, no matter how many notes the user logs. The synthesizer
# is INSTRUCTED to respect these; we also enforce them defensively after
# parsing the LLM's output.
MAX_LEARNINGS = 12
MAX_LEARNING_CHARS = 220


SYNTHESIZER_SYSTEM = """You are the LEARNING SYNTHESIZER for a podcast clip curation system.

Your job: maintain a SHORT, durable list of rules that the Critic agent will
use to judge clip candidates. You receive two inputs each call:

1. **Current learnings** — the rules already in place (may be empty on first run).
2. **New user feedback** — notes the user just wrote about clips the Critic
   recently rejected. Each note says either "the Critic was wrong" (disagree)
   or "the Critic was right" (agree), plus the user's explanation.

Produce an UPDATED list of learnings:

- **Merge** new feedback into existing rules when the pattern matches —
  increment evidence_count, optionally tighten the wording.
- **Add** a new rule when feedback represents a genuinely new pattern.
- **Drop or revise** rules that the new feedback contradicts.
- Each rule is 1–2 sentences MAX, actionable, GENERIC (not "EP021 clip about
  business" — instead "When a clip self-contains an emotional arc, treat
  context references as ornamental rather than disqualifying").
- **Hard cap: """ + str(MAX_LEARNINGS) + """ rules total.** If you have more candidates than that,
  keep the ones with the strongest cumulative evidence_count.
- **Each rule ≤ """ + str(MAX_LEARNING_CHARS) + """ chars.**

Output strict JSON with this exact shape:

```json
{
  "learnings": [
    {
      "text": "When a clip references prior context but contains a complete arc, treat the arc as sufficient.",
      "category": "context_handling",
      "evidence_count": 3
    }
  ]
}
```

Valid categories (use one of these, or invent a new short snake_case one):
context_handling, duration_strictness, hook_quality, meta_references,
emotional_arc, off_topic, audio_quality, style_preference, other.

Respond in the SAME LANGUAGE the user wrote their notes in."""


def _build_user_message(
    current_learnings: list[dict],
    feedback_rows: list[dict],
) -> str:
    """Compose the input the synthesizer reasons over."""
    parts: list[str] = []

    if current_learnings:
        parts.append("# Current learnings")
        for L in current_learnings:
            cat = L.get("category") or "uncategorized"
            ev = L.get("evidence_count") or 1
            txt = L.get("text") or ""
            parts.append(f"- [{cat} · evidence={ev}] {txt}")
    else:
        parts.append("# Current learnings\n(none — this is the first synthesis)")

    parts.append("")
    parts.append("# New user feedback (just consumed)")
    for r in feedback_rows:
        verdict = r.get("user_verdict")
        title = (r.get("title") or "(untitled)").strip()
        reasoning = (r.get("critic_reasoning") or "").strip()
        note = (r.get("user_note") or "").strip()
        parts.append(
            f"- verdict={verdict} · clip=\"{title}\" · Critic said: \"{reasoning}\" · "
            f"User wrote: \"{note}\""
        )

    parts.append("")
    parts.append(
        "Return the UPDATED learnings list as strict JSON. Stay under the "
        f"{MAX_LEARNINGS}-rule cap; merge or drop aggressively if needed."
    )
    return "\n".join(parts)


def _parse_response(raw: str | object) -> list[dict]:
    """Extract `learnings` list from the LLM response, robust to fenced JSON."""
    text = raw if isinstance(raw, str) else getattr(raw, "model_dump_json", lambda: str(raw))()
    if not isinstance(text, str):
        return []
    import re
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    body = m.group(1).strip() if m else text.strip()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("LearningSynthesizer: could not parse JSON response")
        return []
    learnings = data.get("learnings") if isinstance(data, dict) else None
    if not isinstance(learnings, list):
        return []
    out: list[dict] = []
    for L in learnings:
        if not isinstance(L, dict):
            continue
        text = (L.get("text") or "").strip()
        if not text:
            continue
        if len(text) > MAX_LEARNING_CHARS:
            text = text[: MAX_LEARNING_CHARS - 1].rstrip() + "…"
        out.append(
            {
                "text": text,
                "category": (L.get("category") or "other").strip() or "other",
                "evidence_count": max(1, int(L.get("evidence_count") or 1)),
            }
        )
    return out[:MAX_LEARNINGS]


def synthesize(feedback_rows: list[dict]) -> Optional[list[dict]]:
    """Run one synthesis pass. Returns the new learnings list, or None on
    failure. Caller decides whether to persist (we never write to the DB
    from this module — keeps it testable).
    """
    if not feedback_rows:
        return None

    try:
        from server.workers.job_store import get_job_store
        current = get_job_store().get_critic_learnings()
    except Exception:
        current = []

    user_msg = _build_user_message(current, feedback_rows)

    try:
        llm = get_llm()
        response = llm.chat(
            system_prompt=SYNTHESIZER_SYSTEM,
            user_message=user_msg,
            temperature=0.2,
        )
    except Exception as e:
        logger.warning("LearningSynthesizer LLM call failed: %s", e)
        return None

    return _parse_response(response)
