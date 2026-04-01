# Configuración del Modo Local

Azelia autogenera clips a partir de tus podcasts. Puedes configurar tu entorno local para que detecte automáticamente tus episodios y gestionarlos desde el Dashboard.

## 1. Estructura de Carpetas

Para que Azelia detecte tus episodios, tu carpeta de podcasts debe seguir esta estructura exacta:

```
Carpeta_Principal/    (Ej: /Volumes/Backup Inminente)
├── EP001 - Titulo del Episodio/
│   ├── video.mp4    (Archivo de video fuente)
│   └── transcript.json (Opcional, si ya tienes transcripción)
├── EP002 - Titulo del Segundo Episodio/
└── ...
```

**Reglas Importantes:**
- Cada episodio debe estar en su propia carpeta.
- El nombre de la carpeta DEBE comenzar con `EP` seguido de 3 dígitos (ej: `EP001`, `EP015`).
- El resto del nombre de la carpeta (después de `EP###`) se usa como título en el Dashboard.

## 2. Configurar en el Dashboard

1.  Inicia la aplicación (`npm run dev` y `uvicorn ...`).
2.  Ve a la página **Settings** (Configuración).
3.  En la sección **Local Library**:
    - **Podcast Directory**: Escribe la ruta absoluta a tu carpeta principal.
      - Mac: `/Volumes/Backup Inminente` (o arrastra la carpeta al terminal para ver la ruta).
4.  En la sección **AI Providers**:
    - **Groq API Key**: Ingresa tu llave de Groq para transcripción y análisis rápido.
5.  Haz clic en **Save Settings**.
    - Esto guardará tus configuraciones en un archivo `.env` localmente.

## 3. Usar la Librería

1.  Ve a la página **Library** (Librería).
2.  Verás una lista de todas las carpetas que comienzan con `EP...`.
3.  Podrás ver si tienen Video (`✓`) y Transcripción (`✓`).
4.  Haz clic en **Process Episode** para iniciar la generación de clips.

## Nota de Seguridad

Tus llaves de API y rutas se guardan SOLAMENTE en tu computadora (en el archivo `.env`). Nunca se comparten ni se suben al repositorio público.
