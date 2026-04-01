# Azelia Clips — Web Dashboard

Dashboard web de Azelia construido con Astro + React + Tailwind CSS.

## Setup

El dashboard corre integrado con el servidor FastAPI. La forma más simple es:

```bash
# Desde la raíz del repo:
azelia start          # Build frontend + inicia servidor en localhost:8000
azelia start --dev    # Modo desarrollo con hot reload
```

## Desarrollo local (manual)

```bash
cd web
npm install
npm run dev           # Frontend en localhost:4321
```

En paralelo, inicia el backend desde la raíz:
```bash
uvicorn server.app:app --reload --port 8000
```

## Variables de entorno

Crea `web/.env` basándote en `web/.env.example`:

```bash
cp web/.env.example web/.env
```

Edita con tu proyecto de Supabase:
```
PUBLIC_SUPABASE_URL=https://tu-proyecto.supabase.co
PUBLIC_SUPABASE_ANON_KEY=tu-anon-key
PUBLIC_API_URL=/api
```

## Comandos disponibles

| Comando | Acción |
|:--------|:-------|
| `npm install` | Instala dependencias |
| `npm run dev` | Dev server en `localhost:4321` |
| `npm run build` | Build de producción en `./dist/` |
| `npm run preview` | Preview del build local |

## Stack

- **Framework:** Astro 5 + React 19
- **Styling:** Tailwind CSS 4
- **Auth/DB:** Supabase JS
- **Build:** Vite
- **PWA:** vite-plugin-pwa
