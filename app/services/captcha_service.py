"""
services/captcha_service.py — CAPTCHA detection & solving (pure HTTP, no browser).

Supports:
  • Custom image CAPTCHA  (captcha-box  — solved via TrueCaptcha free API)
  • reCAPTCHA v2 / v3     (solved via CapSolver API)
  • hCaptcha              (solved via CapSolver API)

Environment variables (.env)
-----------------------------
TRUECAPTCHA_USERID  — TrueCaptcha user id  (https://truecaptcha.org — free 100/day)
TRUECAPTCHA_APIKEY  — TrueCaptcha api key
CAPSOLVER_API_KEY   — CapSolver key for reCAPTCHA/hCaptcha (optional)
"""
from __future__ import annotations

import asyncio
import base64
import io
import re
from typing import Literal

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

CAPSOLVER_BASE    = "https://api.capsolver.com"
TRUECAPTCHA_BASE  = "https://api.apitruecaptcha.org/one/gettext"

CaptchaType = Literal["image", "recaptchav2", "recaptchav3", "hcaptcha", "none"]


# ════════════════════════════════════════════════════════════════════
#  Detection  (raw HTML string)
# ════════════════════════════════════════════════════════════════════

def detect_captcha(html: str) -> tuple[CaptchaType, str]:
    """
    Scan raw HTML for known CAPTCHA widgets.
    Returns (captcha_type, sitekey_or_img_url).
    """
    # ── Custom image CAPTCHA (captcha-box) ───────────────────────
    if "captcha-box" in html:
        # Find the <img> tag inside the captcha-box div
        m = re.search(
            r'class=["\'][^"\']*captcha-box[^"\']*["\'][^>]*>.*?<img[^>]+src=["\']([^"\']+)["\']',
            html, re.DOTALL | re.IGNORECASE,
        )
        if not m:
            # Broader search: any img near captcha keyword
            m = re.search(r'captcha[^>]*>.*?<img[^>]+src=["\']([^"\']+)["\']', html, re.DOTALL | re.IGNORECASE)
        img_url = m.group(1) if m else ""
        logger.info("Image CAPTCHA detected — img_url=%s", img_url)
        return "image", img_url

    # ── hCaptcha ─────────────────────────────────────────────────
    if "hcaptcha.com" in html:
        m = re.search(r'data-sitekey=["\']([^"\']+)["\']', html)
        sitekey = m.group(1) if m else ""
        logger.info("hCaptcha detected — sitekey=%s", sitekey)
        return "hcaptcha", sitekey

    # ── reCAPTCHA v3 ─────────────────────────────────────────────
    if "grecaptcha.execute" in html:
        m = re.search(r'grecaptcha\.execute\(["\']([^"\']+)["\']', html)
        if not m:
            m = re.search(r'render=["\']([^"\']+)["\']', html)
        sitekey = m.group(1) if m else ""
        logger.info("reCAPTCHA v3 detected — sitekey=%s", sitekey)
        return "recaptchav3", sitekey

    # ── reCAPTCHA v2 ─────────────────────────────────────────────
    if "www.google.com/recaptcha" in html or "g-recaptcha" in html:
        m = re.search(r'data-sitekey=["\']([^"\']+)["\']', html)
        sitekey = m.group(1) if m else ""
        logger.info("reCAPTCHA v2 detected — sitekey=%s", sitekey)
        return "recaptchav2", sitekey

    return "none", ""


def find_captcha_input_name(html: str) -> str:
    """
    Return the <input> field name that holds the typed CAPTCHA answer.
    Strategy:
      1. Find the captcha-box div.
      2. Walk the DOM to find a text input INSIDE or immediately AFTER it
         that is NOT the main barcode/search field.
      3. Fallback: any input whose name/id explicitly contains 'captcha'.
    """
    from bs4 import BeautifulSoup as _BS
    soup = _BS(html, "html.parser")

    # Known search/barcode input names to exclude
    EXCLUDE = re.compile(r"search|barcode|track|txtbSearch", re.IGNORECASE)

    captcha_div = soup.find(class_=re.compile(r"\bcaptcha-box\b", re.IGNORECASE))
    if captcha_div:
        # 1. Input inside the captcha-box itself
        for inp in captcha_div.find_all("input", {"type": lambda t: t in (None, "", "text", "number")}):
            name = inp.get("name", "")
            if name and not EXCLUDE.search(name):
                logger.info("Captcha input found inside captcha-box: %s", name)
                return name

        # 2. Input in the same parent row/div as captcha-box
        parent = captcha_div.parent
        if parent:
            for inp in parent.find_all("input", {"type": lambda t: t in (None, "", "text", "number")}):
                name = inp.get("name", "")
                if name and not EXCLUDE.search(name):
                    logger.info("Captcha input found in captcha-box parent: %s", name)
                    return name

    # 3. Any input whose name or id explicitly contains 'captcha'
    for inp in soup.find_all("input"):
        name = inp.get("name", "")
        id_  = inp.get("id", "")
        if re.search(r"captcha", name + id_, re.IGNORECASE):
            logger.info("Captcha input found by captcha keyword: name=%s id=%s", name, id_)
            return name

    # 4. Log ALL inputs to help debug when detection fails
    all_inputs = [
        (i.get("name", ""), i.get("id", ""), i.get("type", ""))
        for i in soup.find_all("input")
    ]
    logger.warning("Could not detect captcha input — all inputs: %s", all_inputs)
    return "txtCaptcha"   # best-guess fallback for tracking.post.ir


# ════════════════════════════════════════════════════════════════════
#  Image CAPTCHA solver — ddddocr (FREE, local, no API key needed)
#  + TrueCaptcha as optional fallback
# ════════════════════════════════════════════════════════════════════

# Lazily initialised so import errors don't crash startup
_ocr = None

def _get_ocr():
    """Return a cached ddddocr instance, or None if not installed."""
    global _ocr
    if _ocr is not None:
        return _ocr
    try:
        import ddddocr
        _ocr = ddddocr.DdddOcr(show_ad=False)
        logger.info("ddddocr loaded — local CAPTCHA solver ready")
        return _ocr
    except Exception as exc:
        logger.warning("ddddocr not available: %s", exc)
        return None


# Character substitution: common OCR misreads → digit lookalikes
# Applied when the raw OCR result contains letters mixed with digits
_CHAR_TO_DIGIT = str.maketrans({
    'i': '1', 'I': '1', 'l': '1', '!': '1', 'j': '1',
    'O': '0', 'o': '0', 'D': '0', 'Q': '0',
    'S': '5', 's': '5',
    'B': '8',
    'G': '6', 'b': '6',
    'Z': '2', 'z': '2',
    'T': '7',
    'g': '9',
    'q': '9',
    # letters with no digit equivalent — drop by not including in translation
    # they will be removed by re.sub(r'\D','',…) afterwards
})


def _fix_ocr_chars(raw: str) -> str:
    """Apply character substitution then keep only digits."""
    substituted = raw.translate(_CHAR_TO_DIGIT)
    return re.sub(r'\D', '', substituted)


def _preprocess_captcha_image(
    image_bytes: bytes,
    rmax: int = 90,
    gmax: int = 90,
    bmin: int = 70,
    crop: float | None = 0.55,
) -> bytes:
    """
    Isolate the CAPTCHA digits with a colour mask and upscale 3×.

    tracking.post.ir draws the digits in dark navy over a light blue background,
    with bright saturated curves and dots as noise.  A greyscale threshold keeps
    the noise and eats digit strokes; selecting "dark and blue-dominant" pixels
    removes the noise instead.  `crop` trims to the left fraction of the image,
    where the digits always sit.
    """
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        if crop:
            img = img.crop((0, 0, int(img.width * crop), img.height))

        src = img.load()
        out = Image.new("L", img.size, 255)
        dst = out.load()
        for y in range(img.height):
            for x in range(img.width):
                r, g, b = src[x, y]
                if r < rmax and g < gmax and b >= bmin and b > r and b > g:
                    dst[x, y] = 0

        out = out.resize((out.width * 3, out.height * 3), Image.LANCZOS)
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return image_bytes


# Candidate renderings fed to the OCR, in order.  `None` means the raw bytes —
# unmodified images beat any greyscale threshold on this CAPTCHA, so they stay
# in the ensemble.
_OCR_VARIANTS: tuple[dict[str, object] | None, ...] = (
    {"rmax": 90,  "gmax": 90,  "bmin": 70, "crop": 0.55},
    None,
    {"rmax": 110, "gmax": 110, "bmin": 90, "crop": None},
)


async def solve_image_captcha(image_bytes: bytes) -> str | None:
    """
    Solve a 4-digit numeric image CAPTCHA.
    Uses ddddocr locally (free, no API key).
    Falls back to TrueCaptcha if TRUECAPTCHA_USERID/APIKEY are set.

    Returns None when no rendering yields exactly 4 digits — the caller must
    retry with a fresh CAPTCHA rather than submit a partial answer.
    """
    # ── 1. ddddocr (local, free) — ensemble over image variants ───
    ocr = _get_ocr()
    if ocr is not None:
        from collections import Counter

        candidates: list[str] = []
        for variant in _OCR_VARIANTS:
            try:
                img = image_bytes if variant is None else _preprocess_captcha_image(
                    image_bytes, **variant  # type: ignore[arg-type]
                )
                raw = str(ocr.classification(img)).strip()
                digits = _fix_ocr_chars(raw)
                logger.debug("ddddocr variant=%s raw=%r digits=%r", variant, raw, digits)
                if len(digits) == 4:
                    candidates.append(digits)
            except Exception as exc:
                logger.warning("ddddocr variant=%s failed: %s", variant, exc)

        if candidates:
            answer, votes = Counter(candidates).most_common(1)[0]
            logger.info("ddddocr solved — answer=%r (%d/%d votes)",
                        answer, votes, len(_OCR_VARIANTS))
            return answer

        logger.warning("ddddocr produced no 4-digit candidate — trying fallback")

    # ── 2. TrueCaptcha fallback ───────────────────────────────────
    if not settings.truecaptcha_userid or not settings.truecaptcha_apikey:
        logger.warning("No CAPTCHA solver available (ddddocr failed and TrueCaptcha not configured).")
        return None

    b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "userid":  settings.truecaptcha_userid,
        "apikey":  settings.truecaptcha_apikey,
        "data":    b64,
        "mode":    "human",
        "numeric": "true",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(TRUECAPTCHA_BASE, json=payload)
            resp.raise_for_status()
            data = resp.json()
            logger.info("TrueCaptcha response: %s", data)
            result = data.get("result") or data.get("text") or data.get("answer")
            if result:
                return str(result).strip()
            logger.error("TrueCaptcha returned no result: %s", data)
        except Exception as exc:
            logger.error("TrueCaptcha error: %s", exc)
    return None


# ════════════════════════════════════════════════════════════════════
#  CapSolver — reCAPTCHA / hCaptcha
# ════════════════════════════════════════════════════════════════════

async def solve_captcha(
    captcha_type: CaptchaType,
    sitekey: str,
    page_url: str,
) -> str | None:
    """Solve reCAPTCHA/hCaptcha via CapSolver. Returns token or None."""
    if not settings.capsolver_api_key:
        logger.warning("CAPSOLVER_API_KEY not set — cannot solve %s.", captcha_type)
        return None

    if captcha_type == "recaptchav2":
        task = {"type": "ReCaptchaV2TaskProxyLess", "websiteURL": page_url, "websiteKey": sitekey}
    elif captcha_type == "recaptchav3":
        task = {"type": "ReCaptchaV3TaskProxyLess", "websiteURL": page_url, "websiteKey": sitekey,
                "pageAction": "submit", "minScore": 0.5}
    elif captcha_type == "hcaptcha":
        task = {"type": "HCaptchaTaskProxyLess", "websiteURL": page_url, "websiteKey": sitekey}
    else:
        return None

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            r = await client.post(f"{CAPSOLVER_BASE}/createTask",
                                  json={"clientKey": settings.capsolver_api_key, "task": task})
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            logger.error("CapSolver createTask error: %s", exc)
            return None

        if data.get("errorId", 0) != 0:
            logger.error("CapSolver failed: %s", data)
            return None

        task_id = data.get("taskId")
        for _ in range(40):
            await asyncio.sleep(3)
            try:
                poll = await client.post(f"{CAPSOLVER_BASE}/getTaskResult",
                                         json={"clientKey": settings.capsolver_api_key, "taskId": task_id})
                result = poll.json()
            except Exception:
                continue
            if result.get("status") == "ready":
                sol = result.get("solution", {})
                return sol.get("gRecaptchaResponse") or sol.get("token") or sol.get("captchaAnswer")
            if result.get("status") == "failed":
                return None

    return None


# ════════════════════════════════════════════════════════════════════
#  Convenience wrapper (called by scraper_service)
# ════════════════════════════════════════════════════════════════════

async def handle_captcha_in_html(html: str) -> tuple[str | None, CaptchaType]:
    """
    Detect CAPTCHA type in raw HTML.
    For image CAPTCHAs returns (img_url, "image") so the caller can
    download the image and call solve_image_captcha() separately
    (needs the live session for cookies).
    For reCAPTCHA/hCaptcha: detects + solves + returns (token, type).
    Returns (None, "none") when no CAPTCHA found.
    """
    captcha_type, value = detect_captcha(html)

    if captcha_type == "none":
        return None, "none"

    if captcha_type == "image":
        # Return the img_url so the caller downloads it with the live session
        return value, "image"

    # reCAPTCHA / hCaptcha — solve immediately
    token = await solve_captcha(captcha_type, value, settings.tracking_url)
    return token, captcha_type
