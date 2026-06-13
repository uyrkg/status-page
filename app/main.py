import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load .env file so env vars are available via os.getenv
load_dotenv()

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi import status as http_status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import os

from app.database import init_db, get_db_connection
from app.config import config
from app.routers import endpoints, incidents, maintenance, status, config as config_router
from app.monitor import start_scheduler
from app.auth import (
    require_admin,
    create_session_token,
    authenticate_user,
    ensure_admin_user,
    hash_password,
)

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
    ensure_admin_user()
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

# Register routers — status router FIRST so public /api/endpoints wins
app.include_router(status.router)
app.include_router(endpoints.router)
app.include_router(incidents.router)
app.include_router(maintenance.router)
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
    """Authenticate with username/password and set a session cookie."""
    body = await request.json()
    username = body.get("username", "")
    password = body.get("password", "")

    if not authenticate_user(username, password):
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
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


# --- User management routes (admin-only) ---

@app.get("/api/admin/users")
async def list_users(_=Depends(require_admin)):
    """List all users (without password hashes)."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, username, is_admin, created_at FROM users ORDER BY id"
        ).fetchall()
        return [
            {
                "id": r["id"],
                "username": r["username"],
                "is_admin": bool(r["is_admin"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()


@app.post("/api/admin/users")
async def create_user(request: Request, _=Depends(require_admin)):
    """Create a new user."""
    body = await request.json()
    username = body.get("username", "")
    password = body.get("password", "")
    is_admin = body.get("is_admin", False)

    if not username or len(username) < 3:
        raise HTTPException(400, "Username must be at least 3 characters")
    if not password or len(password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    conn = get_db_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            raise HTTPException(409, "Username already exists")

        pw_hash = hash_password(password)
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
            (username, pw_hash, 1 if is_admin else 0),
        )
        conn.commit()
        return {
            "id": cursor.lastrowid,
            "username": username,
            "is_admin": bool(is_admin),
        }
    finally:
        conn.close()


@app.delete("/api/admin/users/{user_id}")
async def delete_user(user_id: int, _=Depends(require_admin)):
    """Delete a user. Cannot delete the initial admin (id=1)."""
    if user_id == 1:
        raise HTTPException(400, "Cannot delete the initial admin user")

    conn = get_db_connection()
    try:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return {"success": True}
    finally:
        conn.close()