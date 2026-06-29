# Spec: Multi-perfil de podcasts + selección de Claude Code por perfil

## Status
Draft

## Purpose
Permitir que un mismo usuario gestione **varios podcasts ("perfiles") completamente aislados** dentro de la
misma instalación de Azelia Clips, saltando entre ellos desde el dashboard sin que los jobs, clips, settings,
tokens de YouTube ni secretos de un perfil se mezclen con los de otro. Cada perfil puede además apuntar a una
**cuenta/instalación distinta de Claude Code** (binario + `CLAUDE_CONFIG_DIR` propios), de modo que cada podcast
use la suscripción de Claude que le corresponda. Mantiene la promesa local-first: todo vive en disco bajo
`~/.azelia/`, sin backend central, sin auth multi-usuario.

## Scope

### In Scope
- Modelo de **perfil** = un podcast con su propio árbol de datos bajo `~/.azelia/profiles/<slug>/`.
- **Registry global** (`~/.azelia/profiles.json`) con la lista de perfiles y el puntero al perfil activo.
- Resolución del `data_dir` efectivo a partir del perfil activo (la app entera opera contra ese árbol).
- **Migración automática** del árbol legacy `~/.azelia/data/` al primer arranque: se mueve a
  `~/.azelia/profiles/<slug>/` con el nombre del podcast actual (`PODCAST_NAME`), o **"Inminente"** si no tiene nombre.
- **CRUD de perfiles**: crear, listar, renombrar/editar, borrar, y **activar** (cambiar de perfil).
- El cambio de perfil **reinicia el servidor** (vía sentinel `.restart` + exit 42 ya existentes) para arrancar
  limpio contra el nuevo árbol. Se **bloquea** si hay un job en curso.
- **Detección de instalaciones de Claude Code** en la máquina (PATH + rutas comunes) y validación de un binario.
- Asignación por perfil de `claude_binary` (path) y `claude_config_dir`, usados al invocar la CLI.
- UI: selector de perfil en el dashboard + pantalla de gestión de perfiles en Settings.

### Out of Scope
- Multi-usuario real / login / permisos (sigue siendo single-user localhost).
- Cambio de perfil **en caliente** sin reiniciar.
- Mover/copiar jobs entre perfiles.
- Cualquier sincronización remota o backend central.
- Gestión del login de Claude en sí (Azelia solo apunta a un `CLAUDE_CONFIG_DIR`; el `claude /login` lo hace el usuario).
- Tests de frontend (no hay runner JS en el repo); la UI se valida manualmente.

## Tech Stack
- Python 3.11+, FastAPI (backend), Pydantic Settings (config).
- Astro + React (dashboard, `web/`).
- Persistencia: filesystem + SQLite por perfil (`jobs.db`, `youtube_shorts.db`) + `secrets.env` por perfil.
- Registry de perfiles: JSON plano en `~/.azelia/profiles.json`.
- Test runner: **`python -m pytest tests/ -v`** (equivale a `make test`).

## Core Entities

### Profile (persistido en el registry)
| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | string (slug) | required, único, `^[a-z0-9][a-z0-9-]{0,47}$` | Identificador estable; deriva del nombre al crear, no cambia al renombrar |
| name | string | required, 1–64 chars, trim | Nombre visible del podcast (= `PODCAST_NAME` del perfil) |
| data_dir | string (abs path) | required | Árbol de datos del perfil. Default nuevos: `~/.azelia/profiles/<id>/` |
| claude_binary | string \| null | path absoluto a un ejecutable, o null | Binario de Claude Code; null ⇒ usar `claude` del PATH |
| claude_config_dir | string \| null | path absoluto, o null | Valor de `CLAUDE_CONFIG_DIR` para esa cuenta; null ⇒ default de la CLI |
| is_default | bool | exactamente uno true | Marca el perfil creado por migración; no se puede borrar si es el único |
| created_at | string (ISO-8601) | required | Sello de creación |

### ProfileRegistry (`~/.azelia/profiles.json`)
```json
{
  "version": 1,
  "active_profile": "<slug>",
  "profiles": [ /* Profile[] */ ]
}
```
Vive **fuera** de cualquier `data_dir` (es global de la máquina). Si `AZELIA_DATA_DIR` está seteado explícitamente,
ese override gana: se registra como perfil `default` **in-place** (sin mover nada) y se respeta esa ruta.

> **Modelo mental — cuenta vs binario:** la cuenta (login/email) NO vive en el binario sino en el
> `CLAUDE_CONFIG_DIR` (su `.claude.json` → `oauthAccount.emailAddress`). Mismo binario + distinto config dir
> = cuenta distinta. El selector principal de la UI es **la cuenta** (config dir, identificada por email);
> el binario es secundario (normalmente uno solo en el PATH).

### ClaudeInstallation (binario detectado en runtime, NO persistido)
| Field | Type | Description |
|-------|------|-------------|
| path | string (abs) | Ruta del ejecutable `claude` encontrado |
| version | string \| null | Salida de `claude --version` (null si no responde) |
| source | enum | `path` \| `claude_local` \| `npm` \| `homebrew` \| `manual` |
| valid | bool | True si `--version` salió con código 0 dentro del timeout |

### ClaudeAccount (cuenta detectada por config dir, NO persistido)
| Field | Type | Description |
|-------|------|-------------|
| config_dir | string (abs) | Carpeta de config (`CLAUDE_CONFIG_DIR`); null/`~/.claude` = default |
| email | string \| null | `oauthAccount.emailAddress` del `.claude.json`; null si no hay sesión |
| display_name | string \| null | `oauthAccount.displayName` |
| plan | string \| null | `oauthAccount.organizationType` (p.ej. `claude_max`, `pro`) |
| logged_in | bool | True si hay `oauthAccount` con email |

## Features

### F1 — Listar perfiles
**Input:** `GET /api/profiles`
**Output (success):**
```
HTTP 200
{
  "active_profile": "inminente",
  "profiles": [
    {"id":"inminente","name":"Inminente","data_dir":"/Users/x/.azelia/profiles/inminente",
     "claude_binary":null,"claude_config_dir":null,"is_default":true,"created_at":"2026-06-16T...","active":true}
  ]
}
```
**Business Rules:** `claude_binary`/`claude_config_dir` se devuelven tal cual (paths, no secretos). `active` = `id == active_profile`.

### F2 — Crear perfil
**Input:** `POST /api/profiles`
```
{"name":"Mi Otro Podcast","claude_binary":null,"claude_config_dir":null}
```
**Output (success):** `HTTP 201` con el `Profile` creado. **No** cambia el perfil activo.
**Business Rules:**
1. `id` = slug(`name`); si colisiona, sufijo `-2`, `-3`, …
2. Crea `~/.azelia/profiles/<id>/` (incluye `jobs/`) y un `secrets.env` con `PODCAST_NAME=<name>`.
3. Si se pasan `claude_binary`/`claude_config_dir`, deben validarse (ver F7) antes de guardar.

**Output (error cases):**
| Condition | HTTP | Error Code | Message |
|-----------|------|-----------|---------|
| name vacío o >64 | 422 | INVALID_NAME | Profile name must be 1–64 characters |
| name slugifica a vacío (p.ej. solo símbolos) | 422 | INVALID_NAME | Profile name must contain letters or digits |
| `claude_binary` no existe / no ejecutable | 422 | INVALID_CLAUDE_BINARY | Selected Claude binary is not a valid executable |
| `claude_config_dir` no es directorio | 422 | INVALID_CONFIG_DIR | CLAUDE_CONFIG_DIR must be an existing directory |

### F3 — Renombrar / editar perfil
**Input:** `PATCH /api/profiles/{id}` — cualquiera de: `name`, `claude_binary`, `claude_config_dir` (null permitido para limpiar).
**Output (success):** `HTTP 200` con el `Profile` actualizado.
**Business Rules:**
1. `id` y `data_dir` **no** cambian al renombrar (solo `name` y el `PODCAST_NAME` del `secrets.env` del perfil).
2. Si el perfil editado es el activo, los cambios de `claude_binary`/`claude_config_dir` aplican tras el próximo arranque
   (se sugiere reactivar). El de `name` aplica en caliente para la UI.

**Output (error cases):** `404 PROFILE_NOT_FOUND`; mismas validaciones que F2 para binary/config_dir/name.

### F4 — Borrar perfil
**Input:** `DELETE /api/profiles/{id}?delete_data=false`
**Output (success):** `HTTP 200 {"deleted":"<id>","data_removed":false}`
**Business Rules:**
1. No se puede borrar el perfil **activo** (cambia primero) → `409 PROFILE_ACTIVE`.
2. No se puede borrar el **último** perfil → `409 LAST_PROFILE`.
3. `delete_data=false` (default): solo desregistra; el árbol queda en disco.
4. `delete_data=true`: borra recursivamente `data_dir` (solo si está bajo `~/.azelia/profiles/`; nunca borra una ruta in-place de `AZELIA_DATA_DIR`).

**Output (error cases):** `404 PROFILE_NOT_FOUND`, `409 PROFILE_ACTIVE`, `409 LAST_PROFILE`.

### F5 — Activar perfil (cambiar)
**Input:** `POST /api/profiles/{id}/activate`
**Output (success):** `HTTP 200 {"status":"restarting","active_profile":"<id>"}`
**Business Rules:**
1. Si hay un job activo (`processing`/`pending`/`resuming`) → **bloquea** con `409 ACTIVE_JOBS` e incluye los job IDs.
   (Reutiliza la lógica de `_has_active_jobs()` de `server/routes/system.py`.)
2. Escribe `active_profile` en el registry y toca el sentinel `.restart` del **data_dir vigente** → el watcher
   sale con exit 42 → el wrapper relanza el server, que ya resuelve el nuevo perfil.
3. Si `id` == activo → `200 {"status":"noop"}` sin reiniciar.

**Output (error cases):** `404 PROFILE_NOT_FOUND`, `409 ACTIVE_JOBS`.

### F6 — Detectar instalaciones y cuentas de Claude Code
**Input:** `GET /api/claude/installations`
**Output (success):**
```
HTTP 200
{
  "installations":[
    {"path":"/Users/x/.claude/local/claude","version":"1.x.x","source":"claude_local","valid":true},
    {"path":"/opt/homebrew/bin/claude","version":"1.x.x","source":"homebrew","valid":true}
  ],
  "accounts":[
    {"config_dir":null,"email":"juan2005duque@gmail.com","display_name":"JuanPa","plan":"claude_max","logged_in":true},
    {"config_dir":"/Users/x/.claude-work","email":"trabajo@empresa.com","display_name":"Trabajo","plan":"pro","logged_in":true}
  ]
}
```
**Business Rules:**
1. **Binarios:** busca en PATH (todas las coincidencias, estilo `which -a`), `~/.claude/local/claude`, prefijo de
   npm global (`npm prefix -g`/bin), homebrew (`/opt/homebrew/bin/claude`, `/usr/local/bin/claude`).
   Deduplica por ruta real (`realpath`); cada candidato corre `--version` (timeout 3s) para `version`/`valid`.
2. **Cuentas:** candidatos = el dir default `~/.claude` y la env `CLAUDE_CONFIG_DIR` (**universales**, todo
   install los tiene), cualquier `CLAUDE_CONFIG_DIR` ya referenciado por un perfil, y —solo como comodidad
   best-effort— los hermanos `~/.claude-*` (excluyendo `*.backup`/`*.bak`/dirs sin sesión). El auto-escaneo de
   carpetas no-estándar NO se garantiza; el alta manual (F7, "elegir carpeta") es la vía universal que cubre
   cualquier ubicación. Para cada candidato, resuelve el archivo **autoritativo** así (verificado en máquina real):
   - dir default `~/.claude` (sin `CLAUDE_CONFIG_DIR`) ⇒ `~/.claude.json` (en el **home**), NO el `~/.claude/.claude.json`
     interno (que puede ser legacy/obsoleto con otro email).
   - dir custom `X` ⇒ `X/.claude.json` (dentro del dir); **nunca** caer a `~/.claude.json` (mez­claría cuentas).
   Extrae `oauthAccount.emailAddress`, `displayName`, `organizationType`. Sin `oauthAccount` (o si una versión
   futura de Claude cambia el esquema) ⇒ degradar con elegancia: `logged_in:false`, `email:null`, y la UI
   identifica la cuenta por su carpeta. Deduplica por config_dir real; varias entradas con el mismo email son
   válidas (cuentas en dirs distintos).
3. Nunca lanza error ni filtra tokens: solo lee los campos no-secretos de `oauthAccount`. Una entrada inválida
   se incluye con `valid:false` / `logged_in:false`.

### F7 — Validar / identificar un binario + config dir manual
**Input:** `POST /api/claude/validate` → `{"path":"/ruta/claude","config_dir":"/ruta/cfg"}` (`path` opcional ⇒ `claude` del PATH; `config_dir` opcional)
**Output (success):**
```
HTTP 200
{"valid":true,"version":"1.x.x","account":{"email":"...","display_name":"...","plan":"...","logged_in":true}}
```
o `{"valid":false,"reason":"not_executable|version_failed|timeout|config_dir_not_found"}`
**Business Rules:** si se pasa `path`, debe existir y ser ejecutable; corre `--version` (con `CLAUDE_CONFIG_DIR=config_dir`
si se pasó) y resuelve la cuenta leyendo el `.claude.json` de ese config dir igual que F6. Permite al usuario
"Añadir cuenta…" eligiendo una carpeta de config a mano y ver de inmediato a qué email pertenece.

### F8 — Aislamiento efectivo (cross-cutting, sin endpoint propio)
**Business Rules:**
1. `packages/core/config.py` resuelve `settings.data_dir` **del perfil activo** (vía un `profile_manager`),
   ejecutando la migración una sola vez si el registry no existe.
2. Todo lo que ya deriva de `settings.data_dir` (jobs, `jobs.db`, `youtube_shorts.db`, `secrets.env`,
   `update.log`, `.restart`) queda automáticamente aislado por perfil — no se tocan esos call-sites.
3. `secrets.env` es por perfil ⇒ `ANTHROPIC_API_KEY`, tokens de YouTube y demás no se filtran entre perfiles.
4. `llm_provider` usa `settings.claude_binary` (o `"claude"`) como ejecutable y, si hay `settings.claude_config_dir`,
   lo pasa como `CLAUDE_CONFIG_DIR` en el `env` de cada `subprocess.run` (incluye `claude_code_available`/`_authenticated`).

### F9 — Migración del árbol legacy
**Business Rules (idempotente, corre al arrancar si falta `~/.azelia/profiles.json`):**
1. Si `AZELIA_DATA_DIR` está seteado explícitamente → registrar perfil `default` **in-place** con esa ruta; no mover.
2. Si existe `~/.azelia/data/` (legacy estándar):
   - `name` = `PODCAST_NAME` leído de `~/.azelia/data/secrets.env` si existe y no es vacío ni `"My Podcast"`; si no → **"Inminente"**.
   - `id` = slug(name). Mueve `~/.azelia/data/` → `~/.azelia/profiles/<id>/` (rename atómico en el mismo volumen).
   - Escribe el registry con ese perfil como `active` e `is_default:true`.
3. Si no hay data legacy → crear perfil "Inminente" vacío (`~/.azelia/profiles/inminente/`).
4. La migración es atómica respecto al registry: el `profiles.json` solo se escribe tras mover los datos con éxito.

## Non-Functional Requirements
- Response time: endpoints de perfiles < 300 ms (excepto F6 detección, < 5 s por los `--version`).
- Authentication: igual que el resto (`require_auth`, single-user localhost).
- Authorization: N/A (single user).
- El cambio de perfil **nunca** corre con un job activo (garantía de no dejar procesos huérfanos).
- Paths derivados de input de usuario (slug, data_dir, delete) sanitizados contra path traversal; `delete_data`
  solo opera dentro de `~/.azelia/profiles/`.

## Done Conditions
- [ ] `python -m pytest tests/ -v` pasa en verde, incluyendo los nuevos tests de perfiles, detección de Claude y migración.
- [ ] Con registry ausente y un `~/.azelia/data/` legacy, el arranque crea el perfil migrado (nombre del podcast o "Inminente") sin perder datos.
- [ ] `GET/POST/PATCH/DELETE /api/profiles` y `POST /api/profiles/{id}/activate` cumplen los contratos de F1–F5.
- [ ] Activar un perfil con un job activo devuelve `409 ACTIVE_JOBS` con los IDs.
- [ ] Activar un perfil sin jobs escribe el sentinel `.restart` y devuelve `{"status":"restarting"}`.
- [ ] `GET /api/claude/installations` lista binarios (con versión) **y cuentas identificadas por email/plan**; `POST /api/claude/validate` valida path+config_dir y devuelve el email de la cuenta.
- [ ] Tras activar el perfil B, los jobs/clips/secrets visibles son los de B y nunca los de A.
- [ ] `llm_provider` invoca el binario y `CLAUDE_CONFIG_DIR` del perfil activo.
- [ ] El dashboard muestra el selector de perfil y la pantalla de gestión (crear/editar/borrar/activar) cableada a los endpoints.
