# Iran Post Tracking API

Track Iranian Post shipments programmatically — get real-time status, location history, and delivery updates via a simple REST API.

> Bypasses Iran Post's bot-detection using Chrome TLS impersonation (`curl_cffi`), solves the site's image CAPTCHA locally with `ddddocr`, and returns clean structured JSON. No browser required.

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
// Request — `phone` is optional
{ "trackingCode": "12345678901234567890", "phone": "09123456789" }

// Success response
{
  "success": true,
  "tracking_code": "12345678901234567890",
  "status": "مرسوله  تحویل گیرنده گردیده است",
  "receiver_name": "علی مقدم",
  "origin": "مركزي،ساوه،نقطه مبادله شهرستان ساوه",
  "destination": "اصفهان،کاشان،نقطه مبادله پستی شهرستان کاشان",
  "last_update": "دوشنبه 29 تير ماه 1405 - 09:19",
  "is_delivered": true,
  "events": [
    {
      "date": "دوشنبه 29 تير ماه 1405 - 09:19",
      "location": "اصفهان،کاشان،نقطه مبادله پستی شهرستان کاشان",
      "status": "مرسوله  تحویل گیرنده گردیده است"
    }
  ],
  "error": null
}
```

`trackingCode` must be **20–24 digits**.

`phone` is the receiver's Iranian mobile number (`09xxxxxxxxx`, `+989xxxxxxxxx`, or
`989xxxxxxxxx` — all normalised) and is **optional**. Every field except `receiver_name`
is returned without it.

Iran Post puts `receiver_name` behind a phone gate — the results page asks for a mobile
number with *«برای مشاهده جزئیات شماره موبایل الزامی است»* and posts it back via
`CustomerMob`. This client implements that second postback, but **it is unverified**:
submitting a number that doesn't belong to the shipment changes the response by nothing
at all — no name, and no error either. Whether supplying the genuine receiver's number
reveals the name has not been confirmed. Treat `receiver_name` as best-effort; it comes
back empty in every case tested so far.

A failed lookup returns HTTP 200 with `"success": false` and a `status` explaining why:

| `status` | Meaning |
|---|---|
| `NOT_FOUND` | Iran Post has no record of this code |
| `INVALID_CODE` | Site rejected the code (includes the site's own message in `error`) |
| `NO_DATA` | Result panel came back empty |
| `CAPTCHA_FAILED` | CAPTCHA could not be solved within `MAX_RETRIES + 1` attempts |
| `BLOCKED` | Request was blocked by bot-detection |

On success, `status` is the live Persian status string from the shipment's latest event.

| HTTP | Cause |
|---|---|
| `400` | Invalid tracking code or phone format |
| `502` | Iran Post unreachable |

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
| `MAX_RETRIES` | `5` | Extra attempts after the first, mostly spent re-solving the CAPTCHA |
| `RETRY_SLEEP_SECONDS` | `1.5` | Delay between retries |
| `IMPERSONATE` | `chrome124` | TLS profile (`chrome124`, `safari17_0`, …) |
| `TRUECAPTCHA_USERID` | — | Optional [TrueCaptcha](https://truecaptcha.org) fallback solver |
| `TRUECAPTCHA_APIKEY` | — | Optional TrueCaptcha API key |
| `CAPSOLVER_API_KEY` | — | Optional [CapSolver](https://capsolver.com) key, for reCAPTCHA/hCaptcha |

No API keys are required. The CAPTCHA is solved locally and offline by `ddddocr`; the
TrueCaptcha and CapSolver settings are fallbacks that stay dormant unless you set them.

---

## How CAPTCHA Solving Works

`tracking.post.ir` guards its search form with a 4-digit image CAPTCHA. Each request:

1. `GET /` — collect the ASP.NET hidden fields (`__VIEWSTATE`, `__EVENTVALIDATION`, …)
   and detect the CAPTCHA.
2. Download the CAPTCHA image from `search.aspx?captcha=1` on the same session.
3. Solve it locally with `ddddocr`. The digits are dark navy on a light-blue background,
   overlaid with brightly coloured noise curves, so the image is rendered three ways —
   a navy colour mask cropped to the left of the frame, the untouched image, and a wider
   mask — and the results are majority-voted. Anything that isn't exactly 4 digits is
   discarded.
4. `POST /` — submit the form with the answer in `txtCaptcha`.

A wrong answer is *not* an HTTP error: the site returns 200 with an empty result panel.
That case is detected and the whole flow retries with a fresh CAPTCHA, up to
`MAX_RETRIES` times. If every attempt fails, the response is an explicit
`CAPTCHA_FAILED` — never a blank success.

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

Python 3.13 · FastAPI · Uvicorn · curl_cffi · BeautifulSoup4 · Pydantic v2 · ddddocr · Pillow · Docker

---

## Project Structure

```
app/
├── api/routes.py          # Endpoints
├── core/config.py         # Settings (env vars)
├── models/schemas.py      # Pydantic models
└── services/
    ├── scraper_service.py # GET → CAPTCHA → POST → parse pipeline
    └── captcha_service.py # CAPTCHA detection, image preprocessing, OCR
tests/
└── test_scraper.py
```
