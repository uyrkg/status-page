# Self-Hosted Status Page

A lightweight internal status page for home lab environments. Monitors endpoints, tracks incidents, and sends email alerts on failures.

## Features

- HTTP/TCP/Ping monitoring with configurable intervals
- Automatic incident creation and resolution
- Maintenance window scheduling
- Email alerts via SMTP
- 30-day check history retention
- Dark-themed status dashboard

## Quick Start

### Using Docker

```bash
# Clone or download the project
cd status-page

# Create data directory
mkdir -p data

# Start with docker-compose
docker-compose up -d

# Access the status page
#   Status page: http://localhost:8000
#   Admin panel: http://localhost:8000/admin.html
```

### Configuration

Create a `.env` file in the project root:

```env
SMTP_HOST=smtp.yourprovider.com
SMTP_PORT=587
SMTP_USER=your-username
SMTP_PASSWORD=your-password
SMTP_FROM=statuspage@yourdomain.com
APP_URL=http://statuspage.yourdomain.com
```

All configuration via environment variables (see below).

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `data/status.db` | SQLite DB path |
| `CHECK_INTERVAL` | `60` | Seconds between checks |
| `HISTORY_RETENTION_DAYS` | `30` | Days to keep check history |
| `SMTP_HOST` | `smtp.example.com` | SMTP server |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | (empty) | SMTP username |
| `SMTP_PASSWORD` | (empty) | SMTP password |
| `SMTP_FROM` | `statuspage@example.com` | From address |
| `SMTP_TLS` | `true` | Use TLS |
| `APP_URL` | `http://localhost:8000` | Public URL for email links |
| `ALERT_COOLDOWN_MINUTES` | `5` | Suppress duplicate alerts |

## API Endpoints

### Endpoints
- `GET /api/endpoints` - List all endpoints
- `POST /api/endpoints` - Create endpoint
- `GET /api/endpoints/{id}` - Get endpoint detail
- `PUT /api/endpoints/{id}` - Update endpoint
- `DELETE /api/endpoints/{id}` - Delete endpoint
- `GET /api/endpoints/{id}/history` - Get check history

### Incidents
- `GET /api/incidents` - List all incidents
- `POST /api/incidents` - Create incident
- `PUT /api/incidents/{id}` - Update incident
- `DELETE /api/incidents/{id}` - Delete incident
- `POST /api/incidents/{id}/resolve` - Resolve incident

### Maintenance
- `GET /api/maintenance` - List maintenance windows
- `POST /api/maintenance` - Create maintenance window
- `PUT /api/maintenance/{id}` - Update maintenance window
- `DELETE /api/maintenance/{id}` - Delete maintenance window

### Status
- `GET /api/status` - Aggregated status
- `GET /api/stats` - Uptime statistics

### Config
- `GET /api/config/smtp` - Get SMTP config
- `PUT /api/config/smtp` - Update SMTP config

## Endpoint Types

### HTTP Check
```json
{
  "name": "Website",
  "check_type": "http",
  "url": "https://example.com",
  "expected_status": 200,
  "timeout": 5,
  "check_interval": 60
}
```

### TCP Check
```json
{
  "name": "SSH Server",
  "check_type": "tcp",
  "host": "192.168.1.100",
  "port": 22,
  "timeout": 5,
  "check_interval": 60
}
```

### Ping Check
```json
{
  "name": "Router",
  "check_type": "ping",
  "host": "192.168.1.1",
  "timeout": 5,
  "check_interval": 60
}
```

## Project Structure

```
status-page/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── README.md
├── app/
│   ├── main.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   ├── config.py
│   ├── scheduler.py
│   ├── emailer.py
│   ├── history.py
│   └── routers/
│       ├── endpoints.py
│       ├── incidents.py
│       ├── maintenance.py
│       ├── status.py
│       └── config.py
├── static/
│   ├── index.html
│   ├── maintenance.html
│   ├── admin.html
│   ├── admin.js
│   ├── style.css
│   └── script.js
└── data/
    └── status.db
```

## Building from Source

```bash
# Build the Docker image
docker build -t status-page .

# Run
docker run -d -p 8000:8000 -v ./data:/app/data --env-file .env status-page
```