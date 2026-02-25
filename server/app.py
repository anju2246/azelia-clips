from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from server.routes.jobs import router
from packages.core.config import settings

from packages.core.db.engine import init_db
from server.dependencies import job_queue

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup Database (creates missing tables)
    init_db()
    
    # Start Job Queue Background Workers
    # Here we would register the main processing logic and then start:
    await job_queue.start_workers(num_workers=1)
    
    yield
    
    # Graceful Shutdown
    await job_queue.stop_workers()

app = FastAPI(title="Celia Clips API", version="0.1.0", lifespan=lifespan)

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

# Include routes
app.include_router(router, prefix="/api")

@app.get("/")
def health_check():
    return {"status": "ok", "service": "Celia Clips API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.app:app", host="0.0.0.0", port=8000, reload=True)
