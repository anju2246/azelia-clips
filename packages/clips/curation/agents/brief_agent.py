"""
Conversational brief agent (T3).

Turns a natural-language feedback message into a list of structured BriefActions.
This is the ONLY place in the brief feature that talks to an LLM — everything
downstream (the applier) is deterministic, so the rest stays testable.
"""
import json
import re
from typing import List, Optional

from packages.core.llm_provider import get_llm
from packages.clips.curation.brief_models import (
    ACTION_TYPES,
    BriefAction,
    BriefCandidate,
    ChatMessage,
)

_SYSTEM_PROMPT = """Eres el asistente del "brief" de Azelia. El usuario revisa los clips
candidatos de un podcast ANTES de renderizarlos y te da feedback en lenguaje natural.
Tu trabajo NO es editar la lista: es traducir el feedback a una lista de ACCIONES que el
backend aplicará. Responde SOLO con JSON válido: {"actions": [ ... ]}.

Catálogo de acciones (campo "type"):
- drop        {"type":"drop","targets":[ids]}            → quita clips de la selección
- rescue      {"type":"rescue","targets":[ids]}          → reactiva clips (incl. descartados/bajo umbral)
- reorder     {"type":"reorder","order":[ids]}           → reordena por prioridad
- adjust_times{"type":"adjust_times","id":N,"start_time":s,"end_time":e}
- find_new    {"type":"find_new","window_start":s,"window_end":e,"hint":"qué buscar"}
- noop        {"type":"noop","reason":"por qué no actuaste / qué aclaración necesitas"}

PRIORIZACIÓN: para CUALQUIER pedido de priorizar/ordenar por un enfoque — sea una dimensión
("los más polémicos", "los de más energía") o algo temático/semántico ("los que hablan de IA",
"los más accionables", "los que empoderan", "humor negro") — usa `reorder` y construye tú el
`order` (TODOS los ids, del mejor al peor para ese enfoque) leyendo los títulos y resúmenes de
los candidatos. NO inventes ids; usa solo los que existen.

Si el pedido es ambiguo (p. ej. "busca algo gracioso" sin minuto para find_new), devuelve un noop
pidiendo la aclaración. Puedes devolver varias acciones en un mismo mensaje."""


class BriefAgent:
    """Interprets feedback → BriefAction[] via the shared LLM provider."""

    def __init__(self, temperature: float = 0.2):
        self.temperature = temperature
        self._llm = get_llm()

    def interpret(
        self,
        message: str,
        candidates: List[BriefCandidate],
        history: Optional[List[ChatMessage]] = None,
    ) -> List[BriefAction]:
        """Return the BriefActions the user's message implies (≥1; [noop] on failure)."""
        user_message = self._build_user_message(message, candidates, history)
        try:
            raw = self._llm.chat(
                system_prompt=_SYSTEM_PROMPT,
                user_message=user_message,
                temperature=self.temperature,
            )
            return self._parse(raw)
        except Exception as e:  # LLM/parse failure must never crash the chat
            return [BriefAction(type="noop", reason=f"No pude interpretar el mensaje ({e}).")]

    def _build_user_message(
        self, message, candidates, history: Optional[List[ChatMessage]]
    ) -> str:
        lines = ["## Candidatos actuales"]
        for c in candidates:
            mark = "✓" if c.selected else "·"
            lines.append(f"[{mark}] #{c.id} ({c.score:.0f}) {c.title}  [{c.start_time:.0f}s-{c.end_time:.0f}s]")
        if history:
            lines.append("\n## Conversación previa")
            for m in history[-6:]:
                lines.append(f"{m.role}: {m.content}")
        lines.append(f"\n## Feedback del usuario\n{message}")
        lines.append('\nResponde SOLO con {"actions":[...]}.')
        return "\n".join(lines)

    def _parse(self, raw) -> List[BriefAction]:
        try:
            text = raw if isinstance(raw, str) else str(raw)
            fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            payload = fence.group(1).strip() if fence else text.strip()
            data = json.loads(payload)
            raw_actions = data.get("actions", []) if isinstance(data, dict) else data
            actions = [
                BriefAction(**a)
                for a in raw_actions
                if isinstance(a, dict) and a.get("type") in ACTION_TYPES
            ]
            if not actions:
                return [BriefAction(type="noop", reason="No entendí qué cambio aplicar; ¿puedes detallarlo?")]
            return actions
        except Exception:
            return [BriefAction(type="noop", reason="No entendí el pedido; ¿puedes reformularlo?")]
