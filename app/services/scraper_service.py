"""
services/scraper_service.py — Iran Post scraping core.

Flow per request (mirrors Node.js server.js exactly):
  1. Create a persistent curl_cffi.AsyncSession with Chrome TLS impersonation per call.
  2. GET  https://tracking.post.ir/  → extract ASP.NET hidden fields.
  3. POST https://tracking.post.ir/  → submit search form.
  4. Parse result HTML with BeautifulSoup → structured dict.

Why curl_cffi instead of httpx?
  The site silently drops connections from Python's default TLS stack because
  the JA3 fingerprint differs from a real browser.  curl_cffi uses libcurl
  compiled with BoringSSL and replays Chrome's exact ClientHello, so the
  server sees an indistinguishable handshake.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Dict

from curl_cffi.requests import AsyncSession, Response
from bs4 import BeautifulSoup

from app.core.config import settings
from app.core.logging import get_logger
from app.models.schemas import TrackResponse, TrackingEvent

logger = get_logger(__name__)

# ── Browser-like headers (identical to Node.js BASE_HEADERS) ────────────────
# curl_cffi already injects the correct TLS fingerprint; these headers make
# the HTTP layer equally browser-like.
BASE_HEADERS: Dict[str, str] = {
    "User-Agent":                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language":           "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding":           "gzip, deflate, br",
    "Connection":                "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Ch-Ua":                 '"Chromium";v="124", "Google Chrome";v="124"',
    "Sec-Ch-Ua-Mobile":          "?0",
    "Sec-Ch-Ua-Platform":        '"Windows"',
    "Sec-Fetch-Dest":            "document",
    "Sec-Fetch-Mode":            "navigate",
    "Sec-Fetch-Site":            "same-origin",
    "Sec-Fetch-User":            "?1",
    "Cache-Control":             "max-age=0",
}

NOT_FOUND_PHRASES = [
    "یافت نشد",
    "اطلاعاتی موجود نیست",
    "کد رهگیری صحیح نیست",
    "کد مرسوله یافت نشد",
    "اطلاعاتی برای این کد",
    "not found",
]


# ════════════════════════════════════════════════════════════════════
#  PUBLIC ENTRY POINT
# ════════════════════════════════════════════════════════════════════

async def scrape_tracking(tracking_code: str) -> TrackResponse:
    """
    Perform the full GET → POST → parse flow for one tracking code.
    Each call gets its own AsyncSession so cookies never leak between requests.
    """
    html = await scrape_raw_html(tracking_code)
    if html is None:
        return TrackResponse(
            success=False,
            tracking_code=tracking_code,
            error="GET failed after retries",
        )
    return _parse_tracking_html(html, tracking_code)


async def scrape_raw_html(tracking_code: str) -> str | None:
    """
    Run the GET → POST pipeline and return the raw response HTML.
    Returns None if the scrape fails entirely.
    Useful for debugging selector mismatches via /api/debug.
    """
    # impersonate= tells curl_cffi which Chrome/Safari JA3+JA4 profile to use.
    async with AsyncSession(
        impersonate=settings.impersonate,
        headers=BASE_HEADERS,
        timeout=settings.timeout_seconds,
        max_redirects=5,
    ) as session:
        # STEP 1 — GET page, extract hidden ASP.NET fields
        hidden = await _extract_hidden_fields(session, tracking_code)
        if hidden is None:
            return None

        if not hidden.get("__VIEWSTATE"):
            return None

        # STEP 2 — POST form and return raw HTML
        return await _post_search_form(session, tracking_code, hidden)


# ════════════════════════════════════════════════════════════════════
#  STEP 1 — GET + hidden-field extraction
# ════════════════════════════════════════════════════════════════════

async def _extract_hidden_fields(
    session: AsyncSession,
    tracking_code: str,
) -> Dict[str, str] | None:
    """
    GET the tracking page and collect all ASP.NET hidden fields.
    Auto-detects the search input name and the __doPostBack eventTarget.
    Retries up to settings.max_retries times with a sleep between attempts.
    """
    for attempt in range(1, settings.max_retries + 1):
        try:
            resp: Response = await session.get(settings.tracking_url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            def _val(name: str) -> str:
                tag = soup.find("input", {"name": name})
                return tag["value"] if tag and tag.get("value") else ""  # type: ignore[index]

            viewstate    = _val("__VIEWSTATE")
            vs_generator = _val("__VIEWSTATEGENERATOR")
            ev_valid     = _val("__EVENTVALIDATION")
            vs_encrypted = _val("__VIEWSTATEENCRYPTED")
            last_focus   = _val("__LASTFOCUS")

            # Auto-detect search text field name
            search_input_name = "txtbSearch"
            for tag in soup.find_all("input", attrs={"type": lambda t: t in ("text", "search")}):
                name = tag.get("name", "")
                if re.search(r"search|track|barcode|code|txtb", name, re.IGNORECASE):
                    search_input_name = name
                    break

            # Auto-detect __doPostBack eventTarget from anchor hrefs
            event_target = "btnSearch"
            for a in soup.find_all("a", href=re.compile(r"doPostBack")):
                href = a.get("href", "")
                text = a.get_text(strip=True)
                if re.search(r"جستجو|پیگیری|search|submit", text + href, re.IGNORECASE):
                    m = re.search(r"__doPostBack\(['\"]([^'\"]+)['\"]", href)
                    if m:
                        event_target = m.group(1)
                        break

            logger.debug(
                "[%s] GET ok — viewstate=%s… input=%s eventTarget=%s",
                tracking_code, viewstate[:20] if viewstate else "MISSING",
                search_input_name, event_target,
            )

            return {
                "__VIEWSTATE":          viewstate,
                "__VIEWSTATEGENERATOR": vs_generator,
                "__EVENTVALIDATION":    ev_valid,
                "__VIEWSTATEENCRYPTED": vs_encrypted,
                "__LASTFOCUS":          last_focus,
                "_search_input_name":   search_input_name,
                "_event_target":        event_target,
            }

        except Exception as exc:
            logger.warning("[%s] GET attempt %d failed: %s", tracking_code, attempt, exc)
            if attempt < settings.max_retries:
                await asyncio.sleep(settings.retry_sleep_seconds)

    return None


# ════════════════════════════════════════════════════════════════════
#  STEP 2 — POST search form
# ════════════════════════════════════════════════════════════════════

async def _post_search_form(
    session: AsyncSession,
    tracking_code: str,
    hidden: Dict[str, str],
) -> str | None:
    """
    Build and submit the ASP.NET postback form, mirroring
    what __doPostBack('btnSearch','') does in the browser.
    """
    search_input_name = hidden.pop("_search_input_name", "txtbSearch")
    event_target      = hidden.pop("_event_target", "btnSearch")

    form_data: Dict[str, str] = {
        "__LASTFOCUS":          hidden.get("__LASTFOCUS", ""),
        "__EVENTTARGET":        event_target,
        "__EVENTARGUMENT":      "",
        "__VIEWSTATE":          hidden.get("__VIEWSTATE", ""),
        "__VIEWSTATEGENERATOR": hidden.get("__VIEWSTATEGENERATOR", ""),
        "__VIEWSTATEENCRYPTED": hidden.get("__VIEWSTATEENCRYPTED", ""),
        "__EVENTVALIDATION":    hidden.get("__EVENTVALIDATION", ""),
        search_input_name:      tracking_code,
        "CustomerMob":          "",   # always present, always blank
    }

    post_headers = {
        **BASE_HEADERS,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer":       settings.tracking_url,
        "Origin":        "https://tracking.post.ir",
        "Sec-Fetch-Site": "same-origin",
    }

    try:
        resp: Response = await session.post(
            settings.tracking_url,
            data=form_data,
            headers=post_headers,
        )
        resp.raise_for_status()
        logger.debug("[%s] POST ok — status=%d len=%d", tracking_code, resp.status_code, len(resp.text))
        return resp.text
    except Exception as exc:
        logger.error("[%s] POST failed: %s", tracking_code, exc)
        return None


# ════════════════════════════════════════════════════════════════════
#  STEP 3 — HTML parser (mirrors parseTrackingHtml in server.js)
# ════════════════════════════════════════════════════════════════════

def _parse_tracking_html(html: str, tracking_code: str) -> TrackResponse:
    """
    Parse the POST response HTML and return a structured TrackResponse.
    Selector logic is a precise port of the Cheerio code in server.js.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Guard: blocked / CAPTCHA
    title_tag = soup.find("title")
    title_text = title_tag.get_text().lower() if title_tag else ""
    if re.search(r"captcha|blocked|access denied|403|forbidden", title_text):
        return TrackResponse(
            success=False,
            tracking_code=tracking_code,
            error="BLOCKED",
            raw_html_parsed=True,
        )

    # Guard: Bootstrap *error* alert messages (e.g. "بارکد نامعتبر است.")
    # The site also uses alert-warning for informational banners that echo the
    # tracking number ("رهگیری مرسوله به شماره : XXXX") — those must NOT be
    # treated as errors.  We only treat an alert as a hard error when its text
    # does NOT contain the tracking code itself.
    alert_msg = ""
    for alert in soup.find_all(class_=re.compile(r"\balert-(danger|warning)\b")):
        text = alert.get_text(strip=True)
        if text and tracking_code not in text:
            alert_msg = text
            break

    # Guard: result panel not present → no data
    pnl_result = soup.find(id="pnlResult")
    if not pnl_result:
        all_text = soup.get_text()
        not_found = any(phrase in all_text for phrase in NOT_FOUND_PHRASES)
        status = "NOT_FOUND" if not_found else "NO_DATA"
        return TrackResponse(
            success=False,
            tracking_code=tracking_code,
            status=status,
            error=alert_msg or None,
            receiver_name="",
            origin="",
            destination="",
            last_update="",
            is_delivered=False,
            events=[],
            raw_html_parsed=True,
        )

    # If panel exists but carries an alert, treat it as a soft failure.
    if alert_msg:
        return TrackResponse(
            success=False,
            tracking_code=tracking_code,
            status="INVALID_CODE",
            error=alert_msg,
            raw_html_parsed=True,
        )

    result: Dict[str, Any] = {
        "success":         True,
        "tracking_code":   tracking_code,
        "status":          "",
        "receiver_name":   "",
        "origin":          "",
        "destination":     "",
        "last_update":     "",
        "is_delivered":    False,
        "events":          [],
        "raw_html_parsed": True,
        "error":           None,
    }

    # ── A: Metadata from .newcolheader → .newcoldata pairs ─────────
    for header_div in soup.find_all(class_="newcolheader"):
        label = header_div.get_text(strip=True)
        next_sib = header_div.find_next_sibling(class_="newcoldata")
        value = next_sib.get_text(strip=True) if next_sib else ""
        if not value:
            continue
        if re.search(r"نام گیرنده", label) and not result["receiver_name"]:
            result["receiver_name"] = value
        if re.search(r"نام فرستنده|فرستنده", label) and not result["origin"]:
            result["origin"] = value
        if re.search(r"مقصد", label) and not result["destination"]:
            result["destination"] = value
        if re.search(r"مبدأ|مبدا|استان مبدا", label) and not result["origin"]:
            result["origin"] = value

    # Check reverse direction for city pairs
    if not result["origin"] or not result["destination"]:
        for data_div in soup.find_all(class_="newcoldata"):
            val = data_div.get_text(strip=True)
            next_h = data_div.find_next_sibling(class_="newcolheader")
            if next_h and re.search(r"مقصد", next_h.get_text(strip=True)) and not result["origin"]:
                result["origin"] = val

    # ── B: Timeline events from #pnlResult .row.newrowdata ─────────
    current_date = ""
    events: list[TrackingEvent] = []

    for row in pnl_result.find_all(class_="row"):  # type: ignore[union-attr]
        date_headers = row.find_all(class_="newtdheader")
        if date_headers:
            current_date = date_headers[0].get_text(strip=True)
            continue

        if "newrowdata" not in (row.get("class") or []):
            continue

        cells = row.find_all(class_="newtddata")
        if len(cells) < 3:
            continue

        # cell[0]=step, cell[1]=status, cell[2]=location, cell[3]=time
        # Remove inner <a> tags from status cell (same as Cheerio .clone().find('a').remove())
        status_cell = cells[1]
        for a_tag in status_cell.find_all("a"):
            a_tag.decompose()
        status_raw = status_cell.get_text(strip=True)

        location = cells[2].get_text(strip=True)
        time_str = cells[3].get_text(strip=True) if len(cells) > 3 else ""

        event_date = f"{current_date} - {time_str}" if current_date else time_str
        event = TrackingEvent(date=event_date, location=location, status=status_raw)

        if event.date or event.status or event.location:
            events.append(event)

    result["events"] = events

    # ── C: Derived fields from events ─────────────────────────────
    if events:
        latest = events[0]
        if not result["status"]:
            result["status"] = latest.status
        if not result["last_update"]:
            result["last_update"] = latest.date
        if not result["destination"]:
            result["destination"] = latest.location
        if not result["origin"]:
            for ev in reversed(events):
                if ev.location:
                    result["origin"] = ev.location
                    break

    # ── D: Delivered flag ─────────────────────────────────────────
    result["is_delivered"] = bool(
        re.search(r"تحویل|تسلیم|delivered", result["status"], re.IGNORECASE)
    )

    return TrackResponse(**result)

