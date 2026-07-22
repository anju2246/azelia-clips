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

from packages.clips.templates.models import (
    BrandingSpec,
    BumpersSpec,
    ClipTemplate,
    IntroTitleSpec,
    LayoutSpec,
    ProgressBarSpec,
    SubtitleSpec,
)
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
        "Eres un asistente que edita TEMPLATES visuales de clips. "
        "Devuelves SIEMPRE y SOLO un objeto JSON con esta forma exacta:\n"
        '{"explanation": "<qué cambiaste, en una frase>", '
        '"unsupported": ["<cada cosa que te pidieron y NO pudiste hacer porque no hay '
        'campo para ello>"], '
        '"template": {"name": "...", "description": "...", "subtitles": {...}, '
        '"layout": {...}, "intro_title": {...}|null, "branding": {...}|null, '
        '"progress_bar": {...}|null, "bumpers": {...}|null}}\n\n'
        "CAMPOS EDITABLES (no inventes otros):\n"
        "subtitles: font_name (str), font_size (12-200), "
        "primary_color/secondary_color/outline_color/back_color (ASS '&HAABBGGRR'), "
        "bold (bool), outline (0-10), shadow (0-10), alignment (1-9 numpad ASS: "
        "1=abajo-izq 2=abajo-centro 3=abajo-der 4=medio-izq 5=centro 6=medio-der "
        "7=arriba-izq 8=arriba-centro 9=arriba-der), margin_v (0-1920), "
        "animation (" + ", ".join(_ALLOWED_ANIMATIONS) + "), words_per_line (1-10).\n"
        "layout: type ('split'=closeup+plano abierto | 'fullscreen'=un plano | 'regions'=pila "
        "de bloques). wide_height_ratio (0.20-0.50) aplica a 'split'.\n"
        "  Para varios planos usa type='regions' con 'regions': una PILA vertical de bloques de "
        "ancho completo (x=0, w=1) cuyas alturas (h) suman 1, apilados con y acumulado. Cada "
        "bloque: source.mode = 'active_speaker' (sigue a quien habla) | 'speaker' (cara fija; pon "
        "source.speaker_ref con el nombre) | 'wide' (plano abierto). Ej. 2 invitados apilados: dos "
        "bloques h=0.5 con mode='speaker'. NO uses posiciones lado a lado ni rects arbitrarios.\n"
        "intro_title (título inicial / hook): enabled (bool), duration_s (1-8), "
        "font_name, font_size (12-200), color/outline_color (ASS), "
        "position ('top'|'center'|'bottom'), box (bool), delay_captions (bool). null = sin título.\n"
        "branding (logo/marca de agua): logo_path (ruta; déjalo como está, no lo inventes), "
        "position ('top-left'|'top-right'|'bottom-left'|'bottom-right'), scale (0.02-0.30), "
        "opacity (0-1), margin (0-200). null = sin logo.\n"
        "progress_bar: enabled (bool), color (ASS), height (2-40), position ('top'|'bottom'). null = sin barra.\n"
        "bumpers (intro/outro): intro_path, outro_path (rutas; no las inventes). null = sin bumpers.\n\n"
        "REGLAS:\n"
        "- Cambia SOLO lo que el usuario pide; conserva el resto del template tal cual.\n"
        "- Respeta los rangos/enums. No inventes valores de rutas (logo/bumpers).\n"
        "- LO QUE NO PUEDAS HACER (p.ej. 'layout para 2 invitados', 'header/tweet superior', "
        "'b-roll', 'emojis automáticos') va en 'unsupported' con palabras del usuario; NO lo "
        "inventes ni lo fuerces en otro campo.\n"
        "- No añadas texto fuera del JSON."
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


def _opt(spec_cls, value, current):
    """Coerce an optional nested spec: a dict → validated spec, explicit null →
    None (disable), missing key → keep current."""
    if value is None:
        return None
    if isinstance(value, dict):
        return spec_cls(**value)
    return current


def _diff(old: dict, new: dict, prefix: str = "") -> list[dict]:
    """Flat list of {path, old, new} for every leaf that changed."""
    changes: list[dict] = []
    keys = set(old or {}) | set(new or {})
    for k in sorted(keys):
        path = f"{prefix}{k}"
        ov, nv = (old or {}).get(k), (new or {}).get(k)
        if isinstance(ov, dict) or isinstance(nv, dict):
            changes.extend(_diff(ov or {}, nv or {}, prefix=f"{path}."))
        elif ov != nv:
            changes.append({"path": path, "old": ov, "new": nv})
    return changes


def _normalize_layout(raw: dict) -> dict:
    """Reconcile `type` with an explicit `regions` list before validation.

    Models routinely echo the base layout's `type` while emitting the region
    stack the user asked for. Taking the list as the statement of intent keeps
    that request from being dropped as stale by LayoutSpec.
    """
    if not isinstance(raw, dict):
        return raw
    if raw.get("regions") and raw.get("type") != "regions":
        return {**raw, "type": "regions"}
    return raw


def _coerce(raw: str, base: ClipTemplate) -> dict:
    """Validate the model reply into {explanation, template, changes, unsupported}."""
    data = _extract_json(raw)
    t = data.get("template")
    if not isinstance(t, dict):
        raise ValueError("missing template object")

    subtitles = SubtitleSpec(**t["subtitles"]) if t.get("subtitles") else base.subtitles
    layout = LayoutSpec(**_normalize_layout(t["layout"])) if t.get("layout") else base.layout

    # Optional v2 specs: present-and-dict → set, explicit null → disable,
    # key absent → keep what the draft already had.
    def field(key, cls):
        return _opt(cls, t[key], getattr(base, key)) if key in t else getattr(base, key)

    # id / is_builtin / created_at are authoritative from the base, never the model.
    from datetime import datetime

    updated = base.model_copy(
        update={
            "name": t.get("name", base.name),
            "description": t.get("description", base.description),
            "subtitles": subtitles,
            "layout": layout,
            "intro_title": field("intro_title", IntroTitleSpec),
            "branding": field("branding", BrandingSpec),
            "progress_bar": field("progress_bar", ProgressBarSpec),
            "bumpers": field("bumpers", BumpersSpec),
            "updated_at": datetime.now().isoformat(),
        }
    )

    # Field-level diff (ignore the always-changing updated_at).
    old_dump, new_dump = base.model_dump(), updated.model_dump()
    old_dump.pop("updated_at", None)
    new_dump.pop("updated_at", None)
    changes = _diff(old_dump, new_dump)

    unsupported = data.get("unsupported") or []
    if not isinstance(unsupported, list):
        unsupported = []

    return {
        "explanation": str(data.get("explanation", "")),
        "template": updated,
        "changes": changes,
        "unsupported": [str(u) for u in unsupported],
    }


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
