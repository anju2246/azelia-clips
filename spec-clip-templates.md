# Spec: Editor de Templates de Clips con asistente de IA + formato exportable

## Status
Approved

## Purpose
Permitir que el usuario **cree y edite sus propios templates visuales para los clips** (estilo de
subtítulos + layout) desde la interfaz del dashboard, sin tocar código. El editor incluye un **chat de IA**
que ayuda a modificar el template en lenguaje natural y acepta una **imagen de referencia** para que el
modelo intente **replicar** ese estilo. Cada template se guarda en un **formato JSON portable (`.azt`)**
versionado e importable/exportable, pensado para que en el futuro la comunidad pueda compartirlo en un
marketplace. Reemplaza el estilo `splitscreen` actualmente hardcodeado en el pipeline por un template
seleccionable. Mantiene la promesa local-first: todo vive en disco bajo el perfil activo, sin backend central.

## Scope

### In Scope
- **Modelo `ClipTemplate`**: controla **subtítulos** (fuente, tamaño, colores, contorno, sombra, animación,
  posición/márgenes, palabras por línea) y **layout** (`split` | `fullscreen`, salida 1080×1920, con la
  **proporción de la división del split ajustable**).
- **Presets built-in** derivados de los 5 estilos existentes (`hormozi`, `mrbeast`, `minimal`, `podcast`,
  `splitscreen`) expuestos como templates de **solo lectura, clonables**.
- **CRUD de templates custom por perfil**: crear, listar, leer, editar, borrar, clonar.
- **Persistencia por perfil**: un archivo `.azt` (JSON) por template bajo `<data_dir>/templates/<slug>.azt`,
  donde `<data_dir>` es el del perfil activo (multi-perfil).
- **Import/Export `.azt`**: descargar un template como archivo y subir uno externo (validando esquema),
  base del formato de marketplace. Fuentes referenciadas **por nombre** (deben estar instaladas en la máquina).
- **Chat de IA (texto)** que edita el template draft: el usuario describe cambios, el modelo devuelve un
  template actualizado + explicación; la UI aplica el cambio y refresca el preview.
- **Imagen de referencia (visión)**: el usuario adjunta una imagen; el modelo intenta replicar el estilo.
  Ruta de visión: **Claude Code CLI primero** (spike), **fallback a Anthropic API** (BYOK). Si ningún
  proveedor con visión está disponible, error claro.
- **Preview en vivo (mockup) interactivo**: render aproximado en el navegador (frame de muestra + CSS) que
  imita subtítulos y layout. **WYSIWYG**: el usuario **arrastra el bloque de subtítulos** y al soltar hace
  *snap* al ancla ASS más cercana (9 zonas) + margen vertical; y en layout `split` **arrastra el divisor**
  para ajustar la proporción close-up/wide. Sin render FFmpeg.
- **Aplicación al pipeline**: cada perfil tiene un **template default** (settings) y en el upload se puede
  **sobreescribir por job**. El pipeline usa el template elegido en lugar del `splitscreen` hardcodeado.

### Out of Scope
- Marketplace real (publicar/descubrir/instalar desde un servidor remoto). Solo se diseña el **formato**
  y el import/export local.
- Empaquetado de fuentes/assets dentro del template (bundle). v1 referencia fuentes **por nombre**.
- Nuevos **tipos** de layout más allá de `split`/`fullscreen`, o crop/posicionamiento por píxel libre. La
  salida queda fija en 1080×1920. (Sí se ajusta la **proporción** de la división del split — ver LayoutSpec.)
- Parámetros de calidad de render FFmpeg (CRF/preset/bitrate) configurables por el usuario.
- Render real de muestra dentro del editor (solo mockup CSS).
- Editar el comportamiento de curación (Finder/Critic/Ranker) o de reframe/face-tracking.
- Multi-usuario / auth / sincronización entre máquinas.

## Tech Stack
- Backend: Python 3 / FastAPI (`server/`), Pydantic v2 models.
- Pipeline: `packages/clips/` (subtítulos ASS via `subtitles/generator.py`, reframe via `vision/reframer.py`).
- LLM: `packages/core/llm_provider.py` (`MultiProviderLLM`: Claude Code CLI → Anthropic API).
- Frontend: Astro + React + TypeScript (`web/`).
- Persistencia: archivos `.azt` (JSON) bajo el `data_dir` del perfil + clave en `secrets.env` para el default.
- Test runner: `pytest` (backend). (Comando exacto a confirmar en CLAUDE.md/pyproject — ver Done Conditions.)

## Core Entities

### ClipTemplate (`.azt` JSON, `schema_version: 1`)
| Campo | Tipo | Constraints | Descripción |
|-------|------|-------------|-------------|
| schema_version | int | required, = 1 | Versión del formato (para import futuro) |
| id | str (slug) | required, único por perfil, `^[a-z0-9-]{1,48}$` | Identificador/slug del template |
| name | str | required, 1–60 chars | Nombre visible ("Mi Marca") |
| description | str | opcional, ≤ 280 chars | Descripción corta |
| author | str | opcional, ≤ 60 chars | Atribución (para marketplace) |
| is_builtin | bool | default false | true = preset de solo lectura (no editable/borrable) |
| created_at | str (ISO 8601) | required | Fecha de creación |
| updated_at | str (ISO 8601) | required | Última edición |
| subtitles | SubtitleSpec | required | Ver abajo |
| layout | LayoutSpec | required | Ver abajo |

### SubtitleSpec
| Campo | Tipo | Constraints | Default |
|-------|------|-------------|---------|
| font_name | str | 1–60 chars (debe existir en la máquina) | "Montserrat" |
| font_size | int | 12–200 | 52 |
| primary_color | str | ASS ABGR `^&H[0-9A-Fa-f]{8}$` | "&H00FFFFFF" |
| secondary_color | str | ASS ABGR (color de highlight) | "&H0000FFFF" |
| outline_color | str | ASS ABGR | "&H00000000" |
| back_color | str | ASS ABGR | "&H80000000" |
| bold | bool | — | true |
| outline | int | 0–10 | 3 |
| shadow | int | 0–10 | 2 |
| alignment | int | 1–9 (numpad ASS) | 2 |
| margin_v | int | 0–1920 | 50 |
| animation | enum | `highlight`\|`karaoke`\|`box`\|`cumulative` | "cumulative" |
| words_per_line | int | 1–10 | 5 |

### LayoutSpec
| Campo | Tipo | Constraints | Default |
|-------|------|-------------|---------|
| type | enum | `split`\|`fullscreen` | "split" |
| output_width | int | = 1080 (fijo v1) | 1080 |
| output_height | int | = 1920 (fijo v1) | 1920 |
| wide_height_ratio | float | 0.20–0.50; solo aplica si `type == "split"` | 0.32 |

> Nota 1: cuando `layout.type == "split"`, el subtítulo suele necesitar `margin_v` alto (el preset
> `splitscreen` usa ~620). El template guarda el `margin_v` real, así que es coherente; el editor sugiere
> un default razonable según el layout pero el valor mandado es el del template.
>
> Nota 2: `wide_height_ratio` ya existe en `reframer.py:222` (`wide_height_ratio: float = 0.32`, ≈ 608/1920);
> el template solo lo expone. El close-up ocupa el resto (`1920 − wide`). El divisor arrastrable del preview
> edita este valor. El default 0.32 conserva el layout actual exacto.

## Features

### F1 — CRUD y almacenamiento de templates
**Endpoints:**
- `GET /api/templates` → `{ templates: ClipTemplate[] }` (built-ins + custom del perfil activo)
- `GET /api/templates/{id}` → `ClipTemplate`
- `POST /api/templates` → crea custom; body `ClipTemplate` (sin id/timestamps; servidor los asigna)
- `PUT /api/templates/{id}` → actualiza custom
- `DELETE /api/templates/{id}` → borra custom
- `POST /api/templates/{id}/clone` → clona (usado para forkear un built-in); body `{ name }`

**Business Rules:**
1. Built-ins se sintetizan al vuelo desde el dict `STYLES` de `subtitles/generator.py` con `is_builtin=true`;
   no se escriben a disco.
2. Editar/borrar un built-in → error (no permitido); el flujo correcto es clonarlo.
3. El slug se deriva del `name` (kebab-case) y se desambigua con sufijo `-2`, `-3`… si colisiona.
4. Los archivos se guardan en `<data_dir>/templates/<slug>.azt` del perfil activo.

**Error cases:**
| Condición | HTTP | Error Code | Mensaje |
|-----------|------|-----------|---------|
| GET/PUT/DELETE id inexistente | 404 | TEMPLATE_NOT_FOUND | Template no encontrado |
| PUT/DELETE sobre built-in | 409 | TEMPLATE_READONLY | Los presets no se editan; clónalo primero |
| Body inválido (esquema) | 422 | TEMPLATE_INVALID | Detalle de validación por campo |

### F2 — Import / Export `.azt`
**Endpoints:**
- `GET /api/templates/{id}/export` → descarga `application/json` con el `.azt` (incluye `schema_version`).
- `POST /api/templates/import` → multipart con archivo `.azt`; valida `schema_version` y esquema, lo guarda
  como nuevo custom (slug desambiguado), `is_builtin=false`.

**Business Rules:**
1. Import rechaza `schema_version` desconocido (futuro: migraciones).
2. Import no confía en `id`/`is_builtin` del archivo: reasigna slug y fuerza `is_builtin=false`.
3. Si `font_name` no está instalada, el import **igual procede** pero la respuesta incluye `warnings`
   (`FONT_NOT_INSTALLED`) — no es fatal.

**Error cases:**
| Condición | HTTP | Error Code | Mensaje |
|-----------|------|-----------|---------|
| Archivo no es JSON válido | 422 | IMPORT_PARSE_ERROR | El archivo no es un .azt válido |
| schema_version no soportado | 422 | IMPORT_VERSION_UNSUPPORTED | Versión de formato no soportada |

### F3 — Chat de IA (texto) para editar el template
**Endpoint:** `POST /api/templates/chat`
**Input:**
```
{
  "template": ClipTemplate,        // draft actual
  "messages": [{ "role": "user"|"assistant", "content": str }],
  "image_b64": str | null          // opcional (ver F4)
}
```
**Output (success):**
```
HTTP 200
{
  "explanation": str,              // texto natural para mostrar en el chat
  "template": ClipTemplate,        // draft actualizado (mismos id/name salvo que se pidan cambiar)
  "provider_used": str             // "claude-code-cli" | "<modelo anthropic>"
}
```
**Business Rules:**
1. Usa `MultiProviderLLM`. El system prompt restringe al modelo a editar **solo** campos de `subtitles` y
   `layout` y a devolver **JSON estricto** `{explanation, template}`.
2. El modelo recibe el template draft actual + esquema/constraints; debe respetar enums y rangos.
3. La respuesta se **valida** contra el esquema `ClipTemplate`; si no parsea o viola constraints, se reintenta
   una vez con un mensaje de corrección; si vuelve a fallar → error.
4. El endpoint **no persiste**: devuelve el draft; el guardado es explícito vía F1 (`POST`/`PUT`).

**Error cases:**
| Condición | HTTP | Error Code | Mensaje |
|-----------|------|-----------|---------|
| No hay proveedor LLM configurado | 503 | LLM_UNAVAILABLE | Configura Claude Code o una API key |
| El modelo no devolvió template válido (2 intentos) | 502 | LLM_BAD_OUTPUT | El asistente no pudo generar un cambio válido |

### F4 — Imagen de referencia (visión)
Extiende la capa LLM con capacidad de visión, usada por F3 cuando `image_b64 != null`.

**Business Rules:**
1. Orden de visión: **Claude Code CLI primero** — guardar la imagen en archivo temporal y referenciar su
   ruta absoluta en el prompt para que la CLI la lea (**spike**: verificar soporte real de imágenes en
   `claude -p`). Si falla o no soporta → **fallback Anthropic API** con bloque de contenido `image` (base64).
2. Si **ningún** proveedor con visión está disponible (CC sin soporte y sin API key), responder error claro
   y permitir continuar el chat en modo solo-texto.
3. Validar la imagen: tipos `image/png|jpeg|webp`, tamaño ≤ 5 MB.
4. El system prompt instruye: "analiza la imagen y traduce su estilo de subtítulos/layout a los campos del
   template; no inventes campos fuera del esquema".

**Error cases:**
| Condición | HTTP | Error Code | Mensaje |
|-----------|------|-----------|---------|
| Imagen pero ningún proveedor con visión | 422 | VISION_UNAVAILABLE | Adjuntar imagen requiere visión; configura una API key |
| Imagen demasiado grande / tipo inválido | 422 | IMAGE_INVALID | Imagen no soportada (png/jpeg/webp, ≤ 5MB) |

### F5 — Preview en vivo (mockup interactivo, frontend)
- Página nueva `/dashboard/templates`: lista de templates + editor (formulario de campos) + chat + **mockup**.
- El mockup muestra un **frame de muestra** (asset estático del repo) con un overlay de subtítulos en CSS que
  aproxima `font_name`, `font_size`, colores, `alignment`, `margin_v` y la animación (estado representado),
  más la composición del `layout.type` (split con su divisor, o fullscreen). Sin llamadas de render al backend.
- **Interacción directa (WYSIWYG):**
  1. **Arrastrar el bloque de subtítulos** → al soltar, la posición hace *snap* al `alignment` (1–9, anclas
     numpad ASS) más cercano y calcula el `margin_v` resultante. Los campos del formulario se actualizan en
     consecuencia (la fuente de verdad sigue siendo `alignment`+`margin_v`, no píxeles libres).
  2. En layout `split`, **arrastrar el divisor** horizontal ajusta `wide_height_ratio` (clamp 0.20–0.50).
- El mockup se actualiza en vivo ante: edición manual del formulario, arrastre directo, y respuestas del chat.

**Business Rules:**
1. El arrastre nunca produce posiciones que ASS no pueda reproducir: siempre se reduce a `alignment`+`margin_v`.
2. `wide_height_ratio` se *clampa* al rango válido; el divisor no permite tapar por completo close-up ni wide.

### F6 — Aplicación del template en el pipeline
**Business Rules:**
1. Nuevo setting por perfil `default_template_id` (en `secrets.env`), default = `"splitscreen"` (built-in)
   para preservar el comportamiento actual.
2. `ProcessRequest` gana `template_id: str | None`; si `None` se usa el `default_template_id` del perfil.
3. El formulario de upload muestra un selector "Template" con default = el del perfil.
4. En `packages/clips/pipeline.py` (hoy `style='splitscreen'`, `animation='cumulative'` hardcodeados ~L687):
   - cargar el `ClipTemplate` resuelto,
   - construir `SubtitleStyle`/`SubtitleGenerator` desde `template.subtitles`,
   - usar `template.subtitles.animation` y `words_per_line`,
   - elegir el layout en el reframe según `template.layout.type` y, si es `split`, pasar
     `template.layout.wide_height_ratio` a la función de split del reframer.
5. Persistir el `template_id` aplicado en el job (job store) para trazabilidad.

**Error cases:**
| Condición | HTTP | Error Code | Mensaje |
|-----------|------|-----------|---------|
| `template_id` no existe al procesar | 422 | TEMPLATE_NOT_FOUND | El template seleccionado no existe |

## Non-Functional Requirements
- **Local-first**: nada sale de la máquina salvo la llamada LLM que el usuario ya elige (Claude Code/Anthropic).
- **Aislamiento por perfil**: templates del perfil A nunca visibles desde el perfil B.
- **Compatibilidad**: instalaciones existentes siguen funcionando — default = built-in `splitscreen`, mismo
  resultado visual que hoy si el usuario no toca nada.
- **Preview**: el mockup responde < 100 ms a cada cambio (es CSS, sin red).
- **Seguridad**: la imagen adjunta se guarda en archivo temporal y se borra tras la llamada; sin secretos en
  los `.azt`; validación estricta de esquema en import (no ejecutar nada del archivo).
- **Autorización/Auth**: ninguna (single-user localhost, coherente con el resto del producto).

## Riesgos / Spikes
| Riesgo | Mitigación |
|--------|-----------|
| Claude Code CLI puede no aceptar imágenes en `-p` | Spike temprano; Anthropic API es el camino garantizado; degradar a solo-texto si no hay visión |
| Fidelidad del mockup CSS vs render FFmpeg real | Documentar que es aproximado; campos mapeados 1:1 con `SubtitleStyle`; arrastre limitado a `alignment`+`margin_v` (lo que ASS sabe reproducir); (opcional futuro: botón render de prueba) |
| Arrastre libre que ASS no pueda reproducir | El drag siempre hace *snap* a ancla+margen; nunca posición por píxel (`\pos`) en v1 |
| Fuentes referenciadas por nombre ausentes en otra máquina | `warnings` en import (`FONT_NOT_INSTALLED`); no fatal |
| Salida JSON del LLM inválida | Validación + 1 reintento con corrección; error explícito si persiste |

## Done Conditions
- [ ] Existe `ClipTemplate` (Pydantic) con validación de todos los campos/constraints y serialización `.azt`.
- [ ] Los 5 presets aparecen como built-ins de solo lectura vía `GET /api/templates`.
- [ ] CRUD completo (crear/leer/editar/borrar/clonar) de templates custom persiste en `<data_dir>/templates/`.
- [ ] Export/import `.azt` round-trip: exportar un template y reimportarlo produce un template equivalente.
- [ ] `POST /api/templates/chat` (texto) devuelve un template válido y la UI lo aplica al draft.
- [ ] Con imagen adjunta, el chat usa visión (CC CLI o fallback Anthropic) o responde `VISION_UNAVAILABLE`.
- [ ] Página `/dashboard/templates` permite crear/editar con preview mockup en vivo e **interactivo**:
      arrastrar subtítulos hace snap a `alignment`+`margin_v`, y arrastrar el divisor del split ajusta
      `wide_height_ratio`.
- [ ] El pipeline aplica el template seleccionado (default por perfil + override por job) en lugar del
      `splitscreen` hardcodeado; sin template elegido, el resultado es idéntico al actual.
- [ ] Todos los tests nuevos pasan bajo el runner del proyecto (`pytest`).
