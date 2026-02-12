# Guía de Integración: Base de Datos de Transcripciones Personalizada

Celia Clips permite conectar tu propia base de datos Supabase como fuente de transcripciones. Esto es ideal si ya tienes un pipeline de transcripción existente y solo quieres usar Celia para la generación de clips.

## 1. Modelo de Datos necesario

Celia espera encontrar dos tablas en tu base de datos Supabase: `episodes` y `utterances`.

### Tabla `episodes`
Almacena la metadata del episodio.

| Columna | Tipo | Descripción |
| :--- | :--- | :--- |
| `id` | uuid/text | ID único del episodio (PK). |
| `episode_number` | int | Número del episodio (e.g., 108). Usado para buscar archivos. |
| `title` | text | Título del episodio. |
| `youtube_url` | text | (Opcional) URL del video original. |
| `published_at` | timestamptz | Fecha de publicación. |

### Tabla `utterances`
Almacena cada segmento de texto hablado con sus tiempos.

| Columna | Tipo | Descripción |
| :--- | :--- | :--- |
| `id` | uuid | ID único del segmento (PK). |
| `episode_id` | uuid/text | FK relacionando con `episodes.id`. |
| `speaker` | text | Etiqueta del hablante (e.g., "A", "B", "HOST", "GUEST"). |
| `text` | text | El texto hablado. |
| `start_time` | float | Tiempo de inicio en segundos (e.g., 12.5). |
| `end_time` | float | Tiempo de fin en segundos (e.g., 15.2). |

---

## 2. Configuración de Seguridad (Row Level Security)

Para proteger tu base de datos, es **CRITICO** activar Row Level Security (RLS). Esto asegura que solo lectura/escritura autorizada sea permitida.

### Script SQL recomendado

Ejecuta este SQL en tu Supabase Dashboard > SQL Editor para configurar las tablas y permisos básicos.

```sql
-- 1. Crear tablas
create table if not exists public.episodes (
  id uuid DEFAULT gen_random_uuid() primary key,
  episode_number int not null,
  title text,
  youtube_url text,
  published_at timestamptz
);

create table if not exists public.utterances (
  id uuid DEFAULT gen_random_uuid() primary key,
  episode_id uuid references public.episodes(id) on delete cascade,
  speaker text,
  text text,
  start_time float,
  end_time float
);

-- 2. Habilitar RLS
alter table public.episodes enable row level security;
alter table public.utterances enable row level security;

-- 3. Crear políticas de lectura pública (Opcional, si quieres que cualquiera lea)
-- Peligroso: Cualquiera con tu URL y Anon Key podría leer tus transcripciones.
-- create policy "Allow public read" on public.episodes for select using (true);
-- create policy "Allow public read" on public.utterances for select using (true);

-- 3. (MEJOR OPCIÓN) Crear política de lectura solo para usuarios autenticados o con clave específica
-- Si usas la API Only mode, la "Service Role Key" salta estas reglas.
-- Si usas la Anon Key desde el cliente (Celia Clips), necesitas una política que permita lectura.

-- Ejemplo: Permitir lectura anónima (necesario para que Celia lea desde el navegador con solo la URL/Key)
-- Como la Key se guarda en el navegador del usuario, se considera "pública" para ese usuario.
create policy "Enable read access for all users" on public.episodes for select using (true);
create policy "Enable read access for all users" on public.utterances for select using (true);

-- 4. Bloquear escritura (Solo Service Role puede escribir)
-- No crees políticas de INSERT/UPDATE para 'anon' o 'authenticated' a menos que sea necesario.
```

> **Nota de Seguridad:** Al permitir `select using (true)` con la `anon key`, cualquiera que tenga tu `anon key` puede leer estas tablas. Dado que Celia Clips es una app local o protegida por ti, esto es aceptable. Si quieres más seguridad, podrías implementar autenticación de usuarios en Supabase y políticas `auth.uid() = owner_id`.

## 3. Script de Importación (`upload_transcript.py`)

Incluimos un script de utilidad para subir tus JSONs de transcripción existentes a Supabase compatible con este esquema.

### Uso:

1.  Instala dependencias: `pip install supabase rich`
2.  Configura tus variables de entorno o edita el script con tu URL/KEY.
3.  Ejecuta:

```bash
python3 docs/custom_integrations/upload_transcript.py path/to/transcript.json --episode-num 105 --title "Mi Episodio Genial"
```

El script parseará el JSON (formato Whisper/AssemblyAI estándar) e insertará las filas en `episodes` y `utterances`.
