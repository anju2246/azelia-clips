"""Azelia Clips API — local-first FastAPI server.

Binds to 127.0.0.1 by default (configurable via AZELIA_BIND_HOST).
No real auth: single local owner. See server/middleware/auth.py.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from packages.core.config import settings
from server.dependencies import job_queue
from server.routes.analytics import router as analytics_router
from server.routes.clips import router as clips_router
from server.routes.settings import router as settings_router
from server.routes.taxonomy import router as taxonomy_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure data dir exists
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    # Start background workers
    await job_queue.start_workers(num_workers=1)
    yield
    # Graceful shutdown
    await job_queue.stop_workers()


app = FastAPI(title="Azelia Clips API", version="0.1.0", lifespan=lifespan)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Fallback standard JSON exception structure."""
    if hasattr(exc, "status_code"):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail if hasattr(exc, "detail") else str(exc)},
        )
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


# CORS — only same-origin in local mode, but keep middleware for dev (Astro on :4321)
origins = [origin.strip() for origin in settings.allowed_cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


# Static Astro build
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "dist")
os.makedirs(static_dir, exist_ok=True)

# API routes (must come before static mount)
app.include_router(clips_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(analytics_router, prefix="/api")
app.include_router(taxonomy_router, prefix="/api")


@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "Azelia Clips API", "version": app.version}


# Mount Astro at root
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server.app:app", host="127.0.0.1", port=8000, reload=True)
