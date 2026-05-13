# Iran Post Tracking API

A production-ready **FastAPI** scraping proxy for [tracking.post.ir](https://tracking.post.ir/).  
It accepts an Iran Post tracking code and returns a fully structured JSON object containing shipment status, timeline events, origin, destination, and delivery state — without exposing any browser dependency to the caller.

### Key Features

- 🔍 **Real browser simulation** — Uses `curl_cffi` to replay Chrome's exact TLS/JA3 fingerprint, bypassing the bot-detection that silently drops standard Python HTTP clients.
- 📦 **Structured response** — Parses raw ASP.NET postback HTML with BeautifulSoup and returns clean, typed JSON.
- 🔄 **Automatic retry** — Configurable retry count and sleep interval on transient GET failures.
- 🐛 **Debug endpoint** — Exposes raw scraped HTML for rapid selector debugging.
- 🐳 **Docker-ready** — Ships with a `Dockerfile` and `docker-compose.yml`, including a liveness health-check.
- ☁️ **Liara-compatible** — Includes `liara.json` for one-command deployment on [Liara](https://liara.ir/).

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Framework | FastAPI 0.111+ |
| ASGI Server | Uvicorn (with standard extras) |
| HTTP / TLS | curl_cffi 0.7+ (Chrome JA3/JA4 impersonation via libcurl + BoringSSL) |
| HTML Parsing | BeautifulSoup4 4.12+ with lxml backend |
| Data Validation | Pydantic v2 · pydantic-settings |
| Config | python-dotenv |
| Testing | pytest 8+ · pytest-asyncio 0.23+ |
| Containerisation | Docker · Docker Compose v3.9 |
| Deployment | Liara (PaaS) |
| Database | None (stateless scraping proxy) |
| Authentication | None (open API — protect at gateway/firewall level) |
| Cache | None |
| Task Queue | None |

> **Why `curl_cffi` instead of `httpx` or `requests`?**  
> `tracking.post.ir` performs server-side TLS fingerprinting (JA3/JA4). Python's built-in `ssl` module — and HTTP clients built on top of it — produce a non-browser `ClientHello` the server silently drops. `curl_cffi` embeds libcurl compiled with BoringSSL and exposes an `impersonate=` flag that replays an exact Chrome TLS profile, bypassing the fingerprint check transparently.

---

## Project Structure

```
Tracking-Post-IR/
├── main.py                  # Root entry point — delegates to uvicorn (used by PaaS runners)
├── Dockerfile               # Slim Python 3.12 image; non-root user; exposes port 3001
├── docker-compose.yml       # Single-service compose with liveness health-check
├── liara.json               # Liara PaaS deployment descriptor
├── requirements.txt         # Python dependencies
└── app/
    ├── main.py              # FastAPI application factory (create_app), CORS, error handlers
    ├── api/
    │   └── routes.py        # All HTTP endpoints: /, /health, /api/track, /api/debug
    ├── core/
    │   ├── config.py        # Settings class (pydantic-settings, reads .env)
    │   └── logging.py       # Structured stdout logging setup
    ├── models/
    │   └── schemas.py       # Pydantic request/response models
    ├── services/
    │   └── scraper_service.py  # Full GET → POST → parse scraping pipeline
    ├── middleware/          # Reserved for future middleware (currently empty)
    └── utils/               # Reserved for shared utilities (currently empty)
tests/
└── test_scraper.py          # Unit tests for the HTML parser (no network calls)
```

---

## Installation

### Prerequisites

- Python **3.12+**
- `pip`
- `libcurl4` shared library — required at runtime by `curl_cffi` on Linux (installed automatically in Docker)

### 1 — Clone the repository

```bash
git clone <repository-url>
cd Tracking-Post-IR
```

### 2 — Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 3 — Install dependencies

```bash
pip install -r requirements.txt
```

> **macOS:** `curl_cffi` ships pre-built wheels; no compiler is needed.  
> **Linux:** Ensure `libcurl4` is present — `sudo apt-get install -y libcurl4`.

### 4 — Configure environment variables

Create a `.env` file in the project root (all variables are optional — defaults are production-safe):

```dotenv
PORT=3001
HOST=0.0.0.0
DEBUG=false
TRACKING_URL=https://tracking.post.ir/
TIMEOUT_SECONDS=20.0
MAX_RETRIES=2
RETRY_SLEEP_SECONDS=1.5
IMPERSONATE=chrome124
```

### 5 — Start the server

```bash
python main.py
```

Or directly via uvicorn:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 3001
```

---

## Environment Variables

All variables are read from `.env` (or from the process environment). None are required — the defaults work out of the box.

| Variable | Description | Default | Required |
|---|---|---|---|
| `PORT` | TCP port the server listens on | `3001` | No |
| `HOST` | Bind address | `0.0.0.0` | No |
| `DEBUG` | Enables uvicorn hot-reload and DEBUG log level | `false` | No |
| `TRACKING_URL` | Base URL of the Iran Post tracking site | `https://tracking.post.ir/` | No |
| `TIMEOUT_SECONDS` | HTTP request timeout in seconds (applies to GET and POST separately) | `20.0` | No |
| `MAX_RETRIES` | Number of GET retry attempts on transient failure | `2` | No |
| `RETRY_SLEEP_SECONDS` | Seconds to sleep between retry attempts | `1.5` | No |
| `IMPERSONATE` | curl_cffi TLS impersonation target | `chrome124` | No |

Valid `IMPERSONATE` values: `chrome124`, `chrome120`, `chrome110`, `safari17_0`, and others listed in the [curl_cffi docs](https://curl-cffi.readthedocs.io/en/latest/impersonate.html).

---

## Running the Project

### Development mode

Enables hot-reload and verbose debug logging:

```bash
DEBUG=true uvicorn app.main:app --host 0.0.0.0 --port 3001 --reload
```

Or set `DEBUG=true` in `.env` and run:

```bash
python main.py
```

### Production mode

```bash
uvicorn app.main:app --host 0.0.0.0 --port 3001 --workers 4
```

### Docker mode

```bash
# Build and start (detached)
docker compose up --build -d

# Stream logs
docker compose logs -f

# Stop
docker compose down
```

The compose service is configured with:
- Port mapping: `3001:3001`
- Restart policy: `unless-stopped`
- Health-check: `GET /health` every 30 s, 10 s timeout, 3 retries, 10 s start period

### PyCharm

1. **Run → Edit Configurations → + → Python**
2. Set **Script path** to `main.py` (project root)  
   *or* use **Module name** `uvicorn` with **Parameters** `app.main:app --host 0.0.0.0 --port 3001 --reload`
3. Set **Working directory** to the project root → **OK** → ▶

---

## API Documentation

FastAPI generates interactive documentation automatically:

| UI | URL |
|---|---|
| Swagger UI (interactive) | [http://localhost:3001/docs](http://localhost:3001/docs) |
| ReDoc (read-only) | [http://localhost:3001/redoc](http://localhost:3001/redoc) |
| OpenAPI JSON schema | [http://localhost:3001/openapi.json](http://localhost:3001/openapi.json) |

---

## Authentication

**No authentication is implemented.** The API is open by default.

It is strongly recommended to place the service behind a reverse proxy or API gateway that enforces:
- IP allowlisting or API-key validation
- Rate limiting
- TLS termination

---

## API Endpoints

### Overview

| Method | Path | Tag | Description | Auth |
|---|---|---|---|---|
| `GET` | `/` | meta | API info and endpoint directory | None |
| `GET` | `/health` | meta | Liveness probe | None |
| `POST` | `/api/track` | tracking | Track a shipment; returns structured JSON | None |
| `POST` | `/api/debug` | debug | Returns raw HTML received from tracking.post.ir | None |

---

### `GET /`

Returns API metadata and a directory of all endpoints.

**Response `200 OK`**

```json
{
  "name": "Iran Post Tracking API",
  "version": "1.0.0",
  "status": "running",
  "endpoints": {
    "health": "GET  /health",
    "track":  "POST /api/track   body: {\"trackingCode\": \"...\"}",
    "debug":  "POST /api/debug   body: {\"trackingCode\": \"...\"}",
    "docs":   "GET  /docs"
  }
}
```

---

### `GET /health`

Liveness probe — always returns `200 OK` while the process is alive. Used by Docker Compose health-checks and load balancers.

**Response `200 OK`**

```json
{
  "status": "ok",
  "ts": "2026-05-13T10:30:00.123456+00:00",
  "mode": "web-scraper"
}
```

---

### `POST /api/track`

Submit a tracking code to Iran Post and receive a fully parsed, structured result.

**Request Body**

| Field | Type | Description | Validation |
|---|---|---|---|
| `trackingCode` | `string` | Iran Post shipment barcode | Exactly 20–24 digits, numeric only |

```json
{
  "trackingCode": "12345678901234567890"
}
```

**Response `200 OK` — successful tracking**

```json
{
  "success": true,
  "tracking_code": "12345678901234567890",
  "status": "تحویل مرسوله",
  "receiver_name": "علی محمدی",
  "origin": "تهران",
  "destination": "اصفهان",
  "last_update": "1403/02/20 - 14:35",
  "is_delivered": true,
  "events": [
    {
      "date": "1403/02/20 - 14:35",
      "location": "اداره پست اصفهان",
      "status": "تحویل مرسوله"
    },
    {
      "date": "1403/02/19 - 09:10",
      "location": "مرکز توزیع اصفهان",
      "status": "ورود به مرکز توزیع"
    }
  ],
  "raw_html_parsed": true,
  "error": null
}
```

**Response `200 OK` — tracking code not found**

```json
{
  "success": false,
  "tracking_code": "12345678901234567890",
  "status": "NOT_FOUND",
  "receiver_name": "",
  "origin": "",
  "destination": "",
  "last_update": "",
  "is_delivered": false,
  "events": [],
  "raw_html_parsed": true,
  "error": null
}
```

**Possible `status` values**

| Value | Meaning |
|---|---|
| *(Persian string)* | Latest event status text returned directly from Iran Post |
| `NOT_FOUND` | No records found for this tracking code |
| `NO_DATA` | Result panel missing; page content is unrecognised |
| `INVALID_CODE` | Iran Post returned a validation error for the barcode |
| `BLOCKED` | The scraper received a CAPTCHA / 403 / Access Denied response |

**HTTP error responses**

| Status | Cause |
|---|---|
| `400 Bad Request` | `trackingCode` is not a 20–24 digit numeric string |
| `502 Bad Gateway` | Upstream scrape failed (Iran Post unreachable, timeout, or returned no HTML) |

---

### `POST /api/debug`

Returns the **raw HTML** received from `tracking.post.ir` after form submission. Use this to diagnose empty results or broken selectors without needing a real browser.

**Request Body** — same as `/api/track`

```json
{
  "trackingCode": "12345678901234567890"
}
```

**Response `200 OK`** — `Content-Type: text/html`  
The full HTML page as a string (rendered directly in the browser for easy inspection).

**HTTP error responses**

| Status | Cause |
|---|---|
| `400` | Invalid tracking code format |
| `502` | Scrape returned no HTML |

---

## Usage Examples

### curl

```bash
# Track a shipment
curl -X POST http://localhost:3001/api/track \
  -H "Content-Type: application/json" \
  -d '{"trackingCode": "12345678901234567890"}'

# Liveness check
curl http://localhost:3001/health

# Debug — view raw HTML in terminal
curl -X POST http://localhost:3001/api/debug \
  -H "Content-Type: application/json" \
  -d '{"trackingCode": "12345678901234567890"}'
```

### Python (`requests`)

```python
import requests

BASE_URL = "http://localhost:3001"

response = requests.post(
    f"{BASE_URL}/api/track",
    json={"trackingCode": "12345678901234567890"},
)
data = response.json()

if data["success"]:
    print(f"Status      : {data['status']}")
    print(f"Delivered   : {data['is_delivered']}")
    print(f"Last update : {data['last_update']}")
    for event in data["events"]:
        print(f"  [{event['date']}] {event['location']} — {event['status']}")
else:
    print(f"Failed: {data.get('status')} / {data.get('error')}")
```

### JavaScript (`fetch`)

```javascript
const BASE_URL = "http://localhost:3001";

async function trackShipment(trackingCode) {
  const response = await fetch(`${BASE_URL}/api/track`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ trackingCode }),
  });

  const data = await response.json();

  if (data.success) {
    console.log("Status:", data.status);
    console.log("Delivered:", data.is_delivered);
    data.events.forEach((e) =>
      console.log(`[${e.date}] ${e.location} — ${e.status}`)
    );
  } else {
    console.error("Error:", data.status, data.error);
  }
}

trackShipment("12345678901234567890");
```

---

## Error Handling

All error responses share a consistent JSON envelope:

```json
{
  "success": false,
  "error": "<error message or Pydantic error list>"
}
```

### HTTP Status Codes

| Code | Scenario |
|---|---|
| `200` | Request processed (inspect the `success` field for the logical outcome) |
| `400` | Request body failed validation |
| `502` | Upstream scraping failure |

### Validation Error (`400`)

Returned when `trackingCode` is not a 20–24 digit numeric string:

```json
{
  "success": false,
  "error": [
    {
      "type": "value_error",
      "loc": ["body", "trackingCode"],
      "msg": "Value error, Invalid tracking code — must be 20–24 digits",
      "input": "ABC123"
    }
  ]
}
```

### Logical Failure (`200` with `success: false`)

Upstream issues (not found, blocked, invalid barcode) are returned as HTTP `200` with `success: false` and a `status` field indicating the cause. This mirrors standard scraping proxy conventions and allows callers to distinguish transport errors from application-level results.

---

## Testing

Tests use **pytest** and target the HTML parser layer directly — no network calls are made.

### Run all tests

```bash
pytest
```

### Run with verbose output

```bash
pytest -v
```

### Run with coverage report

```bash
pip install pytest-cov
pytest --cov=app --cov-report=term-missing
```

### Test cases

| Test | Scenario | Assertion |
|---|---|---|
| `test_blocked_returns_blocked_error` | 403 / CAPTCHA page title | `error == "BLOCKED"` |
| `test_not_found_phrase` | Persian "not found" text in body | `status == "NOT_FOUND"` |
| `test_no_data` | Page with no recognisable content | `status == "NO_DATA"` |
| `test_invalid_barcode_alert_inside_panel` | Alert inside `#pnlResult` | `status == "INVALID_CODE"` |
| `test_invalid_barcode_alert_no_panel` | Alert without result panel | `error` contains Persian message |

---

## Deployment

### Docker (recommended for production)

```bash
# Build image
docker build -t tracking-post-ir .

# Run container
docker run -d \
  --name tracking-post-ir \
  -p 3001:3001 \
  --env-file .env \
  --restart unless-stopped \
  tracking-post-ir
```

### Docker Compose

```bash
docker compose up -d
```

### Liara PaaS

The `liara.json` descriptor configures the platform automatically:

```json
{
  "platform": "python",
  "port": 3001
}
```

Deploy with the [Liara CLI](https://docs.liara.ir/cli/install):

```bash
liara deploy
```

### Gunicorn + Uvicorn workers (bare-metal / VPS)

```bash
pip install gunicorn
gunicorn app.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 4 \
  --bind 0.0.0.0:3001
```

> Place Nginx or Caddy in front for TLS termination, request buffering, and rate limiting.

---

## Security Notes

| Concern | Current State | Recommendation |
|---|---|---|
| **Secret management** | No secrets required; all config values are non-sensitive defaults | Keep `.env` out of version control (add to `.gitignore`); use Docker secrets or a secrets manager in production |
| **Authentication** | None | Add API-key or OAuth2 at the reverse-proxy / API-gateway layer |
| **Rate limiting** | Not implemented in-app | Apply `slowapi` in-process or enforce at Nginx/Caddy/gateway |
| **CORS** | Wildcard (`*`) | Restrict `allow_origins` in `app/main.py` for production deployments |
| **Non-root Docker user** | ✅ Container runs as `appuser` | — |
| **TLS to upstream** | curl_cffi validates certificates by default | Do not disable certificate verification |
| **Dependency pinning** | Minimum-version bounds (`>=`) | Pin exact versions (`==`) for fully reproducible production builds |

---

## Suggested Improvements

1. **Rate limiting** — add [`slowapi`](https://github.com/laurentS/slowapi) or a Redis-backed limiter to avoid being blocked by the upstream site.
2. **Response caching** — cache successful results for a few minutes (e.g. with `aiocache`) to reduce scraping load.
3. **Proxy rotation** — route requests through a pool of residential proxies to distribute IPs.
4. **Exponential back-off** — replace the fixed sleep with [`tenacity`](https://tenacity.readthedocs.io/) for smarter retry logic.
5. **Metrics** — add Prometheus metrics via [`prometheus-fastapi-instrumentator`](https://github.com/trallnag/prometheus-fastapi-instrumentator).
6. **CI/CD** — add a GitHub Actions workflow that runs `pytest` on every push and builds the Docker image on merge to `main`.

---

## Contributing

1. Fork the repository and create a feature branch:
   ```bash
   git checkout -b feature/my-improvement
   ```
2. Install dependencies and confirm a green baseline:
   ```bash
   pip install -r requirements.txt
   pytest
   ```
3. Make your changes, add or update tests, and ensure `pytest` passes.
4. Open a Pull Request with a clear description of the change and its motivation.

**Code style:** Follow PEP 8. Use type annotations throughout. Document non-obvious scraping logic inline.

---

## License

No `LICENSE` file was detected in this repository. All rights reserved unless stated otherwise by the repository owner.

---

## Maintainers

No explicit maintainer information was found in the codebase. Please refer to the repository's contributor history or contact the repository owner directly.
