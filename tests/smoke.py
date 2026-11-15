"""Browser smoke test (Playwright). Skipped when Playwright is not installed.
    python -m pytest tests/smoke.py
"""
import os, threading, uuid, pytest

pw = pytest.importorskip("playwright.sync_api")
from werkzeug.serving import make_server
import app as appmod, extract
from conftest import SAMPLES


PIDS = {}
DIALOG = {"accept": True, "seen": []}   # confirm() answers; tests may flip "accept"


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
        pg.on("dialog", lambda d: (DIALOG["seen"].append(d.message), d.accept() if DIALOG["accept"] else d.dismiss()))
        pg.goto(base_url)
        yield pg
        b.close()
        assert not errors, errors


def signup(page, name, pw="password123"):
    """Create an account on its tab, then log in on the other one (signup does not log you in)."""
    page.click('#authTabs [data-tab="signup"]')
    page.fill("#suUser", name)
    page.fill("#suPass", pw)
    page.fill("#suPass2", pw)
    page.press("#suPass2", "Enter")                                # Enter submits the form you are in
    page.wait_for_selector("#liOk:text('Account created. Log in to continue.')")
    assert page.input_value("#liUser") == name
    page.fill("#liPass", pw)
    page.press("#liPass", "Enter")
    page.wait_for_selector("#app:not([hidden])")
    page.wait_for_selector(".node")


def logout(page):
    if page.is_visible("#auth"):                                   # already signed out
        return
    page.click("#btnUser")
    page.click('#userMenu [data-m="logout"]')
    if page.is_visible("#dlg"):                                    # guests are asked to confirm
        page.click("#dlgYes")
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


def total_cr(page):
    return int(page.text_content("#stDone").split("/")[1].split()[0])


def pos(page, code):
    return page.evaluate("c => plan().pos[c] || null", code)


def drag_to(page, node_id, term):
    a = page.locator(f'.node[data-id="{node_id}"] .card').bounding_box()
    b = page.locator(f'.col[data-key="{term}"] rect.bg').bounding_box()
    page.mouse.move(a["x"] + 60, a["y"] + 30); page.mouse.down()
    page.mouse.move(a["x"] + 90, a["y"] + 40, steps=4)
    page.mouse.move(b["x"] + b["width"] / 2, a["y"] + 30, steps=8); page.mouse.up()


def test_swap_ece201_for_math_path(page):
    logout(page)
    signup(page, "w" + uuid.uuid4().hex[:8])
    open_program(page, "compe")
    before = total_cr(page)
    page.fill("#q", "ECE 201"); page.press("#q", "Enter")
    page.wait_for_selector("#side h2:text('ECE 201')")
    page.click('#side summary:has-text("Swap this course")')
    page.click('#side .row:has-text("MATH 235") button:has-text("Turn on")')

    assert page.locator('.node[data-id="ECE 201"]').count() == 0
    for c in ("MATH 235", "MATH 331", "ECE 296C"):
        assert pos(page, c) == "2-fall"
    for c in ("ECE 213", "ECE 214"):
        assert "err" not in page.get_attribute(f'.node[data-id="{c}"]', "class")
    assert total_cr(page) == before - 4 + 3 + 3 + 1

    drag_to(page, "MATH 331", "2-spring")
    assert pos(page, "MATH 331") == "2-spring"
    for c in ("ECE 213", "ECE 214"):
        assert "err" in page.get_attribute(f'.node[data-id="{c}"]', "class")

    page.click("#stProblems")
    page.click('#side summary:has-text("Swaps")')
    page.click('#side .row:has-text("MATH 235") button:has-text("Turn off")')
    assert pos(page, "ECE 201") == "2-fall"
    for c in ("MATH 235", "MATH 331", "ECE 296C"):
        assert pos(page, c) is None
    for c in ("ECE 213", "ECE 214"):
        assert "err" not in page.get_attribute(f'.node[data-id="{c}"]', "class")
    assert total_cr(page) == before


def test_auth_errors_sit_by_their_field_and_clear(page):
    logout(page)
    page.click('#authTabs [data-tab="signup"]')
    page.fill("#suUser", "x"); page.fill("#suPass", "short"); page.press("#suPass", "Enter")
    assert "3-24" in page.text_content("#suUser-err") and "8" in page.text_content("#suPass-err")
    page.fill("#suUser", "abc")                                    # clears on input
    assert page.text_content("#suUser-err") == ""
    page.fill("#suPass", "password123"); page.fill("#suPass2", "password999"); page.click("#signupForm button[type=submit]")
    assert page.text_content("#suPass2-err") == "Passwords do not match."

    taken = "t" + uuid.uuid4().hex[:8]
    signup(page, taken); logout(page)
    page.click('#authTabs [data-tab="signup"]')
    page.fill("#suUser", taken); page.fill("#suPass", "password123"); page.fill("#suPass2", "password123")
    page.press("#suUser", "Enter")
    page.wait_for_selector("#suUser-err:text('That username is taken.')")
    assert page.is_visible("#signupForm")                          # Enter did not try to log in

    page.click('#authTabs [data-tab="login"]')
    page.fill("#liUser", taken); page.fill("#liPass", "wrong-password"); page.press("#liUser", "Enter")
    page.wait_for_selector("#liPass-err:text('Wrong username or password.')")
    page.fill("#liPass", "password123")
    assert page.text_content("#liPass-err") == ""
    page.press("#liPass", "Enter")
    page.wait_for_selector("#app:not([hidden])")


def test_shared_edit_confirms_and_logs(page):
    logout(page)
    name = "e" + uuid.uuid4().hex[:8]
    signup(page, name)
    open_program(page, "compe")
    page.fill("#q", "ECE 202"); page.press("#q", "Enter")
    page.wait_for_selector("#side h2:text('ECE 202')")
    page.click('#side summary:has-text("Edit")')
    page.fill("#edTitle", "Computational Tools (edited)")
    page.click('#side [data-act="savecourse"]')                    # cancel: nothing changes
    assert "for everyone" in page.text_content("#dlg")
    page.click("#dlgNo")
    assert page.evaluate("S.P.courses['ECE 202'].title") != "Computational Tools (edited)"
    page.click('#side [data-act="savecourse"]')
    page.click("#dlgYes")
    page.wait_for_function("S.P.courses['ECE 202'].title === 'Computational Tools (edited)'")
    page.click("#stProblems")
    page.click('#side summary:has-text("Program")')
    log = page.inner_text("#side pre.log")
    assert f"{name}: ECE 202:" in log

    s = '#side summary:has-text("Program")'                        # mouse focus: no ring; keyboard: ring
    assert page.eval_on_selector(s, "e => getComputedStyle(e).outlineStyle") == "none"
    page.keyboard.press("Shift+Tab"); page.keyboard.press("Tab")
    assert page.eval_on_selector(s, "e => document.activeElement === e && getComputedStyle(e).outlineStyle") == "solid"


def test_paste_catalog_text(page):
    page.click("#btnUpload")
    page.click('.sheet summary:has-text("Paste catalog text")')
    page.fill("#catalog", "ECE 122 - Introduction to Programming (4 credits)\nECE 241 - Advanced Programming (3 credits)\nPrerequisite: ECE 122 and MATH 132.")
    page.fill("#progName", "Pasted catalog")
    page.click("#goCatalog")
    page.wait_for_function("S.P && S.P.name === 'Pasted catalog'")
    page.wait_for_selector('.node[data-id="ECE 241"]')
    assert page.evaluate("S.P.edges.some(e => e.from === 'ECE 122' && e.to === 'ECE 241')")


def fresh(page, key="compe"):
    logout(page)
    signup(page, "z" + uuid.uuid4().hex[:8])
    open_program(page, key)


def test_undo_redo_reset_delete(page):
    fresh(page)
    page.evaluate("moveTo('ECE 202', '2-spring')")
    assert pos(page, "ECE 202") == "2-spring" and page.is_enabled("#btnReset")
    page.click("#btnUndo");  assert pos(page, "ECE 202") == "2-fall"
    page.click("#btnRedo");  assert pos(page, "ECE 202") == "2-spring"
    page.keyboard.press("Control+z"); assert pos(page, "ECE 202") == "2-fall"
    page.keyboard.press("Control+Shift+z"); assert pos(page, "ECE 202") == "2-spring"

    page.click("#btnReset")                                        # back to official, undoable from the toast
    assert pos(page, "ECE 202") == "2-fall" and not page.is_enabled("#btnReset")
    page.click("#toast #tUndo")
    assert pos(page, "ECE 202") == "2-spring"

    page.click("#stProblems"); page.click('#side [data-act="delplan"]')
    assert page.evaluate("S.plans.length") == 1
    page.click("#toast #tUndo")
    assert page.evaluate("S.plans.length") == 2 and pos(page, "ECE 202") == "2-spring"


def crtext(page, term):
    """Visible credit label of a term column (without its hover <title>)."""
    return page.eval_on_selector(f'.col[data-key="{term}"] .cr',
        "e => [...e.childNodes].filter(n => n.nodeName !== 'title').map(n => n.textContent).join(' ')")


def test_overload_is_allowed_until_your_max(page):
    fresh(page)
    page.evaluate("moveTo('ECE 231', '2-fall')")                    # 18 + 4 = 22 cr
    cr = page.locator('.col[data-key="2-fall"] .cr')
    assert crtext(page, "2-fall") == "22 cr (overload)"
    assert "overload" in cr.get_attribute("class")
    assert page.text_content("#stProblems").startswith("○ 0")
    assert crtext(page, "1-fall") == "19 cr (within)"

    cr.click()                                                     # header credits open the limits
    page.wait_for_selector('#side details[data-sec="Credit limits"][open]')
    page.fill('[data-lim="regular:1"]', "21"); page.press('[data-lim="regular:1"]', "Tab")
    cr = page.locator('.col[data-key="2-fall"] .cr')
    assert crtext(page, "2-fall") == "22 cr (over max)" and "over" in cr.get_attribute("class").split()
    assert page.text_content("#stProblems").startswith("✕ 1")
    assert page.is_visible('#side details[data-sec="Credit limits"][open]')   # panel did not snap shut
    page.click('#side [data-act="limdefault"]')
    assert page.text_content("#stProblems").startswith("○ 0")
    page.reload(); page.wait_for_selector(".node")                 # limits are saved with the account
    assert page.evaluate("S.limits.regular") == [19, 30]


def test_fast_program_switch_lands_on_the_last_choice(page):
    fresh(page)
    page.evaluate("""ee => { const f = window.fetch; window._f = f;
        window.fetch = (u, o) => String(u).includes('/api/program/' + ee) ? new Promise(r => setTimeout(r, 700)).then(() => f(u, o)) : f(u, o); }""", PIDS["ee"])
    page.select_option("#progSel", PIDS["ee"])                     # slow
    page.select_option("#progSel", PIDS["compe"])                  # fast, chosen last
    page.wait_for_timeout(1200)
    page.evaluate("window.fetch = window._f")
    assert page.evaluate("S.P.id") == PIDS["compe"] == page.input_value("#progSel")
    assert page.locator('.node[data-id="ECE 322"]').count() == 1    # a CompE-only course is on the map


def test_clear_a_term(page):
    fresh(page)
    clear = '.clr[data-clear="1-fall"]'
    assert page.locator(clear).count() == 0                        # nothing checked, nothing to clear
    page.locator('.node[data-id="MATH 131"] .cb').click()
    page.locator('.node[data-id="ENGIN 112"] .cb').click()         # a partly checked term
    page.locator(clear).click()
    assert page.evaluate("Object.keys(plan().pos).filter(i => plan().pos[i] === '1-fall' && S.done[i]).length") == 0
    assert page.locator(clear).count() == 0
    page.click("#toast #tUndo")
    assert page.evaluate("!!S.done['MATH 131'] && !!S.done['ENGIN 112']")


def test_sign_out_menu(page):
    fresh(page)
    page.click("#btnUser")
    assert "Signed in as" in page.inner_text("#userMenu")
    page.keyboard.press("Escape"); assert page.is_hidden("#userMenu")
    name = page.inner_text("#btnUser")
    logout(page)
    assert page.inner_text("#liOk") == "You are signed out." and page.input_value("#liUser") == name


def test_upload_sheet_clear(page):
    fresh(page)
    page.click("#btnUpload")
    assert not page.is_enabled("#upClear")
    page.set_input_files("#file", os.path.join(SAMPLES, "EE_worksheet.pdf"))
    page.fill("#progName", "x")
    page.click('.sheet summary:has-text("Paste catalog text")'); page.fill("#catalog", "ECE 122 - Intro (4 credits)")
    assert "EE_worksheet.pdf" in page.inner_text("#dropTxt") and page.is_enabled("#upClear")
    page.click("#upClear")
    assert "Drop PDFs here" in page.inner_text("#dropTxt")
    assert page.input_value("#progName") == page.input_value("#catalog") == "" and not page.is_enabled("#upClear")
    page.set_input_files("#file", os.path.join(SAMPLES, "EE_worksheet.pdf"))   # the same file can be chosen again
    assert "EE_worksheet.pdf" in page.inner_text("#dropTxt")
    page.click("#upClear"); page.click("#modal .x")


def test_start_over_and_manage_programs(page):
    fresh(page)
    page.evaluate("moveTo('ECE 202', '2-spring')"); page.locator('.node[data-id="MATH 131"] .cb').click()
    page.click("#stProblems"); page.click('#side summary:has-text("Your data")')
    page.click('#side [data-act="startover"]'); page.click("#dlgYes")
    assert page.evaluate("S.plans.length") == 1 and page.evaluate("Object.keys(S.done).length") == 0
    page.click("#toast #tUndo")
    assert page.evaluate("S.plans.length") == 2 and page.evaluate("!!S.done['MATH 131']")

    page.evaluate("""() => api('/api/typed', {method: 'POST', json: {text: 'MATH 131 | Calc | 4\\nMATH 132 | Calc II | 4', name: 'Throwaway'}})""")
    page.select_option("#progSel", "__manage")
    page.wait_for_selector('#progList .prow:has-text("Throwaway")')
    assert page.input_value("#progSel") == PIDS["compe"]              # the menu entry is not a program
    page.click('#progList .prow:has-text("Throwaway") [data-p="delete"]')
    assert "every user's plans" in page.text_content("#dlg"); page.click("#dlgYes")
    page.wait_for_function("() => ![...document.querySelectorAll('#progList .prow')].some(r => r.textContent.includes('Throwaway'))")
    page.keyboard.press("Escape"); assert page.is_hidden("#progModal")
    assert "Throwaway" not in page.inner_text("#progSel")


def test_selected_card_is_brought_into_view(page):
    fresh(page)
    page.evaluate("view.x = -2000; applyView()")                   # map scrolled far away
    page.evaluate("select('ECE 416')")                              # e.g. clicked from the side panel
    page.wait_for_timeout(600)                                     # let the pan animation finish
    box, stage = page.locator('.node[data-id="ECE 416"] .card').bounding_box(), page.locator("#stage").bounding_box()
    assert stage["x"] <= box["x"] and box["x"] + box["width"] <= stage["x"] + stage["width"]
    page.evaluate("select('ECE 341', true)")                        # an elective not on the map: its chain lights up
    assert page.locator("#world.dim").count() == 1
    assert "hl" in page.get_attribute('.node[data-id="ECE 241"]', "class")
