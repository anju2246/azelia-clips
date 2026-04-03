from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from server.routes.clips import router as clips_router
from server.routes.settings import router as settings_router
from server.routes.analytics import router as analytics_router
from server.routes.auth import router as auth_router
from server.routes.telemetry_routes import router as telemetry_router
from server.routes.upgrade import router as upgrade_router
from packages.core.config import settings

from packages.core.db.engine import init_db
from server.dependencies import job_queue

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup Database (creates missing tables)
    init_db()
    
    # Start Job Queue Background Workers
    await job_queue.start_workers(num_workers=1)
    
    yield
    
    # Graceful Shutdown
    await job_queue.stop_workers()

app = FastAPI(title="Azelia Clips API", version="0.1.0", lifespan=lifespan)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Fallback standard JSON exception structure."""
    if hasattr(exc, "status_code"):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail if hasattr(exc, "detail") else str(exc)}
        )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"}
    )

# CORS configuration
origins = [origin.strip() for origin in settings.allowed_cors_origins.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve Astro Frontend build
import os
from fastapi.staticfiles import StaticFiles

# Setup directory for static files if it doesn't exist (e.g. before first build)
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "dist")
os.makedirs(static_dir, exist_ok=True)

# Important: API routes must be included BEFORE the static files mount
app.include_router(clips_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(analytics_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(telemetry_router, prefix="/api")
app.include_router(upgrade_router, prefix="/api")

@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "Azelia Clips API"}

# Mount the Astro built static directory at the root
# html=True serves index.html automatically for directory roots
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.app:app", host="0.0.0.0", port=8000, reload=True)
