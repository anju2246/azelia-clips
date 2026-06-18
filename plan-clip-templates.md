# Plan: Editor de Templates de Clips con asistente de IA + formato exportable

> Arquitectura para `spec-clip-templates.md` (Approved). Local-first, multi-perfil, MIT.

## Tech Stack
| Concern | Choice | Rationale | Alternativas rechazadas |
|---------|--------|-----------|-------------------------|
| Modelo de datos | Pydantic v2 (`ClipTemplate`) | Ya es el estándar del repo (Settings, ProcessRequest, CuratedClip); validación declarativa = constraints del spec gratis | dataclasses (sin validación), JSON Schema crudo |
| Persistencia | Archivos `.azt` (JSON) bajo `<data_dir>/templates/` | Coherente con local-first y multi-perfil; un archivo = una unidad exportable para el marketplace; sin DB nueva | SQLite (overkill, no portable), un solo `templates.json` (peor para export individual) |
| API | FastAPI router nuevo `server/routes/templates.py` | Mismo patrón que profiles/settings (`include_router(prefix="/api")`) | GraphQL (innecesario) |
| LLM | Extender `MultiProviderLLM` con visión | Reusa el router/orden de proveedores y el aislamiento por perfil ya existente | Cliente Anthropic separado (duplicaría la lógica de fallback) |
| Frontend | Astro page + React (`TemplatesUI.tsx`) | Igual que `settings.astro` + `SettingsForm.tsx` | SPA aparte (rompe la convención) |
| Drag/preview | `framer-motion` (ya instalado) + lógica de snap en TS | Evita dependencia nueva; drag con `drag`/`onDragEnd` | dnd-kit/react-dnd (instalar lib nueva para un caso simple) |
| Tests | pytest + FastAPI `TestClient` | Igual que `test_*_endpoints.py` existentes | — |

## Component Architecture

### Backend

#### `packages/clips/templates/models.py` (dominio)
- **Responsabilidad:** definir `ClipTemplate`, `SubtitleSpec`, `LayoutSpec` (Pydantic) con todas las
  constraints del spec; (de)serialización `.azt`; `schema_version`.
- **Interface:** modelos puros, sin dependencias de FastAPI ni de disco.
- **Dependencias:** ninguna del repo (capa de dominio limpia).

#### `packages/clips/templates/builtins.py`
- **Responsabilidad:** sintetizar los 5 presets como `ClipTemplate(is_builtin=True)` a partir del dict
  `STYLES` de `subtitles/generator.py` (`SubtitleStyle` → `SubtitleSpec`).
- **Interface:** `list_builtins() -> list[ClipTemplate]`, `get_builtin(slug) -> ClipTemplate | None`.
- **Dependencias:** `models.py`, `subtitles/generator.py` (solo lectura del dict).

#### `packages/clips/templates/store.py`
- **Responsabilidad:** I/O por perfil sobre `<data_dir>/templates/`. CRUD de custom + merge con built-ins.
  Resolución de slug, desambiguación, validación al cargar.
- **Interface:** `list_all()`, `get(id)`, `create(t)`, `update(id, t)`, `delete(id)`, `clone(id, name)`,
  `export_bytes(id)`, `import_bytes(data)`, `resolve(id|None) -> ClipTemplate` (con fallback al default).
- **Dependencias:** `models.py`, `builtins.py`, `settings.templates_dir()` (config).
- **Reglas:** built-ins nunca se escriben a disco; editar/borrar un built-in → excepción de dominio.

#### `packages/clips/templates/ai_editor.py`
- **Responsabilidad:** orquestar el chat de IA. Construye system prompt con el esquema + constraints,
  llama al LLM (texto o visión), parsea/valida la salida `{explanation, template}`, reintenta 1 vez.
- **Interface:** `edit(template, messages, image_path|None) -> {explanation, template, provider_used}`.
- **Dependencias:** `models.py`, `packages/core/llm_provider.py`.

#### `packages/core/llm_provider.py` (extensión)
- **Añadir:** `chat_vision(system, user, image_path, ...) -> str` y `vision_available() -> bool`.
  - claude_code: guardar imagen en archivo temporal y referenciar su **ruta absoluta** en el prompt
    (**spike**: confirmar que `claude -p` la lee; si no, marcar CC como sin-visión).
  - anthropic: bloque de contenido `image` (base64) en `messages` (camino garantizado, requiere API key).
  - Fallback: si claude_code no soporta/ falla → anthropic; si ninguno → señal de "sin visión".

#### `server/routes/templates.py`
- **Responsabilidad:** endpoints HTTP (F1–F4). Traduce excepciones de dominio a códigos del spec.
- **Endpoints:** `GET /api/templates`, `GET /api/templates/{id}`, `POST /api/templates`,
  `PUT /api/templates/{id}`, `DELETE /api/templates/{id}`, `POST /api/templates/{id}/clone`,
  `GET /api/templates/{id}/export`, `POST /api/templates/import`, `POST /api/templates/chat`.
- **Dependencias:** `store.py`, `ai_editor.py`, `Depends(require_onboarding)` (mismo auth que clips).

#### `server/models.py` (extensión)
- DTOs de request/response (`CreateTemplateRequest`, `TemplateChatRequest`, etc.) que envuelven
  `ClipTemplate`. `ProcessRequest` gana `template_id: Optional[str]`. `UpdateSettingsRequest`/
  `SettingsResponse` ganan `default_template_id`.

#### `packages/core/config.py` (extensión)
- `default_template_id: str = Field(default="splitscreen", alias="DEFAULT_TEMPLATE_ID")`.
- Helper `templates_dir()` análogo a `jobs_dir()` (`self.data_dir / "templates"`, `mkdir`).

#### `packages/clips/pipeline.py` (modificación — el corazón del valor)
- Reemplazar el `SubtitleGenerator(style='splitscreen')` + `animation='cumulative'` hardcodeados (~L687):
  resolver `template_id` (del job/payload) → `store.resolve()` → mapear `subtitles`→`SubtitleStyle`,
  pasar `animation`/`words_per_line`, y si `layout.type == "split"` pasar `wide_height_ratio` al reframer.
- Persistir el `template_id` aplicado en el job store (trazabilidad).

### Frontend

#### `web/src/pages/dashboard/templates.astro` + `web/src/components/templates/TemplatesUI.tsx`
- **Responsabilidad:** lista de templates (built-in/custom), editor de campos, chat, **mockup interactivo**.
- **Sub-componentes:**
  - `TemplateList.tsx` — listar/seleccionar/clonar/borrar/importar/exportar.
  - `TemplateEditor.tsx` — formulario de `subtitles` + `layout`.
  - `TemplateChat.tsx` — chat + adjuntar imagen (deshabilitado si no hay visión).
  - `TemplatePreview.tsx` — mockup: frame de muestra + overlay CSS; drag del subtítulo (snap a
    `alignment`+`margin_v`) y drag del divisor del split (`wide_height_ratio`), vía framer-motion.
- **Estado:** hooks locales (`useState`/`useEffect`/`useCallback`), `react-hot-toast` para feedback.

#### `web/src/lib/api.ts` (extensión)
- `TemplatesApi` (list/get/create/update/delete/clone/export/import/chat) sobre el `fetchApi` existente.
- Tipos TS de `ClipTemplate` espejando el modelo Pydantic.

#### Upload + Settings (modificación)
- Formulario de procesamiento: selector "Template" (default = `default_template_id`); manda `template_id`.
- `SettingsForm.tsx`: selector de template default del perfil.

## Dependency Map
```
models.py  ←  builtins.py  ←  store.py  ←  routes/templates.py  →  ai_editor.py  →  llm_provider.py
   ↑                              ↑                                                      
config.py (templates_dir,        pipeline.py (resolve + aplica)                          
  default_template_id)           clips.py (template_id en ProcessRequest)                

Frontend:  api.ts ← TemplatesUI (List/Editor/Chat/Preview)
           ProcessForm/SettingsForm → api.ts
```
(flechas = "usa / depende de"; sin ciclos: dominio `models.py` no depende de nada del repo.)

## Cross-Cutting Concerns

### Autenticación
Single-user localhost. Las rutas de templates usan el mismo `Depends(require_onboarding)` que `clips.py`.
Sin cambios al modelo de auth.

### Error handling
Excepciones de dominio en `store.py`/`ai_editor.py` (`TemplateNotFound`, `TemplateReadOnly`,
`TemplateInvalid`, `VisionUnavailable`, `LLMBadOutput`). La capa de ruta las mapea a `HTTPException`
con cuerpo `{error_code, message}` según la tabla de cada feature del spec. La capa de dominio nunca
expone stack traces.

### Configuración / aislamiento por perfil
Todo se resuelve contra `settings.data_dir` (perfil activo). `templates_dir()` crea el dir on-demand.
`default_template_id` se persiste en `secrets.env` del perfil (igual que el resto de settings).

### Logging / observabilidad
Reusar el `Console` de rich ya presente; loguear proveedor LLM usado (texto/visión), import con warnings
(`FONT_NOT_INSTALLED`), y el `template_id` aplicado por job.

### Seguridad
Imagen adjunta → archivo temporal con borrado garantizado (`finally`/context manager) tras la llamada.
Import valida esquema y `schema_version`; **no** ejecuta nada del archivo; fuerza `is_builtin=false` y
reasigna slug (no confía en el `id` entrante). Sin secretos en los `.azt`.

## Architectural Risks
| Riesgo | Likelihood | Impacto | Mitigación |
|--------|-----------|---------|------------|
| `claude -p` no acepta imágenes | Media | Medio | Spike temprano (Task de visión primero verifica); Anthropic API es el camino garantizado; degradar a solo-texto con `VISION_UNAVAILABLE` |
| Firma real del split en `reframer.py` distinta a lo asumido (`wide_height_ratio`) | Media | Medio | Tarea de layout empieza leyendo la firma real y testea que default 0.32 = output idéntico al actual |
| Salida JSON del LLM inválida | Media | Bajo | Validación Pydantic + 1 reintento con corrección; `LLM_BAD_OUTPUT` si persiste |
| Fidelidad mockup CSS vs render FFmpeg | Media | Bajo | Drag limitado a `alignment`+`margin_v` (lo reproducible por ASS); documentar "aproximado" |
| Fuente referenciada ausente en otra máquina | Alta | Bajo | `warnings` no-fatales en import; render usa fallback de fuente del sistema |
| Regresión visual en clips existentes | Baja | Alto | Default = built-in `splitscreen`; test de pipeline que verifica que sin `template_id` el `SubtitleStyle` resultante == el `splitscreen` de hoy |
| `schema_version` futuro | Baja | Bajo | Validar versión en import; rechazo explícito de versiones desconocidas |

## Directory Structure
```
packages/clips/templates/           # NUEVO módulo de dominio
├── __init__.py
├── models.py        # ClipTemplate, SubtitleSpec, LayoutSpec (Pydantic)
├── builtins.py      # 5 presets desde STYLES → ClipTemplate(is_builtin=True)
├── store.py         # CRUD + .azt I/O + resolve() por perfil
└── ai_editor.py     # chat IA: prompt + validación + reintento

packages/core/
├── config.py        # + default_template_id, templates_dir()
└── llm_provider.py  # + chat_vision(), vision_available()

server/
├── routes/templates.py   # NUEVO router (CRUD + import/export + chat)
├── routes/clips.py       # + template_id en /process
├── routes/settings.py    # + default_template_id en GET/POST
├── models.py             # + DTOs templates, ProcessRequest.template_id, settings
└── app.py                # + include_router(templates_router, prefix="/api")

packages/clips/pipeline.py # resolve template y aplica (reemplaza hardcode)

web/src/
├── pages/dashboard/templates.astro     # NUEVA página
├── components/templates/               # NUEVO
│   ├── TemplatesUI.tsx
│   ├── TemplateList.tsx
│   ├── TemplateEditor.tsx
│   ├── TemplateChat.tsx
│   └── TemplatePreview.tsx             # mockup interactivo (framer-motion)
├── lib/api.ts                          # + TemplatesApi + tipos
└── components/settings/SettingsForm.tsx# + selector default template

tests/
├── test_template_model.py       # validación/constraints + round-trip .azt
├── test_template_store.py       # CRUD, builtins read-only, resolve/fallback
├── test_templates_endpoints.py  # rutas CRUD + import/export + clone (TestClient)
├── test_templates_chat.py       # chat texto/visión (LLM mockeado)
└── test_pipeline_template.py    # pipeline aplica template; default == splitscreen actual
```

## Sequencing Rationale (vertical slices)
Orden por valor y dependencia, cada slice end-to-end:
1. **Dominio + store** (`models`, `builtins`, `store`, `templates_dir`) — fundación que todo lo demás usa.
2. **CRUD API + lista en UI** — crear/listar/clonar/borrar visibles; valor inmediato sin pipeline.
3. **Aplicar template al pipeline** (`default_template_id`, `ProcessRequest.template_id`, cambio en
   `pipeline.py`) — el corazón: los templates afectan el output. Incluye test de no-regresión.
4. **Editor + preview interactivo** (formulario + mockup + drag snap + divisor split).
5. **Chat IA (texto)** — `ai_editor` + endpoint + UI chat.
6. **Visión (imagen de referencia)** — spike CC CLI + fallback Anthropic; va tras el chat texto porque
   reusa toda su tubería.
7. **Import/Export `.azt`** — cierra el formato marketplace; depende del modelo ya estable.

Crítico: slices 1→3 forman el camino crítico (sin ellos no hay feature). 4–7 son incrementos de valor.
```
