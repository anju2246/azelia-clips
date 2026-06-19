"""AI-assisted template editing.

Given the current template draft + a chat history, ask the LLM to return an
updated template as strict JSON ({explanation, template}); validate it against
the schema, retrying once with a correction nudge. The endpoint persists nothing
— it returns the new draft and the caller saves explicitly.

Vision (a reference image) is wired in T6 via ``chat_vision``; here only the
text path is exercised.
"""

import base64
import binascii
import json
import re

from packages.clips.templates.models import ClipTemplate, LayoutSpec, SubtitleSpec
from packages.core.llm_provider import get_llm, vision_available

__all__ = [
    "edit",
    "get_llm",
    "vision_available",
    "decode_reference_image",
    "TemplateChatError",
    "ImageInvalid",
]


class TemplateChatError(Exception):
    """The model failed to produce a valid template after the retry."""


class ImageInvalid(Exception):
    """The reference image is not a supported type or is too large."""


_MAX_IMAGE_BYTES = 5 * 1024 * 1024


def decode_reference_image(image_b64: str) -> tuple[bytes, str]:
    """Decode + validate a reference image. Returns (bytes, extension).

    Accepts a raw base64 string or a data URL. Rejects non-image payloads,
    unsupported types, and anything over 5 MB. Raises ImageInvalid.
    """
    payload = image_b64.strip()
    if payload.startswith("data:"):
        _, _, payload = payload.partition(",")
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ImageInvalid("La imagen no es base64 válido") from e

    if not data:
        raise ImageInvalid("Imagen vacía")
    if len(data) > _MAX_IMAGE_BYTES:
        raise ImageInvalid("La imagen supera 5 MB")

    if data[:8].startswith(b"\x89PNG\r\n\x1a\n"):
        return data, ".png"
    if data[:3] == b"\xff\xd8\xff":
        return data, ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return data, ".webp"
    raise ImageInvalid("Tipo no soportado (png/jpeg/webp)")


_ALLOWED_ANIMATIONS = ["highlight", "karaoke", "box", "cumulative"]


def build_system_prompt() -> str:
    return (
        "Eres un asistente que edita TEMPLATES de subtítulos/clips. "
        "Devuelves SIEMPRE y SOLO un objeto JSON con esta forma exacta:\n"
        '{"explanation": "<qué cambiaste, en una frase>", '
        '"template": {"name": "...", "description": "...", '
        '"subtitles": {<campos>}, "layout": {<campos>}}}\n\n'
        "Campos de subtitles: font_name (str), font_size (12-200), "
        "primary_color/secondary_color/outline_color/back_color (formato ASS '&HAABBGGRR'), "
        "bold (bool), outline (0-10), shadow (0-10), alignment (1-9 numpad ASS), "
        "margin_v (0-1920), animation (uno de: " + ", ".join(_ALLOWED_ANIMATIONS) + "), "
        "words_per_line (1-10).\n"
        "Campos de layout: type ('split' o 'fullscreen'), wide_height_ratio (0.20-0.50).\n"
        "Respeta esos rangos. No inventes campos. No añadas texto fuera del JSON."
    )


def _build_user_message(template: ClipTemplate, messages: list[dict]) -> str:
    history = "\n".join(
        f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages
    )
    return (
        "Template actual (JSON):\n"
        f"{template.model_dump_json(indent=2)}\n\n"
        "Conversación:\n"
        f"{history}\n\n"
        "Devuelve el template actualizado como JSON {explanation, template}."
    )


def _extract_json(raw: str) -> dict:
    """Pull the outermost JSON object out of a possibly fenced/explained reply."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found")
    return json.loads(text[start : end + 1])


def _coerce(raw: str, base: ClipTemplate) -> dict:
    """Validate the model reply into {explanation, template}. Raises on bad data."""
    data = _extract_json(raw)
    t = data.get("template")
    if not isinstance(t, dict):
        raise ValueError("missing template object")

    subtitles = SubtitleSpec(**t["subtitles"]) if t.get("subtitles") else base.subtitles
    layout = LayoutSpec(**t["layout"]) if t.get("layout") else base.layout

    # id / is_builtin / created_at are authoritative from the base, never the model.
    from datetime import datetime

    updated = base.model_copy(
        update={
            "name": t.get("name", base.name),
            "description": t.get("description", base.description),
            "subtitles": subtitles,
            "layout": layout,
            "updated_at": datetime.now().isoformat(),
        }
    )
    return {"explanation": str(data.get("explanation", "")), "template": updated}


def edit(
    template: ClipTemplate,
    messages: list[dict],
    image_path: str | None = None,
    llm=None,
) -> dict:
    """Run one AI edit turn. Returns {explanation, template, provider_used}.

    Raises TemplateChatError if the model can't produce a valid template within
    two attempts. ``image_path`` is accepted for forward-compat (vision in T6).
    """
    llm = llm or get_llm()
    system = build_system_prompt()
    user = _build_user_message(template, messages)
    provider_used = ""
    try:
        provider_used = llm.providers[0]["name"]
    except Exception:
        provider_used = "unknown"

    last_err: Exception | None = None
    for attempt in range(2):
        # Vision unavailability is a hard error, not a "bad output" to retry.
        if image_path:
            raw = llm.chat_vision(system, user, image_path)
        else:
            raw = llm.chat(system, user)
        try:
            result = _coerce(raw, template)
            result["provider_used"] = provider_used
            return result
        except Exception as e:  # noqa: BLE001 — any parse/validation failure → retry once
            last_err = e
            user = (
                _build_user_message(template, messages)
                + f"\n\nTu respuesta anterior no fue válida ({e}). "
                "Devuelve EXACTAMENTE el JSON {explanation, template} y nada más."
            )

    raise TemplateChatError(f"El asistente no generó un template válido: {last_err}")
