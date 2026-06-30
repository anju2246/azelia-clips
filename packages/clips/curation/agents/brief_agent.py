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
- adjust_times{"type":"adjust_times","id":N,"start_time":s,"end_time":e}  → mueve el inicio/fin de #N
- trim_to_text{"type":"trim_to_text","id":N,"keep_text":"<fragmento EXACTO a conservar>"}
              → recorta #N para que contenga SOLO ese fragmento citado (resuelto a tiempos por el backend)
- find_new    {"type":"find_new","window_start":s,"window_end":e,"hint":"qué buscar"}
- noop        {"type":"noop","reason":"por qué no actuaste / qué aclaración necesitas"}

FOCO INDIVIDUAL (CRÍTICO): el usuario revisa los clips de a UNO. El feedback es SIEMPRE sobre el
clip en foco salvo que nombre OTRO clip por su número. NUNCA apliques un cambio global a todos los
clips a partir de feedback de un clip. Solo usa `drop` cuando el usuario nombre explícitamente otros
clips ("quita el 5 y el 8"); jamás para "limpiar el resto".

RECORTE POR TEXTO: si sobre el clip en foco el usuario pega un fragmento del transcript y dice cosas
como "déjalo solo con esto", "saca solo esta parte", "recórtalo a esto", "lo demás bórralo/quítalo/
elimínalo" → usa trim_to_text con id = clip en foco y keep_text = el fragmento citado TAL CUAL.
Aquí "lo demás" significa el resto DEL MISMO CLIP, NUNCA otros clips. No emitas drop en este caso.
Abajo tienes el TRANSCRIPT del clip en foco. NUNCA respondas que "solo conoces los rangos del clip"
ni que "no puedes cortar en el medio": SÍ puedes. Si el usuario pega, cita o describe un fragmento,
emite trim_to_text con keep_text = ese fragmento (o, si lo describe, el tramo correspondiente del
transcript que ves). El backend lo resuelve a tiempos exactos, incluso si el fragmento cae un poco
fuera del rango actual del clip. Solo usa noop si el pedido es genuinamente ambiguo, jamás para
excusarte de cortar.

PRIORIZACIÓN: para CUALQUIER pedido de priorizar/ordenar por un enfoque — sea una dimensión
("los más polémicos", "los de más energía") o algo temático/semántico ("los que hablan de IA",
"los más accionables", "los que empoderan", "humor negro") — usa `reorder` y construye tú el
`order` (TODOS los ids, del mejor al peor para ese enfoque) leyendo los títulos y resúmenes de
los candidatos. NO inventes ids; usa solo los que existen.

Si el pedido es ambiguo (p. ej. "busca algo gracioso" sin minuto para find_new), devuelve un noop
pidiendo la aclaración. Puedes devolver varias acciones en un mismo mensaje."""


_MAX_FOCUS_TRANSCRIPT_CHARS = 4000  # defensive truncation of the focus clip text


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
        focus_id: Optional[int] = None,
    ) -> List[BriefAction]:
        """Return the BriefActions the user's message implies (≥1; [noop] on failure).

        ``focus_id`` is the candidate the user is reviewing on screen (one-by-one
        flow); when set, ambiguous feedback resolves to that clip.
        """
        user_message = self._build_user_message(message, candidates, history, focus_id)
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
        self, message, candidates, history: Optional[List[ChatMessage]], focus_id=None
    ) -> str:
        lines = ["## Candidatos actuales"]
        for c in candidates:
            mark = "✓" if c.selected else "·"
            star = " ← EN FOCO" if focus_id is not None and c.id == focus_id else ""
            lines.append(f"[{mark}] #{c.id} ({c.score:.0f}) {c.title}  [{c.start_time:.0f}s-{c.end_time:.0f}s]{star}")
        if focus_id is not None:
            lines.append(
                f"\n## Clip en foco: #{focus_id}\n"
                f"El usuario está revisando EXCLUSIVAMENTE el clip #{focus_id}. "
                f"Cualquier referencia ambigua ('recórtalo', 'quítalo', 'más corto', "
                f"'busca un mejor cierre/arranque', 'no me convence') aplica al #{focus_id}. "
                f"No toques otros clips salvo que el usuario los nombre explícitamente."
            )
            focus_c = next((c for c in candidates if c.id == focus_id), None)
            tx = (getattr(focus_c, "transcript", "") or "").strip() if focus_c else ""
            if tx:
                if len(tx) > _MAX_FOCUS_TRANSCRIPT_CHARS:  # clips are short; just a guard
                    tx = tx[:_MAX_FOCUS_TRANSCRIPT_CHARS] + " …"
                lines.append(f"\n## Transcript del clip en foco #{focus_id}\n{tx}")
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
