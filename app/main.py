import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load .env file so env vars are available via os.getenv
load_dotenv()

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi import status as http_status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import os

from app.database import init_db
from app.config import config
from app.routers import endpoints, incidents, maintenance, status, config as config_router
from app.monitor import start_scheduler
from app.auth import require_admin, create_session_token, verify_password

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
    start_scheduler(app)
    yield
    # Shutdown handled by scheduler


# Rate limiter
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="StatusPage API",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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


# --- Admin auth routes ---

@app.get("/admin/login")
async def serve_login():
    """Serve the login page."""
    login_path = os.path.join(static_dir, "login.html")
    if os.path.exists(login_path):
        return FileResponse(login_path)
    return {"message": "Login page not found"}


@app.post("/api/admin/login")
@limiter.limit("10/minute")
async def admin_login(request: Request):
    """Authenticate and set a session cookie."""
    body = await request.json()
    password = body.get("password", "")

    if not verify_password(password):
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
        )

    token = create_session_token()
    response = JSONResponse({"success": True})
    response.set_cookie(
        key="admin_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400,  # 24 hours
        path="/",
    )
    return response


@app.post("/api/admin/logout")
async def admin_logout():
    """Clear the session cookie."""
    response = JSONResponse({"success": True})
    response.delete_cookie(key="admin_session", path="/")
    return response


@app.get("/admin")
async def serve_admin(_=Depends(require_admin)):
    """Protected admin page — requires valid session."""
    admin_path = os.path.join(static_dir, "admin.html")
    if os.path.exists(admin_path):
        return FileResponse(admin_path)
    return {"message": "Admin page not found"}
