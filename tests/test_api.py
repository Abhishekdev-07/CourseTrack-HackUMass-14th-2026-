import json, uuid, pytest
import app as appmod


@pytest.fixture
def client():
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def uname():
    return "u" + uuid.uuid4().hex[:10]


def signup(c, name, pw="correct-horse"):
    return c.post("/api/signup", json={"username": name, "password": pw})


def test_signup_and_login(client):
    name = uname()
    r = signup(client, name)
    assert r.status_code == 200 and r.get_json()["username"] == name
    client.post("/api/logout")
    r = client.post("/api/login", json={"username": name, "password": "correct-horse"})
    assert r.status_code == 200
    assert client.get("/api/me").get_json()["username"] == name


def test_wrong_password_is_401(client):
    name = uname(); signup(client, name); client.post("/api/logout")
    assert client.post("/api/login", json={"username": name, "password": "nope-nope"}).status_code == 401


def test_programs_need_session(client):
    assert client.get("/api/programs").status_code == 401


def test_state_round_trip(client):
    signup(client, uname())
    blob = {"done": {"MATH 131": True}, "notes": {"MATH 131": "hi"}, "plans": []}
    assert client.put("/api/state/abc123", data=json.dumps(blob), content_type="application/json").status_code == 200
    assert client.get("/api/state/abc123").get_json() == blob


def test_guest_cannot_delete_program(client):
    signup(client, uname())
    r = client.post("/api/typed", json={"text": "MATH 131 | Calc I | 4\nMATH 132 | Calc II | 4 | prereq: MATH 131", "name": "T"})
    pid = r.get_json()["program"]["id"]
    client.post("/api/logout")
    client.post("/api/guest")
    assert client.delete(f"/api/program/{pid}").status_code == 403
    assert client.get(f"/api/program/{pid}").status_code == 200


def test_signup_without_login_creates_no_session(client):
    name = uname()
    r = client.post("/api/signup", json={"username": name, "password": "correct-horse", "login": False})
    assert r.status_code == 200 and r.get_json() == {"created": True, "username": name}
    assert client.get("/api/me").status_code == 401
    assert client.post("/api/login", json={"username": name, "password": "correct-horse"}).status_code == 200


def test_signup_errors_name_the_field(client):
    assert signup(client, "ab").get_json()["field"] == "username"
    assert signup(client, uname(), "short").get_json()["field"] == "password"
    name = uname(); signup(client, name); client.post("/api/logout")
    r = signup(client, name)
    assert r.status_code == 409 and r.get_json()["field"] == "username"


def test_program_edits_are_logged_server_side(client):
    name = uname(); signup(client, name)
    pid = client.post("/api/typed", json={"text": "MATH 131 | Calc I | 4", "name": "L"}).get_json()["program"]["id"]
    p = client.get(f"/api/program/{pid}").get_json()
    before = len(p["log"])
    p["courses"]["MATH 131"]["title"] = "Calculus I"
    p["log"] = ["forged"]; p["_edit"] = "MATH 131: title"
    r = client.put(f"/api/program/{pid}", json=p).get_json()
    assert r["log_entry"]["edited_by"] == name and r["log_entry"]["at"]
    log = client.get(f"/api/program/{pid}").get_json()["log"]
    assert len(log) == before + 1 and log[-1]["msg"] == "MATH 131: title" and "forged" not in log


def test_catalog_endpoint(client):
    signup(client, uname())
    r = client.post("/api/catalog", json={"text": "ECE 122 - Intro (4 credits)\nECE 241 - Adv (3 credits)\nPrerequisite: ECE 122.", "name": "C"})
    assert r.status_code == 200 and any(e["from"] == "ECE 122" and e["to"] == "ECE 241" for e in r.get_json()["program"]["edges"])
    assert client.post("/api/catalog", json={"text": "nothing here"}).status_code == 400
