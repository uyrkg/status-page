# Self-Hosted Status Page System — SPEC.md

## 1. Overview

**Name:** StatusPage  
**Purpose:** Internal self-hosted status page for home lab / homelab environments.  
**Stack:** Python 3.11+, FastAPI, SQLite, APScheduler, HTML/CSS frontend, Docker.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Docker Container                  │
│                                                      │
│  ┌──────────┐   ┌──────────┐   ┌────────────────┐  │
│  │  FastAPI │   │ Scheduler│   │  HTML/CSS      │  │
│  │  API     │◄──│ (60s)    │   │  Static Files  │  │
│  └────┬─────┘   └────┬─────┘   └───────┬────────┘  │
│       │              │                 │            │
│       └──────────────┼─────────────────┘            │
│                      ▼                             │
│               ┌──────────────┐                     │
│               │   SQLite     │                     │
│               │  (status.db) │                     │
│               └──────────────┘                     │
└─────────────────────────────────────────────────────┘
```

- **Backend:** FastAPI runs the REST API and serves the static frontend.
- **Scheduler:** APScheduler runs background checks every 60s.
- **Database:** SQLite stores all data (endpoints, incidents, maintenance windows, check history).
- **Frontend:** Vanilla HTML/CSS. No JavaScript framework. Served as static files.
- **Alerts:** SMTP email via aiojobs/asyncio for async dispatch.

---

## 3. Data Model

### 3.1 Endpoint

```sql
CREATE TABLE endpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT,
    host TEXT,
    port INTEGER,
    check_type TEXT NOT NULL DEFAULT 'http',  -- 'http', 'tcp', 'ping'
    check_interval INTEGER DEFAULT 60,         -- seconds
    timeout INTEGER DEFAULT 5,                -- seconds
    expected_status INTEGER DEFAULT 200,       -- for http checks
    is_enabled BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

- `check_type=http`: `url` is required; `expected_status` checked.
- `check_type=tcp`: `host` + `port` required.
- `check_type=ping`: `host` required; no port.

### 3.2 Incident

```sql
CREATE TABLE incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint_id INTEGER NOT NULL REFERENCES endpoints(id),
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'investigating',  -- 'investigating', 'identified', 'monitoring', 'resolved'
    severity TEXT NOT NULL DEFAULT 'major',        -- 'critical', 'major', 'minor', 'cosmetic'
    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

- `resolved_at` is NULL while incident is open.

### 3.3 MaintenanceWindow

```sql
CREATE TABLE maintenance_windows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint_id INTEGER REFERENCES endpoints(id),  -- NULL = all endpoints
    title TEXT NOT NULL,
    description TEXT,
    scheduled_start DATETIME NOT NULL,
    scheduled_end DATETIME NOT NULL,
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 3.4 CheckHistory

```sql
CREATE TABLE check_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint_id INTEGER NOT NULL REFERENCES endpoints(id),
    check_type TEXT NOT NULL,
    success BOOLEAN NOT NULL,
    response_time_ms INTEGER,
    status_code INTEGER,
    error_message TEXT,
    checked_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

- Kept for 30 days; older records pruned by a daily cleanup job.

### 3.5 EmailAlert

```sql
CREATE TABLE email_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint_id INTEGER REFERENCES endpoints(id),
    incident_id INTEGER REFERENCES incidents(id),
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    success BOOLEAN
);
```

---

## 4. API Endpoints

### 4.1 Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/endpoints` | List all endpoints with current status |
| POST | `/api/endpoints` | Create endpoint |
| GET | `/api/endpoints/{id}` | Get endpoint detail |
| PUT | `/api/endpoints/{id}` | Update endpoint |
| DELETE | `/api/endpoints/{id}` | Delete endpoint |
| GET | `/api/endpoints/{id}/history` | Get check history (query params: `?from=&to=&limit=100`) |

### 4.2 Incidents

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/incidents` | List all incidents (open + resolved) |
| POST | `/api/incidents` | Create incident |
| GET | `/api/incidents/{id}` | Get incident detail |
| PUT | `/api/incidents/{id}` | Update incident (change status, severity, etc.) |
| DELETE | `/api/incidents/{id}` | Delete incident |
| POST | `/api/incidents/{id}/resolve` | Resolve incident (sets resolved_at) |

### 4.3 Maintenance Windows

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/maintenance` | List maintenance windows |
| POST | `/api/maintenance` | Create maintenance window |
| GET | `/api/maintenance/{id}` | Get maintenance window |
| PUT | `/api/maintenance/{id}` | Update maintenance window |
| DELETE | `/api/maintenance/{id}` | Delete maintenance window |

### 4.4 Status

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | Aggregated status: `all_operational`, `degraded`, `partial_outage`, `major_outage` |
| GET | `/api/stats` | Uptime % per endpoint over 7d, 30d |

### 4.5 Email Config

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/config/smtp` | Get SMTP config (password redacted) |
| PUT | `/api/config/smtp` | Update SMTP config |

### 4.6 Frontend

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serve `index.html` |
| GET | `/maintenance` | Serve `maintenance.html` |

Static assets served from `/static/` directory.

---

## 5. Scheduler Behavior

1. Every 60 seconds, APScheduler fires the `run_checks` job.
2. For each enabled endpoint not in an active maintenance window:
   a. Run the appropriate check (HTTP/TCP/PING) with the configured timeout.
   b. Record result in `check_history` with `success`, `response_time_ms`, `status_code`, `error_message`.
   c. If `success == False` and there is no open incident for this endpoint:
      - Create a new incident with `status='investigating'` and severity based on failure count.
      - Queue an email alert.
   d. If `success == True` and there is an open incident:
      - Auto-resolve the incident (set `resolved_at`).
3. Prune `check_history` rows older than 30 days after each run.

---

## 6. Email Alert Logic

- Alerts are sent via SMTP on incident creation (first failure) and optionally when resolved.
- Config via `PUT /api/config/smtp`:
  - `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `smtp_from`, `smtp_tls`
- Email contains: endpoint name, incident title, severity, description, start time, status page URL.
- `smtp_from` is the sender address shown in From/Reply-To.
- Email dispatch is non-blocking (async via `aiojobs` or similar).
- Alert suppression: no duplicate alerts for the same endpoint within 5 minutes.

---

## 7. File Structure

```
status-page/
├── SPEC.md
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, CORS, static mounts, startup/shutdown
│   ├── database.py          # SQLite connection, init_db(), get_db()
│   ├── models.py            # Pydantic models (Endpoint, Incident, MaintenanceWindow, CheckHistory, SMTPConfig)
│   ├── schemas.py           # Request/Response schemas for API
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── endpoints.py     # /api/endpoints routes
│   │   ├── incidents.py     # /api/incidents routes
│   │   ├── maintenance.py   # /api/maintenance routes
│   │   ├── status.py        # /api/status, /api/stats routes
│   │   └── config.py        # /api/config/smtp routes
│   ├── scheduler.py         # APScheduler setup, run_checks(), check_http(), check_tcp(), check_ping()
│   ├── emailer.py           # send_email(), build_incident_email(), SMTPClient
│   ├── history.py           # prune_old_history()
│   └── config.py            # AppConfig (from env vars / .env)
├── static/
│   ├── index.html           # Main status page (all endpoints + active incidents)
│   ├── maintenance.html     # Maintenance page
│   ├── style.css
│   ├── script.js
│   └── logo.svg
└── data/
    └── status.db            # SQLite DB (gitignored, created at runtime)
```

### `app/main.py` — FastAPI Entry Point
- Creates tables on startup via `init_db()`.
- Mounts `/static` → `static/`.
- Mounts `/` → `index.html` (SPA catch-all for frontend).
- Registers all routers under `/api`.
- Starts APScheduler on startup event; shuts down on shutdown event.
- CORS allows all origins (internal use only).

### `app/database.py` — SQLite Setup
- Uses `sqlite3` with `check_same_thread=False`.
- `init_db()` creates tables if not exist.
- `get_db()` yields connection rows as dicts.

### `app/models.py` — Pydantic Models
- `Endpoint`, `Incident`, `MaintenanceWindow`, `CheckHistory`, `SMTPConfig` — data classes with type annotations.
- Used internally and for serialization.

### `app/schemas.py` — API Schemas
- FastAPI `BaseModel` subclasses for request bodies and response payloads.

### `app/routers/` — Route Modules
- Each module exposes a router; registered in `main.py`.

### `app/scheduler.py` — Monitoring Jobs
- `run_checks()` — main job, iterates endpoints, runs checks, handles incidents.
- `check_http(url, timeout, expected_status)` → `CheckResult`.
- `check_tcp(host, port, timeout)` → `CheckResult`.
- `check_ping(host, timeout)` → `CheckResult`.
- Uses `httpx` for HTTP/TCP, `ping3` for ping.

### `app/emailer.py` — Email Dispatch
- `SMTPClient` wraps SMTP connection.
- `send_alert_email(endpoint, incident)` constructs and sends the email.
- All email ops are async.

### `app/config.py` — Configuration
- Reads from environment: `DATABASE_URL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `APP_URL`.
- Defaults for home lab use.

### `static/index.html` — Status Page
- Header: system name, current overall status badge.
- Endpoint list: name, status indicator (green/yellow/red), response time.
- Active incidents section: title, severity badge, started time, description.
- Auto-refreshes every 30 seconds via `fetch('/api/status')` + `fetch('/api/endpoints')`.
- Maintenance banner at top if any active maintenance window.

### `static/maintenance.html` — Maintenance Page
- Lists upcoming and ongoing maintenance windows.
- Simple table: endpoint, title, window start/end, status.

---

## 8. Configuration (Environment Variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `data/status.db` | SQLite DB path |
| `CHECK_INTERVAL` | `60` | Seconds between checks |
| `HISTORY_RETENTION_DAYS` | `30` | Days to keep check history |
| `SMTP_HOST` | `smtp.example.com` | SMTP server |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | `` | SMTP username |
| `SMTP_PASSWORD` | `` | SMTP password |
| `SMTP_FROM` | `statuspage@example.com` | From address |
| `SMTP_TLS` | `true` | Use TLS |
| `APP_URL` | `http://localhost:8000` | Public URL for email links |
| `ALERT_COOLDOWN_MINUTES` | `5` | Suppress duplicate alerts |

---

## 9. Docker Deployment

### `Dockerfile`
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY static/ ./static/
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### `docker-compose.yml`
```yaml
version: '3.8'
services:
  statuspage:
    build: .
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    environment:
      - DATABASE_URL=data/status.db
      - SMTP_HOST=${SMTP_HOST}
      - SMTP_PORT=${SMTP_PORT}
      - SMTP_USER=${SMTP_USER}
      - SMTP_PASSWORD=${SMTP_PASSWORD}
      - SMTP_FROM=${SMTP_FROM}
```

---

## 10. Overall Status Algorithm

`GET /api/status` returns aggregate status:
1. If any unresolved incident with `severity=critical` → `major_outage`
2. Else if any unresolved incident with `severity=major` → `partial_outage`
3. Else if any unresolved incident with `severity=minor` → `degraded`
4. Else if any endpoint is in a maintenance window → `maintenance`
5. Else → `all_operational`

Status reflects the worst active condition.

---

## 11. Dependencies (`requirements.txt`)

```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
pydantic>=2.5.0
httpx>=0.27.0
ping3>=4.0.0
apscheduler>=3.10.0
aiosmtplib>=3.0.0
python-dotenv>=1.0.0
jinja2>=3.1.0
```