"""Browser smoke test (Playwright). Skipped when Playwright is not installed.
    python -m pytest tests/smoke.py
"""
import os, threading, uuid, pytest

pw = pytest.importorskip("playwright.sync_api")
from werkzeug.serving import make_server
import app as appmod, extract
from conftest import SAMPLES


@pytest.fixture(scope="module")
def base_url():
    p = extract.extract_pdfs([os.path.join(SAMPLES, "CompE_worksheet.pdf")])
    appmod.save(p)
    srv = make_server("127.0.0.1", 0, appmod.app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture(scope="module")
def page(base_url):
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as ex:  # browsers not downloaded
            pytest.skip(f"no browser: {ex}")
        pg = b.new_page()
        pg.on("pageerror", lambda e: pytest.fail(f"JS error: {e}"))
        pg.goto(base_url)
        yield pg
        b.close()


def test_signup_check_search_note_reload(page):
    name = "s" + uuid.uuid4().hex[:8]
    page.fill("#auUser", name)
    page.fill("#auPass", "password123")
    page.click("#auSignup")
    page.wait_for_selector("#app:not([hidden])")
    page.wait_for_selector(".node")

    page.click('.tick[data-term="1-fall"]')                       # check a term
    page.wait_for_selector('.tick.all[data-term="1-fall"]')

    page.fill("#q", "ECE 241")                                     # search a course
    page.press("#q", "Enter")
    page.wait_for_selector("#side h2:text('ECE 241')")
    page.fill("#note", "ask about section 2")                      # write a note
    page.wait_for_selector("#stSaved:text('saved')")

    page.reload()
    page.wait_for_selector(".node")
    assert page.inner_text("#btnUser").startswith(name)            # still signed in
    assert page.locator('.tick.all[data-term="1-fall"]').count() == 1
    page.fill("#q", "ECE 241"); page.press("#q", "Enter")
    page.wait_for_selector("#side h2:text('ECE 241')")
    assert page.input_value("#note") == "ask about section 2"
