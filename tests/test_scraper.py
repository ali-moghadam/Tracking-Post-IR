"""
tests/test_scraper.py — Unit tests for the HTML parser.
"""
from __future__ import annotations

import pytest
from app.services.scraper_service import _parse_tracking_html


BLOCKED_HTML = "<html><head><title>Access Denied 403</title></head><body></body></html>"
NO_PANEL_HTML = "<html><body><p>کد مرسوله یافت نشد</p></body></html>"
NO_DATA_HTML = "<html><body><p>some unrelated text</p></body></html>"
INVALID_CODE_HTML = '<html><body><div id="pnlResult"><div class="alert alert-danger">بارکد نامعتبر است.</div></div></body></html>'
INVALID_CODE_NO_PANEL_HTML = '<html><body><div class="alert alert-danger">بارکد نامعتبر است.</div></body></html>'

FAKE_INVALID_CODE = "00000000000000000000"   # 20-digit placeholder — never a real barcode


def test_blocked_returns_blocked_error():
    result = _parse_tracking_html(BLOCKED_HTML, "12345678901234567890")
    assert result.success is False
    assert result.error == "BLOCKED"


def test_not_found_phrase():
    result = _parse_tracking_html(NO_PANEL_HTML, "12345678901234567890")
    assert result.success is False
    assert result.status == "NOT_FOUND"


def test_no_data():
    result = _parse_tracking_html(NO_DATA_HTML, "12345678901234567890")
    assert result.success is False
    assert result.status == "NO_DATA"


def test_invalid_barcode_alert_inside_panel():
    """Alert inside #pnlResult → INVALID_CODE with Persian error message."""
    result = _parse_tracking_html(INVALID_CODE_HTML, FAKE_INVALID_CODE)
    assert result.success is False
    assert result.status == "INVALID_CODE"
    assert "بارکد نامعتبر" in (result.error or "")


def test_invalid_barcode_alert_no_panel():
    """Alert without #pnlResult → NO_DATA/NOT_FOUND with error message populated."""
    result = _parse_tracking_html(INVALID_CODE_NO_PANEL_HTML, FAKE_INVALID_CODE)
    assert result.success is False
    assert "بارکد نامعتبر" in (result.error or "")


