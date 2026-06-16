# Tasks: Multi-perfil de podcasts + selección de Claude Code por perfil

> Cada task es un slice vertical con su ciclo RED → GREEN → REFACTOR.
> Test runner: `python -m pytest tests/ -v`. Marcar `[x]` solo cuando los tests del task pasan en verde.
> Crítica del orden: T1 → T2 → T4 → T5 → T6. T3 es paralelizable con T1/T2.

---

## Task T1: Núcleo de perfiles — ProfileManager + registry + slug
**Status:** [ ]
**Complexity:** M
**Dependencies:** none
**Parallelizable with:** T3

### Description
Modelo `Profile` y `ProfileManager` que lee/escribe el registry `~/.azelia/profiles.json` (atómico), genera slugs únicos, y expone CRUD + activo. Sin migración todavía (T2) y sin tocar `config.py` (T4). Es la base de todo. Resuelve el home vía `AZELIA_HOME`/`Path.home()` y **no importa `config.py`** (evita ciclo).

### Files to Create
- `packages/core/profiles.py`: `Profile` (dataclass/pydantic), `ProfileManager(azelia_home)`, `slugify()`, registry read/write atómico (`.tmp`+`os.replace`), `list/get/active/create/update/delete/set_active/active_data_dir`.
- `tests/test_profiles_manager.py`: tests del CRUD y reglas.

### Files to Modify
- (ninguno)

### Acceptance Criteria
- [ ] `create("Mi Podcast")` genera slug `mi-podcast`, crea `<home>/profiles/mi-podcast/jobs/` y un `secrets.env` con `PODCAST_NAME=Mi Podcast`.
- [ ] Slug colisionante recibe sufijo `-2`, `-3`.
- [ ] `delete` rechaza el perfil activo y el último (raise dominio-específico); `delete_data=True` solo borra dentro de `<home>/profiles/`.
- [ ] `set_active` persiste el puntero; el registry se reescribe atómicamente (nunca queda corrupto a medias).
- [ ] Validación de nombre (1–64, slug no vacío) y de `claude_binary`/`claude_config_dir`.
- [ ] Todos los tests en `tests/test_profiles_manager.py` pasan bajo `python -m pytest tests/test_profiles_manager.py -v`.

### TDD Anchors
- `test_create_profile_generates_slug_and_dirs`
- `test_create_collision_appends_suffix`
- `test_invalid_name_rejected`
- `test_delete_active_profile_rejected`
- `test_delete_last_profile_rejected`
- `test_delete_with_data_only_under_profiles_dir`
- `test_set_active_persists_and_atomic_write`
- `test_registry_roundtrip_survives_reload`

---

## Task T2: Migración del árbol legacy (F9)
**Status:** [ ]
**Complexity:** M
**Dependencies:** T1
**Parallelizable with:** T3

### Description
`ProfileManager.ensure_initialized()`: idempotente. Si falta el registry, ejecuta la migración: respeta `AZELIA_DATA_DIR` in-place; o mueve `~/.azelia/data/` a `~/.azelia/profiles/<slug>/` con nombre = `PODCAST_NAME` (o "Inminente"); o crea perfil "Inminente" vacío. El registry se escribe **solo** tras mover con éxito.

### Files to Create
- `tests/test_profiles_migration.py`

### Files to Modify
- `packages/core/profiles.py`: añadir `ensure_initialized()` + helpers de migración (lectura de `PODCAST_NAME` del `secrets.env` legacy, rename atómico mismo-volumen / registro in-place cross-volumen).

### Acceptance Criteria
- [ ] Con registry ausente + `~/.azelia/data/` legacy con `PODCAST_NAME=X`, crea perfil `X` activo y mueve los datos sin pérdida.
- [ ] Sin `PODCAST_NAME` (o ="My Podcast"/vacío) ⇒ nombre "Inminente".
- [ ] Con `AZELIA_DATA_DIR` seteado ⇒ registra default in-place, no mueve nada.
- [ ] Sin data legacy ⇒ crea perfil "Inminente" vacío.
- [ ] `ensure_initialized()` llamado dos veces no cambia el estado (idempotente).
- [ ] El registry no se escribe si el move falla (simular con monkeypatch).
- [ ] Tests en `tests/test_profiles_migration.py` pasan.

### TDD Anchors
- `test_migrates_legacy_data_with_podcast_name`
- `test_default_name_inminente_when_unnamed`
- `test_respects_azelia_data_dir_override_in_place`
- `test_creates_empty_inminente_when_no_legacy`
- `test_ensure_initialized_idempotent`
- `test_registry_not_written_on_move_failure`

---

## Task T3: Detección de binarios y cuentas de Claude Code (F6/F7)
**Status:** [ ]
**Complexity:** M
**Dependencies:** none
**Parallelizable with:** T1, T2

### Description
`claude_detect.py`: descubre binarios (PATH `which -a`, `~/.claude/local`, npm prefix, homebrew; dedupe por realpath; `--version` timeout) y cuentas (regla de archivo autoritativo default⇒`~/.claude.json`, custom⇒`<dir>/.claude.json`; lectura defensiva de `oauthAccount`; filtra `*.backup`). `validate(path, config_dir)`.

### Files to Create
- `packages/core/claude_detect.py`
- `tests/test_claude_detect.py`

### Files to Modify
- (ninguno)

### Acceptance Criteria
- [ ] `detect_installations()` deduplica por realpath y marca `valid`/`version` por binario; entradas inválidas no lanzan, salen con `valid:false`.
- [ ] `read_account` default lee `~/.claude.json` (home), NO `~/.claude/.claude.json` interno.
- [ ] `read_account` custom lee `<dir>/.claude.json` y **no** cae al home.
- [ ] `oauthAccount` ausente o esquema cambiado ⇒ `logged_in:false`, `email:null` (sin crash, sin filtrar tokens).
- [ ] `detect_accounts` excluye `*.backup`/`*.bak`.
- [ ] `validate` reporta `not_executable|version_failed|timeout|config_dir_not_found` y, si ok, el email.
- [ ] Tests en `tests/test_claude_detect.py` pasan (con fixtures de fake config dirs + monkeypatch de subprocess).

### TDD Anchors
- `test_dedup_binaries_by_realpath`
- `test_invalid_binary_marked_not_valid`
- `test_read_account_default_uses_home_json`
- `test_read_account_custom_uses_inner_json_no_fallback`
- `test_missing_oauth_account_degrades_gracefully`
- `test_detect_accounts_skips_backup_dirs`
- `test_validate_reports_reason_codes`

---

## Task T4: Integración config + llm_provider (perfil activo → data_dir + Claude)
**Status:** [ ]
**Complexity:** M
**Dependencies:** T1, T2, T3
**Parallelizable with:** none

### Description
`config.py` resuelve `data_dir` del perfil activo (vía `ProfileManager.ensure_initialized()`), respetando `AZELIA_DATA_DIR`. Añade `claude_binary`/`claude_config_dir` desde el perfil activo. `llm_provider.py` usa ese binario + `CLAUDE_CONFIG_DIR` en cada `subprocess.run`.

### Files to Create
- `tests/test_llm_provider_profile.py`

### Files to Modify
- `packages/core/config.py`: `_default_data_dir()` delega a `ProfileManager` cuando no hay `AZELIA_DATA_DIR`; nuevos campos `claude_binary`, `claude_config_dir`.
- `packages/core/llm_provider.py`: `claude_code_available/authenticated/_call_claude_code` usan `settings.claude_binary or "claude"` + `env` con `CLAUDE_CONFIG_DIR`.

### Acceptance Criteria
- [ ] Con perfil activo X, `settings.data_dir == <home>/profiles/<x>`.
- [ ] `AZELIA_DATA_DIR` seteado sigue ganando (override in-place).
- [ ] `_call_claude_code` invoca `settings.claude_binary` cuando está set, y `"claude"` cuando es None.
- [ ] Cuando `settings.claude_config_dir` está set, el `subprocess.run` recibe `CLAUDE_CONFIG_DIR` en `env` (verificado con monkeypatch capturando kwargs).
- [ ] No hay import circular config↔profiles (la app arranca).
- [ ] Tests en `tests/test_llm_provider_profile.py` pasan y la suite existente sigue verde.

### TDD Anchors
- `test_data_dir_resolves_active_profile`
- `test_azelia_data_dir_override_wins`
- `test_call_claude_code_uses_profile_binary`
- `test_call_claude_code_passes_config_dir_env`
- `test_no_circular_import`

---

## Task T5: Endpoints de perfiles + Claude (F1–F7) + guard de jobs
**Status:** [ ]
**Complexity:** L
**Dependencies:** T1, T2, T3, T4
**Parallelizable with:** none

### Description
Router `profiles.py` con F1–F7. Extrae `has_active_jobs()` a un helper compartido (devuelve IDs). `activate` bloquea si hay jobs, escribe activo y toca `.restart`. Modelos Pydantic en `models.py`. Registra router en `app.py`.

### Files to Create
- `server/routes/profiles.py`
- `server/services/jobs_guard.py`
- `tests/test_profiles_endpoints.py`

### Files to Modify
- `server/models.py`: `ProfileResponse`, `CreateProfileRequest`, `UpdateProfileRequest`, `ClaudeInstallationResponse`, `ClaudeAccountResponse`, `ValidateClaudeRequest`.
- `server/routes/system.py`: usar `jobs_guard.has_active_jobs()` (dejar de duplicar la lógica local).
- `server/app.py`: `include_router(profiles.router, prefix="/api")`.

### Acceptance Criteria
- [ ] `GET /api/profiles` devuelve lista + activo + binding Claude (sin secretos).
- [ ] `POST /api/profiles` crea (201) sin cambiar el activo; valida nombre/binary/config_dir con los códigos del spec.
- [ ] `PATCH` renombra sin cambiar id/data_dir; reasigna claude_*.
- [ ] `DELETE` respeta `PROFILE_ACTIVE`/`LAST_PROFILE`/`delete_data`.
- [ ] `POST /api/profiles/{id}/activate`: con job activo ⇒ `409 ACTIVE_JOBS` con IDs; sin jobs ⇒ escribe activo, toca `.restart`, devuelve `{"status":"restarting"}`; mismo id ⇒ `noop`.
- [ ] `GET /api/claude/installations` devuelve `installations` + `accounts` (email/plan); `POST /api/claude/validate` valida y devuelve email.
- [ ] Orden verificado: registry se actualiza **antes** del touch del sentinel.
- [ ] Tests en `tests/test_profiles_endpoints.py` pasan (TestClient + tmp home/registry, job_store y subprocess mockeados).

### TDD Anchors
- `test_list_profiles_includes_active_and_claude`
- `test_create_profile_201_does_not_switch`
- `test_create_invalid_name_422`
- `test_patch_rename_keeps_id_and_data_dir`
- `test_delete_active_409` / `test_delete_last_409` / `test_delete_data_flag`
- `test_activate_blocked_by_active_jobs_409_lists_ids`
- `test_activate_writes_registry_then_touches_restart`
- `test_activate_same_profile_noop`
- `test_claude_installations_lists_binaries_and_accounts`
- `test_claude_validate_returns_email`

---

## Task T6: Frontend — selector de perfil + panel de gestión + selector de cuenta Claude
**Status:** [ ]
**Complexity:** L
**Dependencies:** T5
**Parallelizable with:** none

### Description
`ProfileSwitcher` en el Header (lista/activa con confirm + estado "reiniciando…"). `ProfilesPanel` en Settings: CRUD + selector de cuenta de Claude por radios (email/plan) + "Añadir cuenta…" (folder picker → validate). Cliente API en `api.ts`. Sin tests JS (no hay runner); validación manual.

### Files to Create
- `web/src/components/profiles/ProfileSwitcher.tsx`
- `web/src/components/settings/ProfilesPanel.tsx`

### Files to Modify
- `web/src/lib/api.ts`: funciones de perfiles y claude.
- `web/src/components/layout/Header.tsx`: montar `ProfileSwitcher`.
- `web/src/pages/dashboard/settings.astro` / `SettingsForm.tsx`: embeber `ProfilesPanel`.

### Acceptance Criteria
- [ ] El Header muestra el perfil activo y permite cambiar; al activar muestra estado de reinicio y reconecta.
- [ ] El panel lista perfiles y permite crear/renombrar/borrar.
- [ ] El selector de cuenta Claude muestra los emails/planes detectados y permite añadir una carpeta manual viendo el email resuelto.
- [ ] `npm run build` en `web/` compila sin errores de tipos.
- [ ] Verificación manual (skill `/run` o `make`): crear un 2º perfil, cambiar, confirmar aislamiento de jobs/secrets.

### TDD Anchors
- (Sin tests automatizados de frontend; cubierto por los tests de endpoints en T5 + verificación manual.)
