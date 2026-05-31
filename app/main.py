import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from app.database import init_db
from app.config import config
from app.routers import endpoints, incidents, maintenance, status, config as config_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing database")
    init_db()
    yield
    # Shutdown handled by scheduler


app = FastAPI(
    title="StatusPage API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for internal use
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(endpoints.router)
app.include_router(incidents.router)
app.include_router(maintenance.router)
app.include_router(status.router)
app.include_router(config_router.router)

# Static files
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def serve_index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "StatusPage API running", "docs": "/docs"}


@app.get("/maintenance")
async def serve_maintenance():
    maint_path = os.path.join(static_dir, "maintenance.html")
    if os.path.exists(maint_path):
        return FileResponse(maint_path)
    return {"message": "Maintenance page not found"}


@app.get("/admin")
async def serve_admin():
    admin_path = os.path.join(static_dir, "admin.html")
    if os.path.exists(admin_path):
        return FileResponse(admin_path)
    return {"message": "Admin page not found"}


# --- Scheduler startup/shutdown ---
from app.monitor import start_scheduler

@app.on_event("startup")
async def startup_scheduler():
    start_scheduler(app)
