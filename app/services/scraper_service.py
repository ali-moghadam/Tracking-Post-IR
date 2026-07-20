"""
services/scraper_service.py — Iran Post scraping core.

Flow per request:
  1. GET  https://tracking.post.ir/  → extract ASP.NET hidden fields.
     If a CAPTCHA is detected on the GET response, solve it via CapSolver.
  2. POST https://tracking.post.ir/  → submit search form (+ CAPTCHA token if needed).
  3. Parse result HTML with BeautifulSoup → structured dict.

Uses curl_cffi for Chrome TLS impersonation — no browser required.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict

from curl_cffi.requests import AsyncSession, Response
from bs4 import BeautifulSoup

from app.core.config import settings
from app.core.logging import get_logger
from app.models.schemas import TrackResponse, TrackingEvent
from app.services.captcha_service import (
    handle_captcha_in_html,
    find_captcha_input_name,
    solve_image_captcha,
)

logger = get_logger(__name__)

# ── Browser-like headers ─────────────────────────────────────────────────────
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

async def scrape_tracking(tracking_code: str, phone: str | None = None) -> TrackResponse:
    """Perform the full GET → (CAPTCHA solve) → POST → (phone POST) → parse flow."""
    html = await scrape_raw_html(tracking_code, phone=phone)
    if html is None:
        return TrackResponse(
            success=False,
            tracking_code=tracking_code,
            status="CAPTCHA_FAILED",
            error=f"CAPTCHA could not be solved after {settings.max_retries + 1} attempts",
        )
    result = _parse_tracking_html(html, tracking_code)

    # ── Second POST: fetch receiver details via phone number ──────
    # Iran Post requires a separate "مشاهده جزئیات بیشتر" postback
    # with CustomerMob to reveal receiver_name.
    if phone and not result.receiver_name and result.success:
        try:
            detail_html = await _fetch_receiver_details(html, tracking_code, phone)
            if detail_html:
                detail_result = _parse_tracking_html(detail_html, tracking_code)
                if detail_result.receiver_name:
                    result.receiver_name = detail_result.receiver_name
                    logger.info("[%s] receiver_name resolved via phone: %r",
                                tracking_code, result.receiver_name)
        except Exception as exc:
            logger.warning("[%s] receiver detail fetch failed: %s", tracking_code, exc)

    return result


async def scrape_raw_html(tracking_code: str, phone: str | None = None) -> str | None:
    """
    Run the GET → POST pipeline and return the raw response HTML.
    Retries the full flow when the CAPTCHA answer is rejected.
    """
    total_attempts = settings.max_retries + 1

    for attempt in range(1, total_attempts + 1):
        async with AsyncSession(
            impersonate=settings.impersonate,
            headers=BASE_HEADERS,
            timeout=settings.timeout_seconds,
            max_redirects=5,
        ) as session:
            hidden = await _extract_hidden_fields(session, tracking_code)
            if hidden is None:
                return None
            if not hidden.get("__VIEWSTATE"):
                return None

            # OCR gave no usable answer — a fresh CAPTCHA is cheaper than a
            # POST we already know will be rejected.
            if hidden.get("_captcha_required") and not hidden.get("_captcha_token"):
                logger.warning(
                    "[%s] CAPTCHA unsolved — retry %d/%d",
                    tracking_code, attempt, total_attempts,
                )
                if attempt < total_attempts:
                    await asyncio.sleep(settings.retry_sleep_seconds)
                    continue
                return None

            html = await _post_search_form(session, tracking_code, hidden, phone=phone)
            if html is None:
                return None

            # A rejected CAPTCHA still returns HTTP 200; the tell is an empty
            # #pnlResult.  Compare rendered text — the markup carries incidental
            # whitespace that makes string comparison unreliable.  Note that
            # "captcha-box" is present on successful responses too, so it is not
            # a usable signal here.
            _pnl = BeautifulSoup(html, "html.parser").find(id="pnlResult")
            if _pnl is not None and _pnl.get_text(strip=True) == "":
                logger.warning(
                    "[%s] CAPTCHA answer rejected (empty result panel) — retry %d/%d",
                    tracking_code, attempt, total_attempts,
                )
                if attempt < total_attempts:
                    await asyncio.sleep(settings.retry_sleep_seconds)
                    continue
                return None

            return html

    logger.error("[%s] All CAPTCHA retries exhausted", tracking_code)
    return None


async def _fetch_receiver_details(
    result_html: str,
    tracking_code: str,
    phone: str,
) -> str | None:
    """
    Submit the 'مشاهده جزئیات بیشتر' postback with CustomerMob to reveal receiver_name.

    Iran Post flow:
      1. First POST → results page (receiver_name hidden behind phone gate)
      2. This function → second POST with phone → page includes receiver_name
    """
    soup = BeautifulSoup(result_html, "html.parser")

    def _val(name: str) -> str:
        tag = soup.find("input", {"name": name})
        return tag["value"] if tag and tag.get("value") else ""  # type: ignore[index]

    viewstate    = _val("__VIEWSTATE")
    vs_generator = _val("__VIEWSTATEGENERATOR")
    ev_valid     = _val("__EVENTVALIDATION")
    vs_encrypted = _val("__VIEWSTATEENCRYPTED")

    if not viewstate:
        logger.warning("[%s] _fetch_receiver_details: no VIEWSTATE in result HTML", tracking_code)
        return None

    # Find the "مشاهده جزئیات بیشتر" / mobile-submit event target
    # Common patterns: __doPostBack('lnkMore','') or a button with id containing Mob/Detail
    detail_event_target = ""

    # 1. Search for doPostBack links containing detail/mob/more keywords
    for a in soup.find_all("a", href=re.compile(r"doPostBack", re.IGNORECASE)):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if re.search(r"جزئیات|بیشتر|موبایل|detail|more|mob", text + href, re.IGNORECASE):
            m = re.search(r"__doPostBack\(['\"]([^'\"]+)['\"]", href)
            if m:
                detail_event_target = m.group(1)
                logger.info("[%s] detail event target (link): %r", tracking_code, detail_event_target)
                break

    # 2. Search for buttons with relevant id/name
    if not detail_event_target:
        for btn in soup.find_all(["input", "button"],
                                 attrs={"id": re.compile(r"mob|detail|more|phone", re.IGNORECASE)}):
            detail_event_target = btn.get("name") or btn.get("id") or ""
            if detail_event_target:
                logger.info("[%s] detail event target (button): %r", tracking_code, detail_event_target)
                break

    # 3. Fallback: common ASP.NET button names on this site
    if not detail_event_target:
        for candidate in ("btnMob", "btnDetail", "lnkMore", "btnMore", "lnkDetail"):
            if soup.find(id=candidate) or soup.find(attrs={"name": candidate}):
                detail_event_target = candidate
                break

    if not detail_event_target:
        # Log all links + buttons to help diagnose
        all_links = [(a.get("href",""), a.get_text(strip=True)) for a in soup.find_all("a")]
        logger.warning("[%s] Could not find detail event target. links=%s", tracking_code, all_links[:20])
        # Try submitting with CustomerMob anyway — some sites accept it on re-POST
        detail_event_target = "btnSearch"

    form_data: Dict[str, str] = {
        "__LASTFOCUS":          "",
        "__EVENTTARGET":        detail_event_target,
        "__EVENTARGUMENT":      "",
        "__VIEWSTATE":          viewstate,
        "__VIEWSTATEGENERATOR": vs_generator,
        "__VIEWSTATEENCRYPTED": vs_encrypted,
        "__EVENTVALIDATION":    ev_valid,
        "txtbSearch":           tracking_code,
        "CustomerMob":          phone,
    }

    post_headers = {
        **BASE_HEADERS,
        "Content-Type":   "application/x-www-form-urlencoded",
        "Referer":        settings.tracking_url,
        "Origin":         "https://tracking.post.ir",
        "Sec-Fetch-Site": "same-origin",
    }

    async with AsyncSession(
        impersonate=settings.impersonate,
        headers=BASE_HEADERS,
        timeout=settings.timeout_seconds,
        max_redirects=5,
    ) as session:
        try:
            resp: Response = await session.post(
                settings.tracking_url,
                data=form_data,
                headers=post_headers,
            )
            resp.raise_for_status()
            logger.info("[%s] detail POST ok — status=%d len=%d event=%r",
                        tracking_code, resp.status_code, len(resp.text), detail_event_target)
            return resp.text
        except Exception as exc:
            logger.error("[%s] detail POST failed: %s", tracking_code, exc)
            return None



# ════════════════════════════════════════════════════════════════════
#  STEP 1 — GET + hidden-field extraction + CAPTCHA detection
# ════════════════════════════════════════════════════════════════════

async def _extract_hidden_fields(
    session: AsyncSession,
    tracking_code: str,
) -> Dict[str, str] | None:
    """
    GET the tracking page, collect ASP.NET hidden fields, and detect any
    CAPTCHA.  If a CAPTCHA is present, solve it and store the token so
    _post_search_form can include it in the form body.
    """
    for attempt in range(1, settings.max_retries + 1):
        try:
            resp: Response = await session.get(settings.tracking_url)
            resp.raise_for_status()
            html = resp.text
            soup = BeautifulSoup(html, "html.parser")

            logger.debug(
                "[%s] GET response — status=%d  len=%d  snippet(0:500): %s",
                tracking_code, resp.status_code, len(html),
                html[:500].replace("\n", " "),
            )

            # Log all <input> fields so we can verify captcha field name
            if logger.isEnabledFor(logging.DEBUG):
                all_inputs = [(t.get("name",""), t.get("id",""), t.get("type",""))
                              for t in soup.find_all("input")]
                logger.debug("[%s] ALL form inputs: %s", tracking_code, all_inputs)

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

            # Auto-detect __doPostBack eventTarget
            event_target = "btnSearch"
            for a in soup.find_all("a", href=re.compile(r"doPostBack")):
                href = a.get("href", "")
                text = a.get_text(strip=True)
                if re.search(r"جستجو|پیگیری|search|submit", text + href, re.IGNORECASE):
                    m = re.search(r"__doPostBack\(['\"]([^'\"]+)['\"]", href)
                    if m:
                        event_target = m.group(1)
                        break

            # ── CAPTCHA detection & solving ──────────────────────
            captcha_token: str = ""
            captcha_field: str = ""
            img_url, captcha_type = await handle_captcha_in_html(html)

            if captcha_type == "image":
                # img_url returned — download with live session (preserves cookies)
                captcha_input_name = find_captcha_input_name(html)
                logger.info(
                    "[%s] Image CAPTCHA — img_url=%r  input_field=%r",
                    tracking_code, img_url, captcha_input_name,
                )
                if img_url:
                    # Build absolute URL if relative
                    if img_url.startswith("/") or not img_url.startswith("http"):
                        from urllib.parse import urljoin
                        abs_url = urljoin(settings.tracking_url, img_url)
                    else:
                        abs_url = img_url
                    try:
                        img_resp: Response = await session.get(abs_url)
                        img_resp.raise_for_status()
                        answer = await solve_image_captcha(img_resp.content)
                        if answer:
                            captcha_token = answer
                            captcha_field = captcha_input_name
                            logger.info(
                                "[%s] Image CAPTCHA solved — answer=%r  field=%r",
                                tracking_code, answer, captcha_field,
                            )
                        else:
                            logger.warning("[%s] Image CAPTCHA: no answer returned", tracking_code)
                    except Exception as exc:
                        logger.error("[%s] Image CAPTCHA download error: %s", tracking_code, exc)

            elif captcha_type != "none":
                # reCAPTCHA / hCaptcha token
                token = img_url  # handle_captcha_in_html returns token in first position
                if token:
                    captcha_token = token
                    captcha_field = (
                        "h-captcha-response" if captcha_type == "hcaptcha"
                        else "g-recaptcha-response"
                    )
                    logger.info(
                        "[%s] CAPTCHA (%s) solved — token len=%d",
                        tracking_code, captcha_type, len(token),
                    )
                else:
                    logger.warning(
                        "[%s] CAPTCHA (%s) detected but not solved",
                        tracking_code, captcha_type,
                    )

            logger.debug(
                "[%s] GET ok — viewstate=%s… input=%s eventTarget=%s captcha=%s",
                tracking_code, viewstate[:20] if viewstate else "MISSING",
                search_input_name, event_target, captcha_type,
            )

            return {
                "__VIEWSTATE":          viewstate,
                "__VIEWSTATEGENERATOR": vs_generator,
                "__EVENTVALIDATION":    ev_valid,
                "__VIEWSTATEENCRYPTED": vs_encrypted,
                "__LASTFOCUS":          last_focus,
                "_search_input_name":   search_input_name,
                "_event_target":        event_target,
                "_captcha_token":       captcha_token,
                "_captcha_field":       captcha_field,
                "_captcha_required":    "1" if captcha_type != "none" else "",
            }

        except Exception as exc:
            logger.warning("[%s] GET attempt %d failed: %s", tracking_code, attempt, exc)
            if attempt < settings.max_retries:
                await asyncio.sleep(settings.retry_sleep_seconds)

    return None


# ════════════════════════════════════════════════════════════════════
#  STEP 2 — POST search form (with optional CAPTCHA token)
# ════════════════════════════════════════════════════════════════════

async def _post_search_form(
    session: AsyncSession,
    tracking_code: str,
    hidden: Dict[str, str],
    phone: str | None = None,
) -> str | None:
    """Build and submit the ASP.NET postback form, including CAPTCHA token and phone when present."""
    search_input_name = hidden.pop("_search_input_name", "txtbSearch")
    event_target      = hidden.pop("_event_target", "btnSearch")
    captcha_token     = hidden.pop("_captcha_token", "")
    captcha_field     = hidden.pop("_captcha_field", "")
    hidden.pop("_captcha_required", "")

    form_data: Dict[str, str] = {
        "__LASTFOCUS":          hidden.get("__LASTFOCUS", ""),
        "__EVENTTARGET":        event_target,
        "__EVENTARGUMENT":      "",
        "__VIEWSTATE":          hidden.get("__VIEWSTATE", ""),
        "__VIEWSTATEGENERATOR": hidden.get("__VIEWSTATEGENERATOR", ""),
        "__VIEWSTATEENCRYPTED": hidden.get("__VIEWSTATEENCRYPTED", ""),
        "__EVENTVALIDATION":    hidden.get("__EVENTVALIDATION", ""),
        search_input_name:      tracking_code,
        "CustomerMob":          phone or "",   # receiver phone → unlocks receiver_name
    }

    # Inject solved CAPTCHA token if available
    if captcha_token and captcha_field:
        form_data[captcha_field] = captcha_token
        logger.debug("[%s] Injecting %s token into POST", tracking_code, captcha_field)

    post_headers = {
        **BASE_HEADERS,
        "Content-Type":   "application/x-www-form-urlencoded",
        "Referer":        settings.tracking_url,
        "Origin":         "https://tracking.post.ir",
        "Sec-Fetch-Site": "same-origin",
    }

    try:
        resp: Response = await session.post(
            settings.tracking_url,
            data=form_data,
            headers=post_headers,
        )
        resp.raise_for_status()
        logger.debug("[%s] POST ok — status=%d len=%d phone=%s",
                     tracking_code, resp.status_code, len(resp.text),
                     "set" if phone else "not set")
        return resp.text
    except Exception as exc:
        logger.error("[%s] POST failed: %s", tracking_code, exc)
        return None


# ════════════════════════════════════════════════════════════════════
#  STEP 3 — HTML parser
# ════════════════════════════════════════════════════════════════════

def _is_person_name(value: str) -> bool:
    """
    Reject values that are clearly not a receiver name.

    Iran Post writes locations as comma-separated hierarchies
    ("اصفهان،کاشان،نقطه مبادله پستی شهرستان کاشان"), so a candidate containing
    the Arabic comma is a location, not a person.
    """
    value = value.strip()
    return bool(value) and len(value) > 1 and "،" not in value


def _parse_tracking_html(html: str, tracking_code: str) -> TrackResponse:
    """Parse the POST response HTML and return a structured TrackResponse."""
    soup = BeautifulSoup(html, "html.parser")

    # ── Structural diagnostics ──────────────────────────────────────
    title_tag  = soup.find("title")
    title_text = title_tag.get_text().strip() if title_tag else "(no title)"

    if logger.isEnabledFor(logging.DEBUG):
        # Every CSS class in the document — helps spot renamed selectors
        all_classes: list[str] = []
        for tag in soup.find_all(True):
            all_classes.extend(tag.get("class") or [])

        logger.debug(
            "[%s] PARSE DIAG — title=%r  body_len=%d  unique_classes=%s",
            tracking_code, title_text, len(html), sorted(set(all_classes)),
        )
        logger.debug(
            "[%s] PARSE DIAG — html_snippet(0:2000): %s",
            tracking_code, html[:2000].replace("\n", " ").replace("\r", ""),
        )

    # Guard: blocked / CAPTCHA
    if re.search(r"captcha|blocked|access denied|403|forbidden", title_text.lower()):
        logger.warning("[%s] PARSE: title indicates CAPTCHA/block", tracking_code)
        return TrackResponse(
            success=False,
            tracking_code=tracking_code,
            error="BLOCKED",
            raw_html_parsed=True,
        )

    # Guard: Bootstrap error/warning alert messages
    alert_msg = ""
    for alert in soup.find_all(class_=re.compile(r"\balert-(danger|warning)\b")):
        text = alert.get_text(strip=True)
        logger.debug("[%s] PARSE: alert text=%r", tracking_code, text)
        if text and tracking_code not in text:
            alert_msg = text
            break

    # Guard: result panel not present → no data
    pnl_result = soup.find(id="pnlResult")
    logger.debug("[%s] PARSE: pnlResult found=%s", tracking_code, pnl_result is not None)

    if not pnl_result:
        all_text  = soup.get_text()
        not_found = any(phrase in all_text for phrase in NOT_FOUND_PHRASES)
        status    = "NOT_FOUND" if not_found else "NO_DATA"
        logger.info("[%s] PARSE: no pnlResult — status=%s", tracking_code, status)
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

    # An empty result panel means the CAPTCHA was rejected — never a success.
    if pnl_result.get_text(strip=True) == "":  # type: ignore[union-attr]
        logger.warning("[%s] PARSE: result panel is empty", tracking_code)
        return TrackResponse(
            success=False,
            tracking_code=tracking_code,
            status="NO_DATA",
            error=alert_msg or "Empty result panel — CAPTCHA likely rejected",
            raw_html_parsed=True,
        )

    # Log the inner HTML of pnlResult so we can see actual class names
    logger.debug(
        "[%s] PARSE: pnlResult inner HTML (first 3000 chars): %s",
        tracking_code,
        str(pnl_result)[:3000].replace("\n", " "),
    )

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
    col_headers_found = soup.find_all(class_="newcolheader")
    logger.debug("[%s] PARSE: newcolheader count=%d", tracking_code, len(col_headers_found))
    for header_div in col_headers_found:
        label    = header_div.get_text(strip=True)
        next_sib = header_div.find_next_sibling(class_="newcoldata")
        value    = next_sib.get_text(strip=True) if next_sib else ""
        logger.debug("[%s] PARSE: colheader label=%r  value=%r", tracking_code, label, value)
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

    # Also try finding receiver_name from inline label/value spans (detail response format).
    # Match only the full "نام گیرنده" label: the bare word گیرنده also occurs inside
    # ordinary status text ("مرسوله تحویل گیرنده گردیده است"), which used to make this
    # pick up the adjacent location cell as the receiver name.
    if not result["receiver_name"]:
        for tag in soup.find_all(string=re.compile(r"نام\s+گیرنده")):
            parent = tag.parent
            if parent:
                # Try next sibling text
                sibling = parent.find_next_sibling()
                if sibling:
                    val = sibling.get_text(strip=True)
                    if _is_person_name(val):
                        result["receiver_name"] = val
                        logger.info("[%s] PARSE: receiver_name from sibling: %r", tracking_code, val)
                        break
                # Try parent's text minus the label
                full = parent.get_text(strip=True)
                label_text = tag.strip()
                val = full.replace(label_text, "").strip(" :،")
                if _is_person_name(val):
                    result["receiver_name"] = val
                    logger.info("[%s] PARSE: receiver_name from parent text: %r", tracking_code, val)
                    break

    if not result["origin"] or not result["destination"]:
        for data_div in soup.find_all(class_="newcoldata"):
            val    = data_div.get_text(strip=True)
            next_h = data_div.find_next_sibling(class_="newcolheader")
            if next_h and re.search(r"مقصد", next_h.get_text(strip=True)) and not result["origin"]:
                result["origin"] = val

    # ── B: Timeline events ─────────────────────────────────────────
    all_rows = pnl_result.find_all(class_="row")  # type: ignore[union-attr]
    newrowdata_rows = [r for r in all_rows if "newrowdata" in (r.get("class") or [])]
    logger.debug(
        "[%s] PARSE: total .row=%d  .newrowdata=%d",
        tracking_code, len(all_rows), len(newrowdata_rows),
    )

    current_date = ""
    events: list[TrackingEvent] = []

    for row in all_rows:
        date_headers = row.find_all(class_="newtdheader")
        if date_headers:
            current_date = date_headers[0].get_text(strip=True)
            logger.debug("[%s] PARSE: date header=%r", tracking_code, current_date)
            continue

        if "newrowdata" not in (row.get("class") or []):
            continue

        cells = row.find_all(class_="newtddata")
        logger.debug(
            "[%s] PARSE: newrowdata row — newtddata cells=%d  texts=%s",
            tracking_code, len(cells),
            [c.get_text(strip=True) for c in cells],
        )
        if len(cells) < 3:
            continue

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
    logger.info("[%s] PARSE: total events extracted=%d", tracking_code, len(events))

    # ── C: Derived fields ──────────────────────────────────────────
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

    # ── D: Delivered flag ──────────────────────────────────────────
    result["is_delivered"] = bool(
        re.search(r"تحویل|تسلیم|delivered", result["status"], re.IGNORECASE)
    )

    logger.info("[%s] PARSE: final result=%s", tracking_code, {
        k: v for k, v in result.items() if k != "events"
    })
    return TrackResponse(**result)

