"""Browser smoke test (Playwright). Skipped when Playwright is not installed.
    python -m pytest tests/smoke.py
"""
import os, threading, uuid, pytest

pw = pytest.importorskip("playwright.sync_api")
from werkzeug.serving import make_server
import app as appmod, extract
from conftest import SAMPLES


PIDS = {}


@pytest.fixture(scope="module")
def base_url():
    for key, f in (("compe", "CompE_worksheet.pdf"), ("ee", "EE_worksheet.pdf")):
        p = extract.extract_pdfs([os.path.join(SAMPLES, f)])
        appmod.save(p); PIDS[key] = p["id"]
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
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("dialog", lambda d: d.accept())
        pg.goto(base_url)
        yield pg
        b.close()
        assert not errors, errors


def signup(page, name, pw="password123"):
    """Create an account and end up signed in, looking at the map."""
    page.fill("#auUser", name)
    page.fill("#auPass", pw)
    page.click("#auSignup")
    page.wait_for_selector("#app:not([hidden])")
    page.wait_for_selector(".node")


def logout(page):
    page.click("#btnUser")
    page.wait_for_selector("#auth:not([hidden])")


def open_program(page, key):
    page.select_option("#progSel", PIDS[key])
    page.wait_for_function("id => typeof S !== 'undefined' && S.P && S.P.id === id", arg=PIDS[key])


def test_signup_check_search_note_reload(page):
    name = "s" + uuid.uuid4().hex[:8]
    signup(page, name)

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


def test_fill_any_slot_with_custom_course(page):
    logout(page)
    signup(page, "a" + uuid.uuid4().hex[:8])
    open_program(page, "ee")
    slot = page.locator('.node.slot').first                        # Y1 Fall Social World
    sid = slot.get_attribute("data-id")
    slot.click()
    page.wait_for_selector("#side h2:text('Social World Elective')")
    page.fill('#fillForm [name=ccode]', "HISTORY 101")
    page.fill('#fillForm [name=ccr]', "4")
    page.check('#fillForm label:has-text("Historical Studies") input')
    page.click('#fillForm button[type=submit]')
    card = page.locator(f'.node[data-id="{sid}"]')
    assert card.locator(".code").text_content() == "HISTORY 101"
    assert card.locator(".crd").text_content() == "4"
    page.fill("#note", "check DU too")
    page.wait_for_selector("#stSaved:text('saved')")
    card.locator(".cb").click()                                    # credits count
    page.wait_for_function("document.querySelector('#stDone').textContent.startsWith('✓ 4 /')")

    page.reload(); page.wait_for_selector(".node")
    open_program(page, "ee")
    page.click("#stProblems")
    page.click('#side summary:has-text("Social World")')
    item = page.locator('#side label.chk:has-text("Historical Studies")').first
    assert item.locator("input").is_checked() and "HISTORY 101" in item.inner_text()
    page.locator(f'.node[data-id="{sid}"]').click()
    assert page.input_value("#note") == "check DU too"

    logout(page)                                                   # another account sees none of it
    signup(page, "b" + uuid.uuid4().hex[:8])
    open_program(page, "ee")
    assert page.locator('.node .code:text("HISTORY 101")').count() == 0
