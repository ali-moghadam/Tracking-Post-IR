# Iran Post Tracking API — Python / FastAPI

A production-ready Python port of the Node.js `server.js` scraping proxy for [tracking.post.ir](https://tracking.post.ir/).

## Stack

| Layer | Library |
|---|---|
| Web framework | FastAPI |
| ASGI server | Uvicorn |
| HTTP client | **curl_cffi** (Chrome TLS impersonation) |
| HTML parsing | BeautifulSoup4 + lxml |
| Config | pydantic-settings + python-dotenv |

> **Why curl_cffi?**  
> `tracking.post.ir` performs server-side TLS fingerprinting (JA3/JA4).  
> Python's built-in `ssl` module (and `httpx` / `requests` built on top of it) produce a non-browser ClientHello that the server silently drops — `curl` works because BoringSSL sends a browser-identical handshake.  
> `curl_cffi` embeds libcurl compiled with BoringSSL and exposes an `impersonate=` flag that replays an exact Chrome, Safari, or Firefox TLS profile, bypassing the fingerprint check transparently.

---

## Project Structure

```
app/
├── main.py              # App factory + entry point
├── api/
│   └── routes.py        # GET /health  POST /api/track
├── services/
│   └── scraper_service.py  # GET → POST → parse pipeline
├── models/
│   └── schemas.py       # Pydantic request/response models
├── core/
│   ├── config.py        # Environment-based settings
│   └── logging.py       # Logging setup
tests/
└── test_scraper.py      # Parser unit tests
```

---

## Quick Start

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env if you need to change PORT, TIMEOUT_SECONDS, etc.
```

### 3. Run

```bash
uvicorn app.main:app --host 0.0.0.0 --port 3001 --reload
```

Or via Python directly:

```bash
python -m app.main
```

---

## PyCharm Run Configuration

1. Open **Run → Edit Configurations**.
2. Click **+** → **Python**.
3. Set **Script path** to `app/main.py`  
   *or* use **Module name**: `uvicorn` with **Parameters**: `app.main:app --host 0.0.0.0 --port 3001 --reload`.
4. Set **Working directory** to the project root.
5. Click **OK** and press ▶.

The interactive API docs will be available at:  
`http://localhost:3001/docs`

---

## Docker

```bash
# Build and start
docker compose up --build

# Stop
docker compose down
```

---

## API Reference

### `GET /health`

```json
{
  "status": "ok",
  "ts": "2026-05-12T10:00:00+00:00",
  "mode": "web-scraper"
}
```

---

### `POST /api/track`

**Request**

```json
{
  "trackingCode": "12345678901234567890"
}
```

**Successful response**

```json
{
  "success": true,
  "tracking_code": "12345678901234567890",
  "status": "تحویل مرسوله",
  "receiver_name": "علی محمدی",
  "origin": "تهران",
  "destination": "اصفهان",
  "last_update": "1403/02/10 - 14:30",
  "is_delivered": true,
  "events": [
    {
      "date": "1403/02/10 - 14:30",
      "location": "اصفهان",
      "status": "تحویل مرسوله"
    }
  ],
  "raw_html_parsed": true,
  "error": null
}
```

**Error responses**

| HTTP | Reason |
|---|---|
| 400 | Invalid / missing tracking code |
| 502 | Scraping failed (network, timeout, blocked) |

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PORT` | `3001` | Listen port |
| `HOST` | `0.0.0.0` | Bind address |
| `DEBUG` | `false` | Enable debug logging + uvicorn reload |
| `TRACKING_URL` | `https://tracking.post.ir/` | Target URL |
| `TIMEOUT_SECONDS` | `20` | HTTP timeout per request |
| `MAX_RETRIES` | `2` | GET retries on failure |
| `RETRY_SLEEP_SECONDS` | `1.5` | Seconds between retries |
| `IMPERSONATE` | `chrome124` | curl_cffi TLS profile (`chrome124`, `chrome120`, `safari17_0`, …) |

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Suggested Improvements

1. **Rate limiting** — add `slowapi` or a Redis-backed rate limiter to avoid being blocked.
2. **Response caching** — cache successful results for a few minutes (e.g. with `aiocache`) to reduce scraping load.
3. **Proxy rotation** — pass proxies to `httpx.AsyncClient` to distribute requests across IPs.
4. **Retry with exponential back-off** — replace the fixed sleep with `tenacity` for smarter retry logic.
5. **Metrics** — add Prometheus metrics via `prometheus-fastapi-instrumentator`.
6. **CI/CD** — add a GitHub Actions workflow that runs `pytest` on every push.

