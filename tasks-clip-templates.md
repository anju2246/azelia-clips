# Tasks: Editor de Templates de Clips con asistente de IA + formato exportable

> Desglose de `spec-clip-templates.md` + `plan-clip-templates.md`. Cada tarea es un **vertical slice**
> end-to-end. Test runner: `pytest`. Marcar `[x]` al cerrar cada tarea.

---

## Task T1: Dominio del template + store por perfil + config
**Status:** [x]
**Complexity:** M
**Dependencies:** none
**Parallelizable with:** none (fundación)

### Description
Crea el modelo de dominio `ClipTemplate` (con `SubtitleSpec`/`LayoutSpec`), los 5 presets built-in
sintetizados desde `STYLES`, el store por perfil con I/O `.azt`, y la config (`templates_dir()`,
`default_template_id`). Es la base que consumen todas las demás tareas. Sin API ni UI todavía.

### Files to Create
- `packages/clips/templates/__init__.py`: exports públicos del módulo.
- `packages/clips/templates/models.py`: `ClipTemplate`, `SubtitleSpec`, `LayoutSpec` (Pydantic v2) con
  todas las constraints del spec; `schema_version=1`; serialización `.azt`.
- `packages/clips/templates/builtins.py`: `list_builtins()`, `get_builtin(slug)` — mapea cada `SubtitleStyle`
  de `STYLES` a `ClipTemplate(is_builtin=True)`.
- `packages/clips/templates/store.py`: `TemplateStore` con `list_all/get/create/update/delete/clone/
  export_bytes/import_bytes/resolve`; excepciones de dominio (`TemplateNotFound`, `TemplateReadOnly`,
  `TemplateInvalid`).
- `tests/test_template_model.py`, `tests/test_template_store.py`.

### Files to Modify
- `packages/core/config.py`: añadir `default_template_id` (Field, alias `DEFAULT_TEMPLATE_ID`, default
  `"splitscreen"`) y helper `templates_dir()` (análogo a `jobs_dir()`).

### Acceptance Criteria
- [ ] `ClipTemplate` valida rangos/enums del spec (font_size 12–200, color ASS `^&H[0-9A-Fa-f]{8}$`,
      animation enum, wide_height_ratio 0.20–0.50, etc.); valores inválidos lanzan `ValidationError`.
- [ ] Round-trip: `ClipTemplate` → bytes `.azt` → `ClipTemplate` produce un objeto equivalente.
- [ ] `list_builtins()` devuelve exactamente los 5 presets (`hormozi, mrbeast, minimal, podcast,
      splitscreen`) con `is_builtin=True`.
- [ ] `store.create/get/update/delete` persisten en `<data_dir>/templates/<slug>.azt`; slug colisionado
      se desambigua (`-2`).
- [ ] `update/delete` sobre un built-in lanza `TemplateReadOnly`.
- [ ] `resolve(None)` devuelve el built-in `splitscreen`; `resolve("inexistente")` lanza `TemplateNotFound`.
- [ ] Tests en `tests/test_template_model.py` y `tests/test_template_store.py` pasan bajo `pytest`.

### TDD Anchors
- `test_clip_template_rejects_out_of_range_font_size`
- `test_clip_template_rejects_invalid_ass_color`
- `test_azt_roundtrip_preserves_fields`
- `test_list_builtins_returns_five_readonly_presets`
- `test_store_create_persists_to_profile_templates_dir`
- `test_store_slug_collision_disambiguates`
- `test_store_update_builtin_raises_readonly`
- `test_store_resolve_none_returns_splitscreen`

---

## Task T2: CRUD API + lista/clonado en UI
**Status:** [x]
**Complexity:** M
**Dependencies:** T1
**Parallelizable with:** none

### Description
Expone el store vía un router FastAPI (`GET/POST/PUT/DELETE /api/templates`, `POST .../clone`) y una UI de
lista en `/dashboard/templates` que permite ver built-ins + custom, crear, clonar y borrar. Sin editor de
campos ni preview todavía (eso es T4).

### Files to Create
- `server/routes/templates.py`: router con CRUD + clone; mapea excepciones de dominio a `{error_code,
  message}` con los HTTP del spec (404 `TEMPLATE_NOT_FOUND`, 409 `TEMPLATE_READONLY`, 422 `TEMPLATE_INVALID`).
- `web/src/pages/dashboard/templates.astro`: página con `DashboardLayout`.
- `web/src/components/templates/TemplatesUI.tsx` + `TemplateList.tsx`.
- `tests/test_templates_endpoints.py`.

### Files to Modify
- `server/app.py`: `app.include_router(templates_router, prefix="/api")`.
- `server/models.py`: `CreateTemplateRequest`, `CloneTemplateRequest`, `TemplateResponse`.
- `web/src/lib/api.ts`: `TemplatesApi` (list/get/create/update/delete/clone) + tipos TS de `ClipTemplate`.
- Navegación del dashboard: enlace a `/dashboard/templates`.

### Acceptance Criteria
- [ ] `GET /api/templates` devuelve built-ins + custom del perfil activo.
- [ ] `POST /api/templates` crea custom; `POST /api/templates/{id}/clone` forkea (incl. built-ins).
- [ ] `PUT`/`DELETE` sobre built-in → 409 `TEMPLATE_READONLY`; sobre id inexistente → 404.
- [ ] Body inválido → 422 `TEMPLATE_INVALID` con detalle por campo.
- [ ] La página `/dashboard/templates` lista los templates y permite crear/clonar/borrar con feedback toast.
- [ ] `tests/test_templates_endpoints.py` (TestClient) cubre los casos de éxito y error; pasa bajo `pytest`.

### TDD Anchors
- `test_get_templates_includes_builtins_and_custom`
- `test_post_template_creates_custom`
- `test_clone_builtin_creates_editable_copy`
- `test_put_builtin_returns_409_readonly`
- `test_delete_missing_returns_404`
- `test_post_invalid_body_returns_422`

---

## Task T3: Aplicar template en el pipeline (default por perfil + override por job)
**Status:** [x]  — backend + plumbing + unit tests. **Verificación manual pendiente** (FFmpeg no es
unit-testable): correr un clip real con (a) sin template → idéntico al actual, (b) template custom
split con otro `wide_height_ratio`, (c) template `fullscreen` (mux de audio nuevo). Usar `/run` o `/verify`.
**Complexity:** L
**Dependencies:** T1
**Parallelizable with:** T2

### Description
Hace que los templates **afecten el render**: setting `default_template_id` por perfil, `template_id` por
job en el upload, y reemplazo del `splitscreen`/`cumulative` hardcodeados en `pipeline.py` por el template
resuelto (subtítulos + layout `wide_height_ratio`). Incluye **test de no-regresión**.

### Files to Modify
- `server/models.py`: `ProcessRequest.template_id: Optional[str]`; `UpdateSettingsRequest`/`SettingsResponse`
  + `default_template_id`.
- `server/routes/clips.py`: `template_id` como `Form(None)`; inyectarlo en el payload del job
  (`template_id or settings.default_template_id`).
- `server/routes/settings.py`: leer/escribir `DEFAULT_TEMPLATE_ID` en GET/POST settings.
- `packages/clips/pipeline.py` (~L676–690): resolver template del payload → mapear `subtitles`→`SubtitleStyle`,
  usar `animation`/`words_per_line`; si `layout.type=="split"` pasar `wide_height_ratio` al reframer.
  Persistir el `template_id` aplicado en el job.
- `web/src/components/.../ProcessForm` y `SettingsForm.tsx`: selector de template (default del perfil).
- `web/src/lib/api.ts`: `ProcessRequest`/settings types + `template_id`/`default_template_id`.

### Files to Create
- `tests/test_pipeline_template.py`.

### Acceptance Criteria
- [ ] **Primero** confirmar la firma real de la función de split en `reframer.py` y cómo se pasa
      `wide_height_ratio` (riesgo del plan); ajustar el plumbing en consecuencia.
- [ ] Procesar con `template_id=None` produce un `SubtitleStyle` **idéntico** al `splitscreen` actual
      (no-regresión) y `wide_height_ratio` por defecto = el layout de hoy.
- [ ] Procesar con un template custom aplica su fuente/colores/animación/words_per_line y su
      `wide_height_ratio` al render.
- [ ] `template_id` inexistente al procesar → 422 `TEMPLATE_NOT_FOUND`.
- [ ] El `template_id` aplicado queda registrado en el job store.
- [ ] `tests/test_pipeline_template.py` pasa bajo `pytest`.

### TDD Anchors
- `test_resolve_default_template_matches_current_splitscreen_style` (no-regresión)
- `test_pipeline_applies_custom_subtitle_style`
- `test_pipeline_split_uses_template_wide_height_ratio`
- `test_process_with_unknown_template_returns_422`
- `test_job_records_applied_template_id`

---

## Task T4: Editor de campos + preview interactivo (mockup)
**Status:** [x]  — lógica de snap/colores con tests puros (esbuild+node). **Verificación visual pendiente**
del drag real en el navegador (`/run` o `npm run dev`).
**Complexity:** L
**Dependencies:** T2
**Parallelizable with:** T3

### Description
Editor de los campos de `subtitles`+`layout` y el **mockup interactivo**: frame de muestra + overlay CSS;
arrastrar el bloque de subtítulos hace *snap* a `alignment`(1–9)+`margin_v`; arrastrar el divisor del split
ajusta `wide_height_ratio` (clamp 0.20–0.50). Guardado vía `PUT` (T2). Frontend-pesado.

### Files to Create
- `web/src/components/templates/TemplateEditor.tsx`.
- `web/src/components/templates/TemplatePreview.tsx` (framer-motion: `drag` + `onDragEnd`).
- `web/src/components/templates/snap.ts`: utilidad pura `pointToAlignment(x,y,box) -> {alignment, margin_v}`
  y `ratioFromDivider(y, height) -> wide_height_ratio`.
- Asset estático de frame de muestra en `web/public/` (o `web/src/assets/`).
- `web/src/components/templates/__tests__/snap.test.ts` (si hay runner JS; si no, validar la lógica de snap
  en una util Python equivalente testeada con pytest — decidir en RED).

### Files to Modify
- `web/src/components/templates/TemplatesUI.tsx`: integrar editor + preview con el template seleccionado.

### Acceptance Criteria
- [ ] El mockup refleja en vivo font/size/colores/alignment/margin_v/animación y la composición del layout.
- [ ] Arrastrar el subtítulo y soltar actualiza `alignment`+`margin_v` (snap a la zona más cercana); el
      formulario y el template reflejan el cambio.
- [ ] En layout `split`, arrastrar el divisor actualiza `wide_height_ratio` clamp [0.20, 0.50].
- [ ] La lógica de snap (`pointToAlignment`, `ratioFromDivider`) tiene tests unitarios que pasan.
- [ ] Guardar persiste vía `PUT /api/templates/{id}` y muestra toast.

### TDD Anchors
- `test_point_to_alignment_snaps_to_nearest_of_nine_zones`
- `test_point_to_alignment_computes_margin_v`
- `test_ratio_from_divider_clamps_to_valid_range`

---

## Task T5: Chat de IA (texto) para editar el template
**Status:** [x]
**Complexity:** M
**Dependencies:** T2, T4
**Parallelizable with:** none

### Description
`ai_editor` + endpoint `POST /api/templates/chat` (solo texto) + UI de chat. El modelo recibe el draft +
esquema/constraints y devuelve `{explanation, template}` validado; 1 reintento si falla; la UI aplica el
patch al draft y refresca el preview. No persiste (guardado explícito vía T2).

### Files to Create
- `packages/clips/templates/ai_editor.py`: `edit(template, messages, image_path=None)`; system prompt con
  esquema/constraints; parseo + validación Pydantic + 1 reintento; devuelve `provider_used`.
- `tests/test_templates_chat.py` (LLM mockeado).

### Files to Modify
- `server/routes/templates.py`: `POST /api/templates/chat`; 503 `LLM_UNAVAILABLE`, 502 `LLM_BAD_OUTPUT`.
- `server/models.py`: `TemplateChatRequest`/`TemplateChatResponse`.
- `web/src/components/templates/TemplateChat.tsx` + `TemplatesUI.tsx`; `api.ts` `TemplatesApi.chat`.

### Acceptance Criteria
- [ ] Con LLM mockeado devolviendo JSON válido, el endpoint responde `{explanation, template, provider_used}`
      y el template respeta las constraints.
- [ ] Salida no-parseable/ inválida → reintento; si vuelve a fallar → 502 `LLM_BAD_OUTPUT`.
- [ ] Sin proveedor LLM → 503 `LLM_UNAVAILABLE`.
- [ ] La UI de chat aplica el template devuelto al draft y refresca el preview.
- [ ] `tests/test_templates_chat.py` pasa bajo `pytest`.

### TDD Anchors
- `test_chat_returns_validated_template`
- `test_chat_retries_then_raises_on_invalid_output`
- `test_chat_no_provider_returns_503`

---

## Task T6: Imagen de referencia (visión) — Claude Code only (SIN fallback Anthropic)
**Status:** [x]  — spike confirmado (`claude -p --allowedTools Read` lee imágenes). Visión exclusiva por
Claude Code por decisión local-first/$0. **Verificación manual pendiente:** flujo real de replicar un
template desde una imagen en el navegador.
**Complexity:** L
**Dependencies:** T5
**Parallelizable with:** none

### Description
Añade visión a la capa LLM y la conecta al chat cuando hay imagen adjunta. **Empieza con el spike**:
verificar si `claude -p` lee imágenes referenciando ruta absoluta; si no, CC queda como sin-visión y se usa
Anthropic API (base64). Si ningún proveedor con visión → `VISION_UNAVAILABLE` y el chat sigue en texto.

### Files to Modify
- `packages/core/llm_provider.py`: `vision_available()` y `chat_vision(system, user, image_path, ...)`
  (claude_code con ruta temporal → fallback anthropic con bloque `image` base64).
- `packages/clips/templates/ai_editor.py`: usar `chat_vision` cuando hay `image_path`.
- `server/routes/templates.py`: `POST /api/templates/chat` acepta imagen (base64/multipart); validar
  tipo (`png/jpeg/webp`) y tamaño (≤5MB); archivo temporal con borrado garantizado; 422 `VISION_UNAVAILABLE`
  / `IMAGE_INVALID`.
- `web/src/components/templates/TemplateChat.tsx`: adjuntar imagen; deshabilitar si `vision_available` es
  falso (exponer un flag vía `GET /api/templates` meta o un endpoint de capacidades).
- `tests/test_templates_chat.py`: casos de visión.

### Acceptance Criteria
- [ ] Spike documentado: ¿`claude -p` acepta imágenes? Resultado reflejado en `vision_available()`.
- [ ] Con imagen y un proveedor de visión (mockeado), el chat la usa y devuelve template válido.
- [ ] Imagen sin proveedor de visión → 422 `VISION_UNAVAILABLE`; el chat de texto sigue operativo.
- [ ] Imagen de tipo/tamaño inválido → 422 `IMAGE_INVALID`.
- [ ] El archivo temporal de la imagen se borra siempre (incluso ante excepción).
- [ ] Tests de visión en `tests/test_templates_chat.py` pasan bajo `pytest`.

### TDD Anchors
- `test_vision_uses_anthropic_when_cc_unsupported`
- `test_image_without_vision_provider_returns_422`
- `test_invalid_image_type_returns_422`
- `test_temp_image_deleted_after_call`

---

## Task T7: Import / Export `.azt`
**Status:** [x]
**Complexity:** M
**Dependencies:** T2
**Parallelizable with:** T4, T5

### Description
Cierra el formato marketplace: exportar un template como archivo `.azt` descargable e importar uno externo
validando `schema_version` y esquema, guardándolo como custom (slug desambiguado, `is_builtin=false`).
Warning no-fatal si la fuente no está instalada.

### Files to Modify
- `server/routes/templates.py`: `GET /api/templates/{id}/export` (descarga JSON) y
  `POST /api/templates/import` (multipart); 422 `IMPORT_PARSE_ERROR` / `IMPORT_VERSION_UNSUPPORTED`;
  respuesta con `warnings` (`FONT_NOT_INSTALLED`).
- `packages/clips/templates/store.py`: `export_bytes`/`import_bytes` (ya stubs en T1) — implementar
  validación de versión, reasignación de slug, `is_builtin=false`, detección de fuente instalada.
- `web/src/components/templates/TemplateList.tsx`: botones Importar/Exportar; `api.ts` export/import.
- `tests/test_templates_endpoints.py`: casos import/export.

### Acceptance Criteria
- [ ] Round-trip HTTP: exportar un template e importarlo produce un template equivalente (nuevo slug).
- [ ] Import de `schema_version` desconocida → 422 `IMPORT_VERSION_UNSUPPORTED`.
- [ ] Import de archivo no-JSON → 422 `IMPORT_PARSE_ERROR`.
- [ ] Import fuerza `is_builtin=false` e ignora el `id` entrante.
- [ ] Import con fuente ausente responde 200 con `warnings: [FONT_NOT_INSTALLED]` (no fatal).
- [ ] Tests de import/export pasan bajo `pytest`.

### TDD Anchors
- `test_export_import_roundtrip_creates_equivalent_template`
- `test_import_unknown_schema_version_returns_422`
- `test_import_non_json_returns_422`
- `test_import_forces_is_builtin_false_and_new_slug`
- `test_import_missing_font_returns_warning_not_error`

---

---

# v2 — Conectar + Ampliar el techo (T8–T13)

> Deriva de las secciones "v2 Extensions" de `spec-clip-templates.md`. T8 y T9 **completan** spec ya
> aprobado (sin nueva firma). T10–T13 son **scope nuevo** (schema_version 2) y requieren la firma de
> JuanPa antes de implementar.

## Task T8: Conectar template_id al flujo de proceso (frontend) + verificación E2E
**Status:** [x]  — frontend + backend hardening + tests. **Verificación E2E manual pendiente** (clip real).
**Complexity:** M
**Dependencies:** T2, T3 (backend ya listo)
**Parallelizable with:** none (crítico — desbloquea el valor de todo el feature)

### Description
El backend ya acepta `template_id` por job y `default_template_id` por perfil. Falta el **frontend**:
exponer `template_id` en `ProcessRequest` (TS), un **selector de Template** en el flujo de upload/proceso
(default = el del perfil) y un control de `default_template_id` en `SettingsForm`. Cierra el hueco que
hacía el feature "inútil": diseñas un template y por fin se aplica al clip.

### Files to Modify
- `web/src/lib/api.ts`: `ProcessRequest.template_id?: string`; asegurar que `processVideo`/`processLocalVideo`
  lo envían (ya forwardea `req`, pero verificar y tipar). `UpdateSettingsRequest.default_template_id?: string`.
- Componente real de upload/proceso (`web/src/components/dashboard/UploadWidget.tsx` y/o
  `web/src/components/workflow/DashboardController.tsx`): selector "Template" poblado con `TemplatesApi.list()`,
  default = `settings.default_template_id`.
- `web/src/components/settings/SettingsForm.tsx`: selector `default_template_id` (lista de templates del perfil).

### Files to Create
- `web/tests/e2e/templates-apply.spec.ts` *(o)* un test de integración del flujo de selección si Playwright
  no es viable hoy; mínimo: un test que confirme que `processVideo(file, {template_id})` mete `template_id`
  en el `FormData`.

### Acceptance Criteria
- [ ] `ProcessRequest` incluye `template_id`; al procesar con un template elegido, el `FormData` lo envía.
- [ ] El formulario de upload muestra el selector de Template con el default del perfil preseleccionado.
- [ ] `SettingsForm` permite ver/guardar `default_template_id`; persiste vía `POST /api/settings`.
- [ ] **Verificación E2E manual** (`/run` o `/verify`): procesar un clip real con un template custom (p.ej.
      `wide_height_ratio` distinto o `fullscreen`) produce un clip visiblemente distinto al default.
- [ ] Build del front verde (`npm run build`).

### TDD Anchors
- `test_process_request_serializes_template_id` (FormData incluye template_id)
- `test_settings_form_roundtrips_default_template_id`

---

## Task T9: Fidelidad de fuentes (web fonts reales + fuentes instaladas)
**Status:** [x]
**Complexity:** M
**Dependencies:** T8
**Parallelizable with:** T10

### Description
El editor ofrece fuentes que el preview no carga (muestra una sans genérica) y que la máquina puede no
tener instaladas (el render ASS también cae a fallback). Cargar web fonts reales en el editor y reportar
qué fuentes están instaladas para no prometer lo que el render no honra.

### Files to Modify
- `web/src/layouts/DashboardLayout.astro` (y/o un `@font-face` dedicado): cargar Anton, Bebas Neue, Oswald,
  Montserrat, Poppins, etc. usadas en `FONTS` del editor.
- `web/src/components/templates/TemplateEditorModal.tsx`: marcar fuentes no instaladas (badge) usando la
  capability del backend; warning al guardar si `font_name` no instalada.
- `server/routes/templates.py` *(o `settings.py`)*: exponer `installed_fonts` (o un check por nombre).

### Files to Create
- `packages/clips/templates/fonts.py`: `is_font_installed(name)` / `list_installed_fonts()` (vía `fc-list`
  en Linux/mac o fallback por carpetas de fuentes); `tests/test_template_fonts.py`.

### Acceptance Criteria
- [ ] El preview del editor renderiza con la fuente seleccionada (web font cargada), no una fallback.
- [ ] `list_installed_fonts()` detecta fuentes del sistema; `is_font_installed("Arial")` razonable por OS.
- [ ] El editor marca visualmente fuentes no instaladas y emite `FONT_NOT_INSTALLED` al guardar (no bloquea).
- [ ] `tests/test_template_fonts.py` pasa.

### TDD Anchors
- `test_list_installed_fonts_returns_known_system_font`
- `test_is_font_installed_false_for_made_up_name`

---

## Task T10: Logo / marca de agua (branding overlay FFmpeg)  — **scope nuevo (firma)**
**Status:** [x]  — modelo + builder FFmpeg puro + API + upload de logo + editor + tests. **Verificación visual pendiente** (clip real).
**Complexity:** M
**Dependencies:** T1 (modelo), T3 (pipeline)
**Parallelizable with:** T9, T11

### Description
Añadir `BrandingSpec` al modelo (opcional, default None → no-regresión) y aplicar el logo como overlay
FFmpeg en el compose/burn, en la esquina/escala/opacidad/margen indicados. Validar que `logo_path` está
dentro del `data_dir` del perfil (anti path-traversal).

### Files to Modify
- `packages/clips/templates/models.py`: `BrandingSpec` + `branding` opcional; `SCHEMA_VERSION=2`.
- `packages/clips/templates/render.py`: incluir branding en el `RenderPlan`.
- `packages/clips/pipeline.py`: aplicar overlay del logo en el burn (o paso de compose) si hay branding.
- `packages/clips/templates/builtins.py`: builtins con `branding=None` (sin cambios visuales).

### Files to Create
- `tests/test_template_branding.py`.

### Acceptance Criteria
- [ ] `BrandingSpec` valida posición/escala/opacidad/margen; `logo_path` fuera del data_dir → ValidationError.
- [ ] El `RenderPlan` traslada branding; el comando FFmpeg incluye un `overlay` cuando hay logo.
- [ ] Sin branding → comando/render idéntico al actual (no-regresión, test).
- [ ] `schema_version=2` y un `.azt` v1 (sin branding) se carga con `branding=None`.
- [ ] `tests/test_template_branding.py` pasa.

### TDD Anchors
- `test_branding_rejects_path_outside_profile`
- `test_render_plan_includes_overlay_when_logo_present`
- `test_no_branding_keeps_render_command_unchanged`
- `test_v1_azt_loads_with_branding_none`

---

## Task T11: Barra de progreso (drawbox time-based)  — **scope nuevo (firma)**
**Status:** [x]  — modelo + drawbox temporal + color ASS→FFmpeg + API + editor + tests. **Verificación visual pendiente**.
**Complexity:** M
**Dependencies:** T1, T3
**Parallelizable with:** T10

### Description
`ProgressBarSpec` (opcional, `enabled=false` por defecto) y una barra que crece 0→100% a lo largo del clip
vía `drawbox` con expresión temporal (`w*t/dur`) en el burn. Color/alto/posición configurables.

### Files to Modify
- `packages/clips/templates/models.py`: `ProgressBarSpec` + `progress_bar` opcional.
- `packages/clips/templates/render.py` + `pipeline.py`: inyectar el `drawbox` cuando `enabled`.

### Files to Create
- `tests/test_template_progressbar.py`.

### Acceptance Criteria
- [ ] `ProgressBarSpec` valida color ASS/alto/posición.
- [ ] Con `enabled`, el filtro incluye un `drawbox` con ancho dependiente del tiempo; sin él, no se añade.
- [ ] Color ASS → BGR/hex correcto para FFmpeg (no confundir orden de bytes).
- [ ] `tests/test_template_progressbar.py` pasa.

### TDD Anchors
- `test_progress_bar_disabled_adds_no_filter`
- `test_progress_bar_filter_width_is_time_dependent`
- `test_ass_color_to_ffmpeg_hex_byte_order`

---

## Task T12: Intro / Outro (bumpers, concat)  — **scope nuevo (firma)**
**Status:** [ ]
**Complexity:** L
**Dependencies:** T1, T3
**Parallelizable with:** none (toca el final del render)

### Description
`BumpersSpec` (opcional) con `intro_path`/`outro_path`; concatenar normalizando a 1080×1920 + codec/fps del
clip (concat por re-encode). Rutas ausentes → warning, se omiten (no aborta).

### Files to Modify
- `packages/clips/templates/models.py`: `BumpersSpec` + `bumpers` opcional (rutas validadas dentro del data_dir).
- `packages/clips/pipeline.py`: tras el burn, si hay bumpers válidos, normalizar y concatenar.

### Files to Create
- `packages/clips/templates/bumpers.py`: helper puro que arma el plan de concat (lista ordenada de inputs +
  flag de re-encode) — testeable sin ejecutar FFmpeg.
- `tests/test_template_bumpers.py`.

### Acceptance Criteria
- [ ] Sin bumpers → no hay paso de concat (no-regresión).
- [ ] Con intro+outro válidos, el plan de concat es `[intro, clip, outro]` normalizados.
- [ ] Ruta inexistente → se omite con warning, no aborta; el plan conserva los presentes.
- [ ] `bumpers` con ruta fuera del data_dir → ValidationError.
- [ ] `tests/test_template_bumpers.py` pasa.

### TDD Anchors
- `test_no_bumpers_no_concat_step`
- `test_concat_plan_orders_intro_clip_outro`
- `test_missing_bumper_path_skipped_with_warning`

---

## Task T13: Hook title (título los primeros N segundos antes de los captions)  — **scope nuevo (firma)**
**Status:** [x]  — render + API + editor + tests. **Verificación visual pendiente** (clip real).
**Complexity:** L
**Dependencies:** T1, T3
**Parallelizable with:** T10, T11

### Description
`IntroTitleSpec` (opcional, `enabled=false`). Dibuja `clip.title` (de la curación) centrado/top/bottom
durante `duration_s` (default 4s) como evento ASS temporizado con caja opcional. Si `delay_captions=true`,
desplazar los eventos de subtítulos para que **empiecen después** del título (el título sale antes que los
captions). `clip.title` vacío → no se dibuja aunque esté `enabled`.

### Files to Modify
- `packages/clips/templates/models.py`: `IntroTitleSpec` + `intro_title` opcional.
- `packages/clips/subtitles/generator.py`: (a) método para emitir el evento de título temporizado;
  (b) opción de **offset** de los subtítulos (`start_at`) cuando `delay_captions`.
- `packages/clips/pipeline.py`: pasar `clip.title` + `intro_title` al generador.

### Files to Create
- `tests/test_template_intro_title.py`.

### Acceptance Criteria
- [ ] Con `enabled` y `clip.title` no vacío, el `.ass` contiene un `Dialogue` del título con fin = `duration_s`.
- [ ] Con `delay_captions=true`, el primer subtítulo de palabras empieza ≥ `duration_s`.
- [ ] `clip.title` vacío → no se emite evento de título (aunque `enabled`).
- [ ] Desactivado → `.ass` idéntico al actual (no-regresión).
- [ ] `tests/test_template_intro_title.py` pasa.

### TDD Anchors
- `test_intro_title_emitted_with_duration`
- `test_empty_clip_title_emits_no_intro`
- `test_delay_captions_offsets_first_subtitle`
- `test_intro_title_disabled_keeps_ass_unchanged`

---

## Critical path
v1: `T1 → T3` (template afecta el render). v2: **`T8` es el nuevo crítico** — sin el frontend, todo el
feature es inútil; va primero. Luego `T9` (fidelidad). Expansiones (scope nuevo, tras firma):
`T10 ∥ T11 ∥ T13` (independientes), `T12` al final (toca el cierre del render). Orden por valor:
T8 → T9 → T13 (hook title) → T10 (logo) → T11 (barra) → T12 (bumpers).
