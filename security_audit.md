# Security Audit — Status Page

> Generated: 2026-05-31

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| fastapi | >=0.110.0 | Web framework |
| uvicorn[standard] | >=0.27.0 | ASGI server |
| pydantic | >=2.5.0 | Data validation |
| httpx | >=0.27.0 | HTTP client (endpoint checks) |
| ping3 | >=4.0.0 | ICMP ping |
| apscheduler | >=3.10.0 | Background scheduler |
| aiosmtplib | >=3.0.0 | SMTP email |
| python-dotenv | >=1.0.0 | Env config |
| jinja2 | >=3.1.0 | Templating |

---

## Vulnerability 1: SSRF — Server-Side Request Forgery ⚠️ HIGH

**Location:** `app/monitor.py` — `check_http()`, `check_tcp()`, `check_ping()`

**Issue:** User-supplied URLs and hosts are passed directly to `httpx` and `ping3` without validation. An attacker with admin access to the API could specify internal/infrastructure addresses:

- `http://169.254.169.254/latest/meta-data/` — AWS metadata
- `http://localhost/` — local services
- `http://10.0.0.1/` — internal network
- `http://192.168.50.1/` — router/admin panels

The app performs these requests **server-side**, potentially revealing internal service data.

**Patched check_http():**
```python
from urllib.parse import urlparse

def check_http(url: str, timeout: int, expected_status: int) -> CheckResult:
    parsed = urlparse(url)
    # Block private/loopback hosts
    blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
    if parsed.hostname in blocked_hosts:
        return CheckResult(success=False, error_message="Host not allowed")
    # Block private IP ranges
    # (extend with ipaddress module checks)
```

**Recommended fixes:**
1. **Allowlist** permitted URL schemes (`http`, `https` only)
2. **Blocklist** private IP ranges: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`, `169.254.0.0/16` (link-local), IPv6 equivalents
3. **Blocklist** cloud metadata endpoints: `169.254.169.254`
4. **Blocklist** bare hostname shortcuts that resolve to localhost
5. Use `httpx` timeout and avoid following redirects to untrusted hosts

---

## Vulnerability 2: Blind SSRF via Redirects

**Location:** `app/monitor.py` — `check_tcp()`

**Issue:** `httpx` follows HTTP redirects by default. A malicious endpoint could redirect to `http://169.254.169.254/...` on a cloud instance.

**Fix:** Disable redirects for httpx client:
```python
with httpx.Client(timeout=timeout, follow_redirects=False) as client:
```

---

## Vulnerability 3: Unrestricted CORS + No Authentication ⚠️ MEDIUM

**Location:** `app/main.py` — `CORSMiddleware`

```python
allow_origins=["*"],
allow_credentials=True,
```

**Issue:** The entire API is open to any origin with credentials. No authentication is required for any endpoint — anyone who can reach the server can:
- Read/modify/delete all endpoints
- Create/delete all incidents
- Read SMTP credentials (password redacted, but config visible)
- Trigger maintenance windows

**Context:** This is acceptable **only if** the status page is on an isolated internal network not exposed externally, and the admin panel is accessed via SSH tunnel.

**Recommended fixes:**
1. Add an `ADMIN_SECRET` env var and check it in a middleware
2. Restrict CORS to known origins
3. Add IP allowlisting at the Docker/network level

---

## Vulnerability 4: SMTP Password Stored in Plaintext ⚠️ LOW

**Location:** `app/routers/config.py`, `app/database.py` — `smtp_config` table

**Issue:** SMTP password is stored in the SQLite DB without encryption.

**Recommended fixes:**
1. Encrypt the password at rest (e.g., using `cryptography` Fernet)
2. Store only an encrypted version; decrypt at runtime
3. Alternatively: use environment variables only for SMTP password, don't persist to DB

---

## Vulnerability 5: SQL Injection — ✅ SAFE

**Finding:** All SQL queries throughout the codebase use **parameterized queries** with `?` placeholders and tuple values:

```python
conn.execute("SELECT * FROM endpoints WHERE id = ?", (endpoint_id,))
conn.execute("UPDATE endpoints SET {set_clause} WHERE id = ?", (*values, id))
```

The dynamic SET clause in `update_endpoint()` is built from Pydantic model keys (`data.model_dump(...)`), not raw user input. This is safe.

---

## Vulnerability 6: Input Spoofing in Incident/Description Fields — ✅ SAFE (with note)

**Finding:** User-supplied strings (titles, descriptions, endpoint names) are rendered in HTML via `escapeHtml()` in `admin.js`, which creates a proper text node — XSS is prevented.

However, these fields are **not sanitized** before being stored in the DB or before being inserted into the HTML email body in `emailer.py`. A stored XSS via `description` field would only fire in email clients (which have their own sanitization), not in the browser admin panel because `escapeHtml()` is applied on render.

---

## Vulnerability 7: Ping Check — Potential Firewall/Ethical Concern

**Location:** `app/monitor.py` — `check_ping()`

**Issue:** The `ping3` library sends ICMP (ping) packets. On some systems, sending pings requires `sudo`. If running inside a Docker container without `--cap-add NET_RAW`, ping will fail. If it works, the app can be used to ping any IP from the server — a minor risk on its own, but combined with SSRF, makes internal network enumeration easier.

**Recommendation:** Document that ping checks require elevated privileges and may be blocked by Docker.

---

## Vulnerability 8: No Rate Limiting

**Finding:** No rate limiting on any API endpoint. An attacker with access could flood the API with requests to create incidents or endpoints.

**Recommendation:** Add rate limiting middleware (e.g., `slowapi`).

---

## Summary Table

| Vulnerability | Severity | Status |
|---------------|----------|--------|
| SSRF (URL/host) | HIGH | ❌ Not mitigated |
| Blind SSRF via redirects | HIGH | ❌ Not mitigated |
| CORS wide open + no auth | MEDIUM | ❌ Not mitigated (internal use only) |
| SMTP password in plaintext | LOW | ❌ Not mitigated |
| SQL Injection | N/A | ✅ Safe |
| XSS in admin panel | N/A | ✅ Safe (escapeHtml) |
| XSS in emails | LOW | ⚠️ Partial (email client sanitization varies) |
| Ping / ICMP | INFO | ℹ️ Note only |
| No rate limiting | LOW | ❌ Not mitigated |

---

## Recommended Priority Fixes

1. **Immediate:** Add SSRF protection — block private IPs, link-local, cloud metadata IPs from `url` and `host` inputs
2. **Immediate:** Set `follow_redirects=False` on httpx client
3. **Soon:** Add `ADMIN_SECRET` env var for API authentication
4. **Soon:** Encrypt SMTP password at rest
5. **Nice-to-have:** Add rate limiting, restrict CORS

---

*Audit performed on 2026-05-31. Re-audit after any changes to router logic, monitor logic, or new dependencies.*
