# Plan: Multi-perfil de podcasts + selección de Claude Code por perfil

## Tech Stack
| Concern | Choice | Rationale | Alternativas rechazadas |
|---------|--------|-----------|-------------------------|
| Registry de perfiles | JSON plano `~/.azelia/profiles.json` | Global a la máquina, fuera de cualquier data_dir; legible/editable a mano; cero deps | SQLite (otra DB global solo para esto = overkill); dir scanning sin registry (no guarda puntero activo ni binding de Claude) |
| Aislamiento | 1 carpeta por perfil bajo `~/.azelia/profiles/<slug>/` | Reusa el patrón `AZELIA_DATA_DIR` ya existente; todo lo que deriva de `settings.data_dir` queda aislado sin tocar call-sites | Namespacing por `profile_id` en DB compartida (riesgo de fuga, hay que filtrar cada query) |
| Switch | Reinicio vía sentinel `.restart` + exit 42 | Mecanismo **ya existente y probado** (self-update); arranque limpio, sin estado compartido entre perfiles | Hot-reload de singletons (settings/llm/job_store) = frágil y fuera de scope |
| Identidad de cuenta Claude | Leer `oauthAccount.emailAddress` del `.claude.json` autoritativo | Verificado en máquina real; identifica cuentas por email en vez de rutas | Parsear salida de la CLI (no hay comando de status estable) |
| Detección de binario | `which -a` + rutas comunes + dedupe por `realpath` | Verificado: colapsa PATH/npm/homebrew al mismo binario | Solo PATH (se pierden installs fuera de PATH) |

## Component Architecture

### `packages/core/profiles.py` (NUEVO) — dominio + repositorio
- **Responsabilidad:** modelo `Profile`, lectura/escritura atómica del registry, `slugify`, migración del árbol legacy, resolución del perfil activo y de su `data_dir`/`claude_binary`/`claude_config_dir`.
- **Interfaz:**
  - `ProfileManager(azelia_home: Path)` — home resuelto vía `AZELIA_HOME` env (default `~/.azelia`).
  - `.ensure_initialized() -> None` (idempotente; corre migración F9 si falta el registry)
  - `.list() -> list[Profile]` · `.active() -> Profile` · `.get(id) -> Profile|None`
  - `.create(name, claude_binary=None, claude_config_dir=None) -> Profile`
  - `.update(id, **fields) -> Profile` · `.delete(id, delete_data=False) -> None`
  - `.set_active(id) -> None` (solo escribe el registry; el reinicio lo dispara la ruta)
  - `.active_data_dir() -> Path` (lo consume `config.py`)
- **Dependencias:** solo `pathlib`, `json`, `shutil`, `re`. **NO importa `config.py`** (evita ciclo: config→profiles).

### `packages/core/claude_detect.py` (NUEVO) — detección (capa boundary)
- **Responsabilidad:** descubrir binarios y cuentas de Claude Code; validar uno manual.
- **Interfaz:**
  - `detect_installations() -> list[ClaudeInstallation]` (PATH `which -a`, `~/.claude/local`, npm prefix, homebrew; dedupe por realpath; `--version` timeout 3s; nombres `claude`/`claude.exe`/`claude.cmd`)
  - `detect_accounts(extra_config_dirs: list[Path]) -> list[ClaudeAccount]`
  - `read_account(config_dir: Path|None) -> ClaudeAccount` (regla de archivo autoritativo: default ⇒ `~/.claude.json`; custom ⇒ `<dir>/.claude.json`, sin fallback)
  - `validate(path: Path|None, config_dir: Path|None) -> dict`
- **Dependencias:** `subprocess`, `shutil`, `json`, `pathlib`. Sin estado.

### `packages/core/config.py` (MODIFICAR)
- `_default_data_dir()`: si `AZELIA_DATA_DIR` está seteado ⇒ respeta override (perfil in-place). Si no ⇒ `ProfileManager(...).ensure_initialized()` + `.active_data_dir()`.
- Nuevos campos en `Settings`: `claude_binary: str|None`, `claude_config_dir: str|None`, poblados desde el perfil activo (no desde env).

### `packages/core/llm_provider.py` (MODIFICAR)
- `claude_code_available()`, `claude_code_authenticated()`, `_call_claude_code()`: usar `settings.claude_binary or "claude"` como ejecutable y, si `settings.claude_config_dir`, pasar `env={**os.environ, "CLAUDE_CONFIG_DIR": settings.claude_config_dir}` en cada `subprocess.run`.

### `server/routes/profiles.py` (NUEVO) — capa presentación
- Endpoints F1–F7 (`/api/profiles*`, `/api/claude/installations`, `/api/claude/validate`).
- Reusa `require_auth`, `ProfileManager`, `claude_detect`, `has_active_jobs()` y el sentinel `.restart`.
- `activate`: valida no-jobs → `set_active` → `touch(settings.data_dir/".restart")` → `{"status":"restarting"}`.

### `server/workers/job_store.py` o `server/services/jobs_guard.py` (MODIFICAR/NUEVO)
- Extraer `has_active_jobs() -> tuple[bool, list[str]]` (hoy embebido en `system.py:120`) para reuso por `system.py` y `profiles.py`. Devuelve también los IDs (el spec pide listarlos en el 409).

### `server/models.py` (MODIFICAR)
- `ProfileResponse`, `CreateProfileRequest`, `UpdateProfileRequest`, `ClaudeInstallationResponse`, `ClaudeAccountResponse`, `ValidateClaudeRequest`.

### `server/app.py` (MODIFICAR)
- Registrar `profiles.router` bajo `/api`.

### Frontend (`web/`)
- `web/src/lib/api.ts` (MOD): funciones `listProfiles/createProfile/updateProfile/deleteProfile/activateProfile/getClaudeInstallations/validateClaude`.
- `web/src/components/profiles/ProfileSwitcher.tsx` (NUEVO): dropdown en `Header.tsx` (zona derecha, junto al indicador de usuario) que lista perfiles y activa (con confirm + estado "reiniciando…").
- `web/src/components/settings/ProfilesPanel.tsx` (NUEVO): CRUD + selector de cuenta de Claude (lista de radios por email/plan + "Añadir cuenta…"), embebido en `web/src/pages/dashboard/settings.astro` / `SettingsForm.tsx`.
- `web/src/components/layout/Header.tsx` (MOD): montar `ProfileSwitcher`.

## Dependency Map
```
web (Header/Settings) → /api/profiles, /api/claude/* (profiles.py)
profiles.py → ProfileManager (profiles.py) , claude_detect.py , jobs_guard
config.py → ProfileManager            (config NO es importado por ProfileManager)
llm_provider.py → config.settings
```
(sin ciclos: la única dirección sensible config→profiles es unidireccional)

## Cross-Cutting Concerns
### Autenticación
`require_auth` en todos los endpoints (single-user localhost), igual que el resto de rutas.
### Reinicio
Reusa sentinel `~/.azelia/<active>/.restart` + exit 42 (`cli.py:391`). **Orden obligatorio:** escribir `active_profile` en el registry **antes** de tocar el sentinel, para que el proceso relanzado lea el perfil correcto.
### Guard de jobs
`has_active_jobs()` compartido; `activate` y `system/update` lo usan. El switch nunca corre con job activo ⇒ no hay procesos huérfanos.
### Manejo de errores
`HTTPException(status_code, detail=<código>)` con los códigos del spec (INVALID_NAME, ACTIVE_JOBS, LAST_PROFILE, PROFILE_ACTIVE, etc.). Nunca se filtran tokens (solo campos no-secretos de `oauthAccount`).
### Config / secrets
`secrets.env` por perfil (cae solo del data_dir aislado). Paths de borrado validados: `delete_data` solo dentro de `~/.azelia/profiles/`.

## Architectural Risks
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Migración interrumpida al mover el árbol legacy | Baja | Alto (pérdida de datos) | `os.rename` atómico si mismo volumen; si cross-volumen ⇒ registrar in-place sin mover. Escribir `profiles.json` **solo** tras mover con éxito. Idempotente. |
| `.claude/.claude.json` legacy con email distinto al activo | Media | Medio (cuenta mal etiquetada) | Regla de archivo autoritativo (default⇒home, custom⇒dentro), ya verificada en máquina real |
| Ciclo de import config↔profiles | Media | Alto (crash al arrancar) | `ProfileManager` resuelve home vía `AZELIA_HOME`/`Path.home()`, jamás importa `config` |
| `settings` cachea data_dir al importar | Cierta (por diseño) | Bajo | El switch reinicia el proceso; aceptado en el spec |
| Orden registry/sentinel invertido | Baja | Medio (arranca en perfil viejo) | Test explícito del orden; helper único `activate()` |
| Binario `claude.exe` / cross-platform | Cierta (visto aquí) | Bajo | Detección prueba nombres `claude`,`claude.exe`,`claude.cmd`; se ejecuta el symlink del PATH |
| Versión futura de Claude cambia el esquema de `oauthAccount` | Baja | Bajo | Lectura defensiva (`.get`); si falta el email ⇒ `logged_in:false` y la UI cae al alta manual por carpeta. No rompe nada |
| Cuenta en carpeta no-estándar no auto-detectada | Cierta (otros installs) | Bajo | Auto-escaneo es best-effort; el alta manual (F7) cubre cualquier ubicación de forma universal |

## Directory Structure
```
packages/core/
  profiles.py         # NUEVO — ProfileManager + Profile + migración + registry
  claude_detect.py    # NUEVO — detección de binarios/cuentas + validate
  config.py           # MOD  — data_dir y claude_* desde perfil activo
  llm_provider.py     # MOD  — binario + CLAUDE_CONFIG_DIR por perfil
server/
  routes/profiles.py  # NUEVO — endpoints F1–F7
  services/jobs_guard.py  # NUEVO (o extraer en job_store) — has_active_jobs()
  models.py           # MOD  — modelos de perfiles/claude
  app.py              # MOD  — registrar router
web/src/
  components/profiles/ProfileSwitcher.tsx   # NUEVO
  components/settings/ProfilesPanel.tsx     # NUEVO
  components/layout/Header.tsx              # MOD
  lib/api.ts                                # MOD
tests/
  test_profiles_manager.py        # NUEVO
  test_profiles_migration.py      # NUEVO
  test_claude_detect.py           # NUEVO
  test_profiles_endpoints.py      # NUEVO
  test_llm_provider_profile.py    # NUEVO
```

## Sequencing Rationale
Slices verticales, cada uno con su test (RED→GREEN→REFACTOR), ordenados para que ningún task dependa de uno incompleto:
1. **Núcleo de perfiles** (profiles.py: registry + CRUD + slug) — base de todo.
2. **Migración** (F9) — depende de (1); aísla el riesgo de datos en un slice propio y testeable con tmp dirs.
3. **Detección de Claude** (claude_detect.py: binarios + cuentas + validate) — independiente, paralelizable con (1)/(2).
4. **Integración config + llm_provider** — depende de (1) y (3); conecta el perfil activo a data_dir y a la CLI.
5. **Endpoints** (profiles.py + models + app + jobs_guard) — depende de (1)–(4).
6. **Frontend** (switcher + panel) — depende de (5).
```
```
