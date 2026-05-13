# Iran Post Tracking API

Track Iranian Post shipments programmatically — get real-time status, location history, and delivery updates via a simple REST API.

> Bypasses Iran Post's bot-detection using Chrome TLS impersonation (`curl_cffi`) and returns clean structured JSON.

---

## API Documentation

| UI | URL |
|---|---|
| Swagger UI | [http://localhost:3001/docs](http://localhost:3001/docs) |
| ReDoc | [http://localhost:3001/redoc](http://localhost:3001/redoc) |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | API info |
| `GET` | `/health` | Liveness probe |
| `POST` | `/api/track` | Track a shipment |
| `POST` | `/api/debug` | Raw HTML response (debugging) |

### `POST /api/track`

```json
// Request
{ "trackingCode": "12345678901234567890" }

// Success response
{
  "success": true,
  "tracking_code": "12345678901234567890",
  "status": "تحویل مرسوله",
  "receiver_name": "علی مقدم",
  "origin": "تهران",
  "destination": "آیادان",
  "last_update": "1403/02/20 - 14:35",
  "is_delivered": true,
  "events": [
    { "date": "1403/02/20 - 14:35", "location": "اداره پست تهران", "status": "تحویل مرسوله" }
  ],
  "error": null
}
```

`trackingCode` must be **20–24 digits**. Possible `status` values: `NOT_FOUND`, `NO_DATA`, `INVALID_CODE`, `BLOCKED`, or a live Persian status string.

| HTTP | Cause |
|---|---|
| `400` | Invalid tracking code format |
| `502` | Iran Post unreachable or returned no data |

---

## Quick Start

```bash
git clone <repository-url> && cd Tracking-Post-IR
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py          # → http://localhost:3001
```

### Docker

```bash
docker compose up --build -d
```

### Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `PORT` | `3001` | Listen port |
| `HOST` | `0.0.0.0` | Bind address |
| `DEBUG` | `false` | Hot-reload + debug logs |
| `TIMEOUT_SECONDS` | `20.0` | Request timeout |
| `MAX_RETRIES` | `2` | GET retry attempts |
| `RETRY_SLEEP_SECONDS` | `1.5` | Delay between retries |
| `IMPERSONATE` | `chrome124` | TLS profile (`chrome124`, `safari17_0`, …) |

---

## Usage Examples

```bash
# curl
curl -X POST http://localhost:3001/api/track \
  -H "Content-Type: application/json" \
  -d '{"trackingCode": "12345678901234567890"}'
```

```python
# Python
import requests
r = requests.post("http://localhost:3001/api/track", json={"trackingCode": "12345678901234567890"})
print(r.json())
```

```js
// JavaScript
const res = await fetch("http://localhost:3001/api/track", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ trackingCode: "12345678901234567890" }),
});
console.log(await res.json());
```

---

## Testing

```bash
pytest -v
```

---

## CI / CD

A GitHub Actions workflow is included at `.github/workflows/ci.yml`:

| Trigger | Job | What it does |
|---|---|---|
| Every push / PR | `pytest` | Installs deps and runs the full test suite |
| Merge to `main` | `Docker build & push` | Builds the image and pushes to Docker Hub (runs only if tests pass) |

**Liara deployment** is handled via Liara's **native GitHub integration** (not GitHub Actions), because GitHub runners cannot reliably reach Liara's servers within the CLI timeout. Set it up once:  
Dashboard → your app → **Git** tab → connect repo → branch: `master` → Save.  
Liara will auto-deploy on every push to `master`.

**Required repository secrets** (Settings → Secrets → Actions):

| Secret | Description |
|---|---|
| `DOCKER_USERNAME` | Your Docker Hub username |
| `DOCKER_PASSWORD` | Your Docker Hub password or access token |

---

## Deployment

- **Liara PaaS:** `liara deploy` (configured via `liara.json`)
- **Gunicorn:** `gunicorn app.main:app --worker-class uvicorn.workers.UvicornWorker --workers 4 --bind 0.0.0.0:3001`

---

## Tech Stack

Python 3.12 · FastAPI · Uvicorn · curl_cffi · BeautifulSoup4 · Pydantic v2 · Docker

---

## Project Structure

```
app/
├── api/routes.py          # Endpoints
├── core/config.py         # Settings (env vars)
├── models/schemas.py      # Pydantic models
└── services/scraper_service.py  # GET → POST → parse pipeline
tests/
└── test_scraper.py
```
