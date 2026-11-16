"""
Verification test suite for GTM Plan Group 1 & Group 2 site additions:
1. Legal & Trust pages: /subprocessors and /dpa render with proper Canadian safeguards.
2. Cookie notice banner logic in global-chrome.js.
3. Canadian og:locale = en_CA across all public templates.
4. SMC3 CzarLite® copy refinement and trademark disclaimer on /pricing.
"""
from fastapi.testclient import TestClient
from main import app
from services.db_service import init_db


def test_01_subprocessors_page_renders_with_canadian_safeguards():
    init_db()
    client = TestClient(app)
    res = client.get("/subprocessors")
    assert res.status_code == 200
    html = res.text

    assert "Authorized Sub-processors" in html
    assert "Web Hosting Canada" in html
    assert "Stripe Payments Canada" in html
    assert "Amazon Web Services" in html
    assert "Montreal, QC, Canada" in html
    assert "CA_CENTRAL_WHC" in html


def test_02_dpa_page_renders_b2b_saas_terms():
    init_db()
    client = TestClient(app)
    res = client.get("/dpa")
    assert res.status_code == 200
    html = res.text

    assert "Data Processing Addendum" in html
    assert "PIPEDA" in html
    assert "Controller" in html
    assert "Processor" in html
    assert "CA_CENTRAL_WHC" in html
    assert "Argon2id" in html


def test_03_cookie_notice_in_global_chrome():
    client = TestClient(app)
    res = client.get("/static/js/global-chrome.js")
    assert res.status_code == 200
    js = res.text

    assert "quotelytics-cookie-notice" in js
    assert "quotelytics_cookie_acknowledged" in js
    assert "quotelytics_session" in js


def test_04_canadian_og_locale_en_ca_across_public_pages():
    client = TestClient(app)
    pages = ["/", "/demo", "/pricing", "/login", "/get-started", "/privacy", "/terms", "/subprocessors", "/dpa"]
    for p in pages:
        res = client.get(p)
        assert res.status_code == 200, f"Page {p} returned {res.status_code}"
        assert 'content="en_CA"' in res.text, f"Page {p} does not contain og:locale en_CA"


def test_05_czarlite_trademark_copy_on_pricing_page():
    client = TestClient(app)
    res = client.get("/pricing")
    assert res.status_code == 200
    html = res.text

    assert "CzarLite®-Compatible" in html
    assert "CzarLite® is a registered trademark of SMC3 Inc." in html
    assert "not affiliated with or endorsed by SMC3 Inc." in html
