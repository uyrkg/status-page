# Self-Hosted Status Page

> ⚠️ **Disclaimer:** This project was "vibe coded" — built with AI assistance. Use at your own risk. Not production-hardened.

A lightweight internal status page for home lab environments. Monitors endpoints, tracks incidents, and sends email alerts on failures.

```
┌──────────────────────────────────────────────────────┐
│                    Status Page                         │
│                                                       │
│   ┌─────────────┐   ┌─────────────┐  ┌───────────┐  │
│   │  Endpoint 1  │   │  Endpoint 2  │  │     ...    │  │
│   │    ● OK     │   │  ⚠ DEGRADED  │  │            │  │
│   └─────────────┘   └─────────────┘  └───────────┘  │
│                                                       │
│   Active Incidents: 1  │  Last check: 30s ago       │
└──────────────────────────────────────────────────────┘
```

## Features

- HTTP / TCP / Ping monitoring with configurable intervals
- Automatic incident creation and resolution
- Maintenance window scheduling
- Email alerts via SMTP
- 30-day check history retention
- Dark-themed status dashboard
- Admin panel for managing endpoints and incidents

---

## Prerequisites

- **Docker** (for containerized install)
- **Python 3.11+** (for manual install)
- **SMTP server** (Gmail, SendGrid, Mailgun, self-hosted, etc.)

---

## Install: Docker (Recommended)

### 1. Install Docker

<details open>
<summary><b>Linux (Ubuntu/Debian)</b></summary>

```bash
# Update package index
sudo apt update

# Install prerequisites
sudo apt install -y ca-certificates curl

# Add Docker's GPG key
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add Docker repo
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add your user to the docker group (avoid needing sudo)
sudo usermod -aG docker $USER
newgrp docker
```

Verify Docker is running:
```bash
docker run hello-world
```

</details>

<details>
<summary><b>macOS</b></summary>

1. Download **Docker Desktop** from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop)
2. Install the `.dmg` file
3. Launch **Docker Desktop** from Applications
4. Wait until the whale icon in the menu bar stabilizes

Verify in terminal:
```bash
docker --version
docker run hello-world
```

> **Note:** Docker Desktop for Mac includes Docker Engine, Docker CLI, and Docker Compose — no separate installs needed.

</details>

<details>
<summary><b>Windows</b></summary>

1. Download **Docker Desktop** from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop)
2. Run the installer (`.exe`)
3. Enable **WSL 2** when prompted (recommended) or use Hyper-V
4. Restart your machine
5. Launch **Docker Desktop** from the Start menu

Verify in PowerShell:
```powershell
docker --version
docker run hello-world
```

> **Note:** For Windows 10 Home, Docker Desktop requires WSL 2. Run `wsl --install` in an admin PowerShell first, then install Docker Desktop.

</details>

---

### 2. Clone or download the project

```bash
git clone https://github.com/uyrkg/status-page.git
cd status-page
```

Or download and extract the ZIP from GitHub.

---

### 3. Configure environment variables

Create a `.env` file in the project root:

```bash
cp .env.example .env
# Then edit .env with your favourite editor
```

Minimum config needed:

```env
# App
APP_URL=http://localhost:8000

# SMTP (required for email alerts)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=statuspage@yourdomain.com
SMTP_TLS=true

# Optional overrides
# CHECK_INTERVAL=60
# HISTORY_RETENTION_DAYS=30
# ALERT_COOLDOWN_MINUTES=5
```

> **Gmail SMTP:** Use an [App Password](https://support.google.com/accounts/answer/185833) instead of your real password. Enable 2FA first, then create an App Password under Google Account → Security → App passwords.

> **Other SMTP providers (SendGrid, Mailgun, etc.):** Use the SMTP credentials from your provider's dashboard. The port and TLS settings depend on your provider.

---

### 4. Start the container

```bash
# Create the data directory
mkdir -p data

# Start in detached mode
docker-compose up -d

# Check logs
docker logs -f status-page-statuspage-1
```

---

### 5. Access the status page

| Page | URL |
|------|-----|
| **Status page** | http://localhost:8000 |
| **Admin panel** | http://localhost:8000/admin.html |

---

## Install: Manual (pip)

Requires Python 3.11+.

```bash
# Clone the repo
git clone https://github.com/uyrkg/status-page.git
cd status-page

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .\.venv\Scripts\Activate.ps1   # Windows PowerShell

# Install dependencies
pip install -r requirements.txt

# Create data directory
mkdir -p data

# Set environment variables (Linux/macOS)
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=your-email@gmail.com
export SMTP_PASSWORD=your-app-password
export SMTP_FROM=statuspage@yourdomain.com
export APP_URL=http://localhost:8000

# Or on Windows (PowerShell)
# $env:SMTP_HOST="smtp.gmail.com"
# ...

# Run the server
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Access at http://localhost:8000

---

## Post-Install Setup

### Adding your first endpoint

1. Open the admin panel: http://localhost:8000/admin.html
2. Click **Add Endpoint**
3. Fill in the fields:

```
Name:        My Website
Check Type:  HTTP
URL:         https://example.com
Expected:    200
Interval:    60 seconds
Timeout:     5 seconds
Enabled:     ☑
```

4. Click **Save**

The endpoint will be checked every 60 seconds. Its status appears on the main status page.

### Endpoint types

**HTTP check** — monitors a URL and verifies the HTTP status code:
```
Name:       Example Website
Check Type: http
URL:        https://example.com
Expected:   200
```

**TCP check** — verifies a TCP port is open:
```
Name:       SSH Server
Check Type: tcp
Host:       192.168.1.100
Port:       22
```

**Ping check** — ICMP ping an IP or hostname:
```
Name:       Router
Check Type: ping
Host:       192.168.1.1
```

### Configuring SMTP

1. Go to the admin panel → **Settings** or **Config**
2. Enter your SMTP details (or set via environment variables before starting)
3. Click **Test** to send a test email

If no test button exists, create an incident manually — it will trigger an alert email if SMTP is configured correctly.

### Checking the logs

```bash
# Docker
docker logs status-page-statuspage-1

# Manual
# Output appears in the terminal running uvicorn
```

### Stopping

```bash
# Docker
docker-compose down

# Manual
# Press Ctrl+C in the terminal running uvicorn
```

### Upgrading

```bash
# Docker
git pull origin master
docker-compose down
docker-compose build
docker-compose up -d

# Manual
git pull origin master
source .venv/bin/activate
pip install -r requirements.txt
# Restart uvicorn
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Docker Container                    │
│                                                      │
│  ┌──────────┐   ┌──────────┐   ┌─────────────────┐ │
│  │  FastAPI  │   │ Scheduler│   │  HTML/CSS       │ │
│  │  REST API │◄──│ (60s)    │   │  Admin Panel    │ │
│  └────┬─────┘   └────┬─────┘   └────────┬────────┘ │
│       │              │                   │          │
│       └──────────────┼───────────────────┘          │
│                      ▼                              │
│               ┌──────────────┐                       │
│               │   SQLite     │                       │
│               │  status.db   │                       │
│               └──────────────┘                       │
└─────────────────────────────────────────────────────┘
```

The app runs as a single container with:
- **FastAPI** — REST API + static file server
- **APScheduler** — background checker every 60s
- **SQLite** — persistent storage (endpoints, incidents, history)
- **SMTP** — async email alerts on failures

---

## API Reference

### Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/endpoints` | List all endpoints |
| POST | `/api/endpoints` | Create endpoint |
| GET | `/api/endpoints/{id}` | Get endpoint |
| PUT | `/api/endpoints/{id}` | Update endpoint |
| DELETE | `/api/endpoints/{id}` | Delete endpoint |
| GET | `/api/endpoints/{id}/history` | Check history |

### Incidents
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/incidents` | List incidents |
| POST | `/api/incidents` | Create incident |
| PUT | `/api/incidents/{id}` | Update incident |
| DELETE | `/api/incidents/{id}` | Delete incident |
| POST | `/api/incidents/{id}/resolve` | Resolve incident |

### Maintenance
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/maintenance` | List windows |
| POST | `/api/maintenance` | Create window |
| PUT | `/api/maintenance/{id}` | Update window |
| DELETE | `/api/maintenance/{id}` | Delete window |

### Status
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | Overall status |
| GET | `/api/stats` | Uptime stats |

---

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `data/status.db` | SQLite DB path |
| `CHECK_INTERVAL` | `60` | Seconds between checks |
| `HISTORY_RETENTION_DAYS` | `30` | Days to keep history |
| `SMTP_HOST` | `smtp.example.com` | SMTP server |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | — | SMTP username |
| `SMTP_PASSWORD` | — | SMTP password |
| `SMTP_FROM` | `statuspage@example.com` | From address |
| `SMTP_TLS` | `true` | Use TLS |
| `APP_URL` | `http://localhost:8000` | Public URL for email links |
| `ALERT_COOLDOWN_MINUTES` | `5` | Suppress duplicate alerts |

---

## Troubleshooting

### Container won't start

```bash
# Check logs
docker logs status-page-statuspage-1

# Common causes:
# - Port 8000 already in use: change the port in docker-compose.yml
# - .env file missing: ensure it exists in the project root
```

### Emails not sending

1. Verify SMTP credentials in `.env`
2. For Gmail: ensure you're using an **App Password**, not your real password
3. Check the container logs for SMTP errors
4. Try sending a test email by creating a manual incident

### Endpoint shows "Unknown" status

The checker runs every 60 seconds. Wait up to 2 minutes after adding an endpoint for its first check to complete.

### Database errors

The SQLite DB is stored at `data/status.db`. If it gets corrupted:

```bash
rm data/status.db
# Restart the container — it will recreate the DB automatically
docker-compose restart
```

---

## License

MIT — do whatever you want with it.