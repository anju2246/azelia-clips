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
1. Visión **exclusivamente vía Claude Code CLI** (suscripción del usuario, $0). **Sin fallback a Anthropic
   API.** Se guarda la imagen en archivo temporal y se referencia su ruta absoluta en el prompt para que la
   CLI la lea con su herramienta Read (**spike**: verificar soporte real de imágenes en `claude -p`).
2. Si Claude Code no está disponible o no soporta imágenes → `VISION_UNAVAILABLE`; el chat de **texto** sigue
   operativo (usando el router normal). El adjuntar imagen se deshabilita en la UI cuando no hay visión.
3. Validar la imagen: tipos `image/png|jpeg|webp`, tamaño ≤ 5 MB. Archivo temporal con borrado garantizado.
4. El system prompt instruye: "analiza la imagen y traduce su estilo de subtítulos/layout a los campos del
   template; no inventes campos fuera del esquema".

**Error cases:**
| Condición | HTTP | Error Code | Mensaje |
|-----------|------|-----------|---------|
| Imagen pero Claude Code no disponible/sin visión | 422 | VISION_UNAVAILABLE | Adjuntar imagen requiere Claude Code |
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

---

# v2 Extensions — Conectar + Ampliar el techo (T8–T13)

> **schema_version pasa de 1 → 2.** Todos los campos nuevos son **opcionales** y su default
> equivale a **desactivado** (`None`/`enabled=false`), de modo que: (a) un `.azt` v1 se carga sin
> cambios (los campos nuevos toman su default), (b) la **no-regresión** se mantiene — sin tocar nada,
> un clip sale idéntico a hoy. Import de v1 sigue siendo válido; import de v2 en un Azelia viejo NO es
> objetivo (forward-compat no requerida).

## Entidades nuevas (todas opcionales en `ClipTemplate`)

### BrandingSpec (logo / marca de agua) — campo `branding: BrandingSpec | None = None`
| Campo | Tipo | Constraints | Default | Descripción |
|-------|------|-------------|---------|-------------|
| logo_path | str \| None | ruta de archivo PNG/WebP existente bajo el `data_dir` del perfil | None | Imagen del logo (con alpha) |
| position | enum | `top-left`\|`top-right`\|`bottom-left`\|`bottom-right` | `top-right` | Esquina del overlay |
| scale | float | 0.02–0.30 | 0.10 | Ancho del logo como fracción del ancho de salida (1080) |
| opacity | float | 0.0–1.0 | 1.0 | Opacidad del overlay |
| margin | int | 0–200 | 40 | Margen en px desde los bordes |

### ProgressBarSpec — campo `progress_bar: ProgressBarSpec | None = None`
| Campo | Tipo | Constraints | Default | Descripción |
|-------|------|-------------|---------|-------------|
| enabled | bool | — | false | Activa la barra de progreso |
| color | str | ASS ABGR `^&H[0-9A-Fa-f]{8}$` | `&H0000FFFF` | Color de la barra rellena |
| height | int | 2–40 | 12 | Alto de la barra en px |
| position | enum | `top`\|`bottom` | `bottom` | Borde donde se ancla |

### IntroTitleSpec (hook title los primeros N seg) — campo `intro_title: IntroTitleSpec | None = None`
| Campo | Tipo | Constraints | Default | Descripción |
|-------|------|-------------|---------|-------------|
| enabled | bool | — | false | Muestra un título en pantalla al inicio del clip |
| duration_s | float | 1.0–8.0 | 4.0 | Segundos que permanece el título |
| font_name | str | 1–60 chars | hereda `subtitles.font_name` si vacío | Fuente del título |
| font_size | int | 12–200 | 72 | Tamaño del título |
| color | str | ASS ABGR | `&H00FFFFFF` | Color del texto |
| outline_color | str | ASS ABGR | `&H00000000` | Color del contorno |
| position | enum | `top`\|`center`\|`bottom` | `center` | Posición vertical |
| box | bool | — | true | Caja semitransparente detrás del texto |
| delay_captions | bool | — | true | Si true, **los subtítulos no aparecen** hasta que termina el título (`duration_s`) — "el título sale **antes** que los captions" |

> **Texto del título:** proviene de `CuratedClip.title` (ya generado por la curación). El template
> **no** define el texto — solo su estilo, duración y posición. Si `clip.title` está vacío, el título
> no se dibuja aunque `enabled=true` (no se inventa texto).

### BumpersSpec (intro / outro) — campo `bumpers: BumpersSpec | None = None`
| Campo | Tipo | Constraints | Default | Descripción |
|-------|------|-------------|---------|-------------|
| intro_path | str \| None | ruta de un .mp4 bajo el `data_dir` del perfil | None | Clip de intro a concatenar antes |
| outro_path | str \| None | ruta de un .mp4 bajo el `data_dir` del perfil | None | Clip de outro a concatenar después |

> Los bumpers se **normalizan** a 1080×1920 y al codec/fps del clip antes de concatenar (concat por
> re-encode, no demuxer, para tolerar parámetros distintos). Si una ruta no existe → warning no fatal,
> se omite ese bumper.

## Features nuevas

### F7 — Conectar el template al flujo de proceso (completa F6 en el frontend) — **T8**
El backend de F6 ya está; falta el **frontend** y el campo en `ProcessRequest` (TS):
- `web/src/lib/api.ts`: `ProcessRequest.template_id?: string`.
- Selector "Template" en el formulario de subida/proceso (UploadWidget / la ruta real de upload):
  lista `GET /api/templates`, default = `default_template_id` del perfil.
- `SettingsForm.tsx`: control para `default_template_id` (selector de templates del perfil).
- El `template_id` elegido viaja en el `FormData` de `processVideo` y en `processLocalVideo`.

**Done:** elegir un template en upload o fijar el default en Settings hace que el clip renderizado
use ese template (verificable end-to-end con un clip real).

### F8 — Fidelidad de fuentes — **T9**
- Cargar como **web fonts reales** (Google Fonts/`@font-face`) las fuentes ofrecidas en el editor
  (Anton, Bebas Neue, Oswald, Montserrat, Poppins, Impact-alt…), para que el preview no mienta.
- Backend: endpoint/utilidad que reporte qué fuentes están **instaladas en la máquina** (las que el
  render ASS puede honrar); el editor marca visualmente las no instaladas y el guardado emite warning
  `FONT_NOT_INSTALLED` (coherente con import). Sin bloquear.

### F9 — Logo / marca de agua — **T10**
Overlay del `branding.logo_path` vía filtro FFmpeg `overlay` en el paso de burn/compose, en la
esquina/escala/opacidad/margen indicados. Sin branding → sin cambios.

### F10 — Barra de progreso — **T11**
Barra que crece linealmente 0→100% a lo largo del clip, dibujada con `drawbox`/expresión temporal
en el burn. Solo si `progress_bar.enabled`.

### F11 — Hook title (título los primeros N segundos) — **T13**
Dibuja `clip.title` centrado (o top/bottom) durante `intro_title.duration_s` (default 4s) como evento
ASS temporizado (o `drawtext`), con caja opcional. Si `delay_captions=true`, los eventos de subtítulos
se **desplazan** para empezar en `duration_s` (los captions salen **después** del título). Sin
`intro_title` o con `clip.title` vacío → sin cambios.

### F12 — Intro / Outro (bumpers) — **T12**
Concatena `bumpers.intro_path` antes y `bumpers.outro_path` después del clip final, normalizando a
1080×1920 + codec/fps del clip. Rutas ausentes → warning, se omiten.

**Error cases (nuevas) — aplican a F9/F12 (assets en disco):**
| Condición | Comportamiento |
|-----------|----------------|
| `logo_path`/`intro_path`/`outro_path` no existe | Warning no fatal en el job log; se omite ese overlay/bumper (no aborta el render) |
| asset fuera del `data_dir` del perfil (path traversal) | Rechazado en validación del template (no se guarda) |

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
| Claude Code CLI puede no aceptar imágenes en `-p` | Spike temprano; **sin fallback a Anthropic** (decisión local-first/$0): si no hay visión por CC, `VISION_UNAVAILABLE` y el chat sigue en solo-texto |
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

### Done Conditions v2 (T8–T13)
- [ ] **T8** El frontend permite elegir template en upload y fijar `default_template_id` en Settings; el
      clip renderizado usa ese template (verificación end-to-end con un clip real).
- [ ] **T9** El preview del editor usa las fuentes reales (web fonts cargadas); las fuentes no instaladas
      en la máquina se marcan y emiten `FONT_NOT_INSTALLED` al guardar (no bloquean).
- [ ] **T10** Con `branding.logo_path`, el clip final muestra el logo en la esquina/escala/opacidad
      indicadas; sin branding, el render es idéntico al actual (no-regresión).
- [ ] **T11** Con `progress_bar.enabled`, el clip muestra una barra que va 0→100%; desactivada, sin cambios.
- [ ] **T12** Con `bumpers.intro_path`/`outro_path` válidos, el clip final los concatena normalizados;
      rutas ausentes → warning, no aborta.
- [ ] **T13** Con `intro_title.enabled` y `clip.title` no vacío, el clip muestra el título los primeros
      `duration_s` seg y (si `delay_captions`) los subtítulos empiezan después; desactivado, sin cambios.
- [ ] `schema_version=2`: un `.azt` v1 se sigue cargando (campos nuevos toman default = desactivado).
