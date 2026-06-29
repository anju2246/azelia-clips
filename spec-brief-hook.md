# Spec: Aprobación/edición del hook (texto de los primeros ~6s) en el brief

## Status
Approved (firmado 2026-06-28). Default del campo = título del clip (pre-cargado).

## Purpose
Cuando el template aplicado al job tiene el **hook title** activo (`intro_title.enabled`),
el chat inicial de revisión (brief) debe mostrar, por cada clip, el **texto del hook** en
un campo editable para que el creador lo **apruebe o lo modifique a mano** antes de renderizar.
Si el template NO tiene el hook activo, ese campo **no aparece**. Hoy el texto del hook se
autogenera (= título del clip) y se renderiza sin aprobación: este spec agrega el control humano.

## Decisiones de producto (ya tomadas)
1. **Campo hook separado** del título: nuevo `hook_text`, independiente de `title`.
2. **Edición inline** en la tarjeta del clip (determinista, sin pasar por el LLM del chat).
3. **Gating** = el toggle del template (`intro_title.enabled`). El brief siempre está activo,
   así que el único condicional es el del template.

## Scope
### In
- `hook_text` en `BriefCandidate` y `CuratedClip`.
- `build_session` rellena `hook_text` (default = `title` del clip → pre-cargado y editable).
- El brief expone `hook_enabled` (y `hook_duration_s`) derivado del template del job.
- Endpoint para editar el `hook_text` de un candidato.
- `_approved_curated_clips` arrastra `hook_text` al `CuratedClip`.
- Render usa `hook_text or title` para la tarjeta de hook.
- UI: campo editable inline en `BriefChatModal`, visible solo si `hook_enabled`.
### Out
- Cambiar cómo se ESTILIZA el hook (fuente/posición/duración) — eso ya vive en el editor de templates.
- Acción conversacional `set_hook` (descartada: la edición es inline).
- Aprobar el hook cuando el brief está apagado (no aplica: el brief nunca se apaga).

## Modelo de datos
### `BriefCandidate` (packages/clips/curation/brief_models.py)
| Campo | Tipo | Default | Nota |
|---|---|---|---|
| `hook_text` | `str` | `""` | Texto del hook editable. En `build_session` se inicializa al `title`. |

### `CuratedClip` (packages/clips/curation/models.py)
| Campo | Tipo | Default | Nota |
|---|---|---|---|
| `hook_text` | `str` | `""` | Texto del hook. Vacío → render cae al `title` (no-regresión). |

### `BriefSession` (packages/clips/curation/brief_models.py)
| Campo | Tipo | Default | Nota |
|---|---|---|---|
| `hook_enabled` | `bool` | `False` | `True` si el template del job tiene `intro_title.enabled`. |
| `hook_duration_s` | `float` | `0.0` | Para mostrar "primeros Ns" en la UI (informativo). |

## Backend
### `build_session(job_dir, episode_id, min_score, *, hook_enabled=False, hook_duration_s=0.0)`
- Inicializa cada candidato con `hook_text = clip.get("title","")`.
- Setea `session.hook_enabled` / `session.hook_duration_s` desde los args.
- Sin regresión: con defaults (`hook_enabled=False`) el comportamiento es idéntico al actual.

### `_open_brief_gate` (packages/clips/pipeline.py)
- Resuelve el template una vez: `TemplateStore(settings.templates_dir()).resolve(self.template_id)`.
- Pasa `hook_enabled = bool(tpl.intro_title and tpl.intro_title.enabled)` y
  `hook_duration_s = tpl.intro_title.duration_s if enabled else 0.0` a `build_session`.

### Endpoint nuevo
```
POST /api/clips/jobs/{job_id}/brief/candidate/{cand_id}/hook
body: { "hook_text": str }   # se recorta; se limita a ~120 chars
→ 200 { ...brief_payload }    # sesión actualizada y persistida
→ 404 si el candidato no existe ; 409 si la sesión no está en awaiting_brief
```
- Actualiza `hook_text` del candidato, persiste la sesión (save_session), devuelve el payload.

### `_brief_payload(session)`
- Incluye `hook_enabled`, `hook_duration_s` y `hook_text` por candidato (ya sale en `model_dump`).

### `_approved_curated_clips` (packages/clips/curation, server/routes/clips.py)
- En el `model_copy(update={...})` y en el clip "bare" (rescued/found): incluir
  `"hook_text": c.hook_text or curation[i].title` (o `c.hook_text` para bare).

### Render (packages/clips/pipeline.py:~704)
- `clip_title = getattr(clip, "hook_text", "") or getattr(clip, "title", "")`.
- El generador (`generate_word_by_word(..., clip_title=...)`) no cambia su firma.

## Frontend (web/src/components/workflow/BriefChatModal.tsx)
- Si `hook_enabled`: en cada tarjeta de clip, debajo del título, un input editable
  "Hook (primeros {hook_duration_s}s)" pre-cargado con `candidate.hook_text`.
- onBlur / "guardar" → `POST .../brief/candidate/{id}/hook` con el texto; refresca el payload.
- Si NO `hook_enabled`: el campo no se renderiza (cero cambios visuales).
- Tipos en `web/src/lib/api.ts`: `hook_text` en el candidato; `hook_enabled`/`hook_duration_s` en el payload del brief.

## Edge cases
| Caso | Esperado |
|---|---|
| Template sin `intro_title` o `enabled=False` | `hook_enabled=False`; sin campo; render igual que hoy. |
| `hook_text` vacío tras editar | Render cae al `title` (no se rompe el hook). |
| `hook_text` > límite | Se recorta a ~120 chars en el endpoint. |
| Clip rescued/found (sin source de curación) | `hook_text` = el que traiga el candidato (default su `title`). |
| Caracteres `{ }` / saltos de línea en el hook | El generador ya neutraliza `{}` y `\n` (`_intro_title_event`). |

## Done Conditions
- [ ] `BriefCandidate`/`CuratedClip`/`BriefSession` tienen los campos nuevos (defaults no-regresivos).
- [ ] `build_session` inicializa `hook_text=title` y propaga `hook_enabled`.
- [ ] `_open_brief_gate` deriva `hook_enabled` del template del job.
- [ ] Endpoint POST hook edita y persiste; 404/409 cubiertos.
- [ ] `_approved_curated_clips` arrastra `hook_text`; render usa `hook_text or title`.
- [ ] UI muestra el campo SOLO si `hook_enabled`; edición persiste.
- [ ] Tests: gating on/off, default=title, override de hook, fallback a title, endpoint 200/404, no-regresión del .ass cuando `enabled=False`.
- [ ] `security_gate` verde; suite verde.
