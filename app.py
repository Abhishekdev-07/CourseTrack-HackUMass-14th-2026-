"""CourseTrack - upload a curriculum PDF, get an interactive degree tree.

Run locally:   pip install -r requirements.txt && python app.py   ->  http://127.0.0.1:5000
Run hosted:    gunicorn app:app

Storage is deliberately simple so there is nothing to set up:
  data/programs/*.json   extracted curricula (shared by everyone)
  data/coursetrack.db    SQLite: accounts + each user's plans, checkmarks and notes
"""
import os, json, hashlib, threading, glob, sqlite3, secrets, re
from datetime import timedelta
from functools import wraps
from flask import Flask, request, jsonify, render_template, abort, session, g
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import extract, llm

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("COURSETRACK_DATA", os.path.join(BASE, "data"))
PROG_DIR, UP_DIR, CACHE_DIR = (os.path.join(DATA, d) for d in ("programs", "uploads", "cache"))
LIB, DB, KEYFILE = (os.path.join(DATA, f) for f in ("known_edges.json", "coursetrack.db", "secret.key"))
for d in (PROG_DIR, UP_DIR, CACHE_DIR):
    os.makedirs(d, exist_ok=True)


def secret_key():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    if not os.path.exists(KEYFILE):          # generated once, so logins survive restarts
        with open(KEYFILE, "w") as f:
            f.write(secrets.token_hex(32))
    return open(KEYFILE).read().strip()


app = Flask(__name__)
app.config.update(SECRET_KEY=secret_key(), MAX_CONTENT_LENGTH=40 * 1024 * 1024,
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=timedelta(days=30))
AI = {}  # program id -> {"status": off|running|done|error, "msg": str}
lock = threading.Lock()


# ───────────────────────── database + accounts ─────────────────────────
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()


with sqlite3.connect(DB) as _c:
    _c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE,
        pw TEXT, guest INTEGER DEFAULT 0, last_program TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS state(user_id INTEGER, program_id TEXT, data TEXT,
        updated TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(user_id, program_id));
    """)


def current_user():
    uid = session.get("uid")
    return db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if uid else None


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **k):
        g.user = current_user()
        if not g.user:
            return jsonify(error="Please log in."), 401
        return fn(*a, **k)
    return wrapper


def start_session(uid):
    session.clear(); session.permanent = True; session["uid"] = uid


def me_json(u):
    return {"username": u["username"], "guest": bool(u["guest"]), "last_program": u["last_program"]}


@app.get("/api/me")
@login_required
def me():
    return jsonify(me_json(g.user))


@app.post("/api/signup")
def signup():
    d = request.get_json(silent=True) or {}
    name, pw = (d.get("username") or "").strip(), d.get("password") or ""
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{3,24}", name):
        return jsonify(error="Username: 3-24 letters, numbers, dot, dash or underscore.", field="username"), 400
    if len(pw) < 8:
        return jsonify(error="Password needs at least 8 characters.", field="password"), 400
    try:
        cur = db().execute("INSERT INTO users(username, pw) VALUES(?,?)", (name, generate_password_hash(pw)))
        db().commit()
    except sqlite3.IntegrityError:
        return jsonify(error="That username is taken.", field="username"), 409
    if d.get("login", True) is False:          # the web client asks the user to log in explicitly
        return jsonify(created=True, username=name)
    start_session(cur.lastrowid)
    return jsonify(me_json(current_user()))


@app.post("/api/login")
def login():
    d = request.get_json(silent=True) or {}
    u = db().execute("SELECT * FROM users WHERE username=? AND guest=0", ((d.get("username") or "").strip(),)).fetchone()
    if not u or not check_password_hash(u["pw"], d.get("password") or ""):
        return jsonify(error="Wrong username or password.", field="password"), 401
    start_session(u["id"])
    return jsonify(me_json(u))


@app.post("/api/guest")
def guest():
    cur = db().execute("INSERT INTO users(username, guest) VALUES(?,1)", ("guest-" + secrets.token_hex(4),))
    db().commit(); start_session(cur.lastrowid)
    return jsonify(me_json(current_user()))


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.route("/api/state/<pid>", methods=["GET", "PUT"])
@login_required
def state(pid):
    """Everything personal for one program: what-if plans, completed courses, notes."""
    if not pid.isalnum():
        abort(400)
    if request.method == "GET":
        r = db().execute("SELECT data FROM state WHERE user_id=? AND program_id=?", (g.user["id"], pid)).fetchone()
        db().execute("UPDATE users SET last_program=? WHERE id=?", (pid, g.user["id"])); db().commit()
        return jsonify(json.loads(r["data"]) if r else {})
    body = request.get_data(as_text=True)
    if len(body) > 400_000:
        return jsonify(error="Too large."), 413
    json.loads(body)
    db().execute("INSERT INTO state(user_id, program_id, data) VALUES(?,?,?) ON CONFLICT(user_id, program_id) "
                 "DO UPDATE SET data=excluded.data, updated=CURRENT_TIMESTAMP", (g.user["id"], pid, body))
    db().commit()
    return jsonify(ok=True)


# ───────────────────────── programs ─────────────────────────
def ppath(pid):
    if not pid.isalnum():
        abort(400)
    return os.path.join(PROG_DIR, pid + ".json")


def save(p):
    with lock, open(ppath(p["id"]), "w") as f:
        json.dump(p, f, indent=1)


def load(pid):
    if not os.path.exists(ppath(pid)):
        abort(404)
    with open(ppath(pid)) as f:
        return json.load(f)


def library(p):
    """Prerequisites are facts about courses, not about one major. Every link we
    learn is remembered and re-used for the next program that has the same courses."""
    lib = json.load(open(LIB)) if os.path.exists(LIB) else []
    have = {(e["from"], e["to"]) for e in p["edges"]}
    n = 0
    for e in lib:
        if e["from"] in p["courses"] and e["to"] in p["courses"] and (e["from"], e["to"]) not in have:
            p["edges"].append(dict(e, source="library")); have.add((e["from"], e["to"])); n += 1
    if n:
        p["log"].append(f"+{n} links re-used from earlier uploads")
    known = {(e["from"], e["to"]) for e in lib}
    lib += [{"from": e["from"], "to": e["to"], "type": e["type"]} for e in p["edges"]
            if (e["from"], e["to"]) not in known and e.get("source") != "library"]
    with lock, open(LIB, "w") as f:
        json.dump(lib, f)
    return p


def ai_job(pid, paths, digest):
    cache = os.path.join(CACHE_DIR, digest + ".json")
    try:
        if os.path.exists(cache):
            patch = json.load(open(cache))
        else:
            patch = llm.refine(paths, load(pid))
            json.dump(patch, open(cache, "w"))
        save(llm.apply_patch(load(pid), patch))
        AI[pid] = {"status": "done", "msg": "AI refinement merged"}
    except Exception as ex:  # never break the app because the API hiccuped
        AI[pid] = {"status": "error", "msg": str(ex)[:200]}


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/programs")
@login_required
def programs():
    out = []
    for f in sorted(glob.glob(os.path.join(PROG_DIR, "*.json")), key=os.path.getmtime, reverse=True):
        p = json.load(open(f))
        out.append({"id": p["id"], "name": p["name"]})
    return jsonify(out)


@app.route("/api/program/<pid>", methods=["GET", "PUT", "DELETE"])
@login_required
def program(pid):
    if request.method == "GET":
        return jsonify(load(pid))
    if request.method == "DELETE":
        if g.user["guest"]:
            return jsonify(error="Create an account to delete programs."), 403
        os.remove(ppath(pid)); return jsonify(ok=True)
    p = request.get_json(); p["id"] = pid
    save(p); return jsonify(ok=True)


@app.post("/api/upload")
@login_required
def upload():
    files = [f for f in request.files.getlist("files") if f.filename.lower().endswith(".pdf")]
    if not files:
        return jsonify(error="Upload at least one PDF."), 400
    paths, h = [], hashlib.sha256()
    for f in files:
        data = f.read(); h.update(data)
        path = os.path.join(UP_DIR, hashlib.sha1(data).hexdigest()[:12] + "_" + secure_filename(f.filename))
        open(path, "wb").write(data); paths.append(path)
    try:
        p = extract.extract_pdfs(paths, request.form.get("name") or None)
    except Exception as ex:
        return jsonify(error=f"Could not read that PDF: {ex}"), 400
    if len(p["courses"]) < 2:
        return jsonify(error="No course codes found. If the PDF is a scan, type the courses in instead."), 400
    p = library(p); save(p)
    if llm.enabled():
        AI[p["id"]] = {"status": "running", "msg": "AI is reading the footnotes in the background..."}
        threading.Thread(target=ai_job, args=(p["id"], paths, h.hexdigest()), daemon=True).start()
    else:
        AI[p["id"]] = {"status": "off", "msg": ""}
    return jsonify(program=p, ai=AI[p["id"]])


@app.post("/api/typed")
@login_required
def typed():
    d = request.get_json()
    p = extract.parse_typed(d.get("text", ""), d.get("name") or "My Program")
    if len(p["courses"]) < 1:
        return jsonify(error="No course codes found. Use lines like:  ECE 241 | Advanced Programming | 3 | prereq: ECE 122"), 400
    p = library(p); save(p)
    return jsonify(program=p, ai={"status": "off", "msg": ""})


@app.get("/api/ai/<pid>")
@login_required
def ai_status(pid):
    return jsonify(AI.get(pid, {"status": "off", "msg": ""}))


if __name__ == "__main__":
    app.run(debug=os.environ.get("DEBUG") == "1", port=int(os.environ.get("PORT", 5000)))
