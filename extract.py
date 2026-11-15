"""CourseTrack extraction: PDF -> one fixed curriculum schema.

No AI needed here. Three geometric/text parsers run on every page:
  1. grid parser      - semester worksheets (term headers + course cells)
  2. flowchart parser - boxes + arrows read from the PDF's vector drawing
  3. notes parser     - "Note N" sections, elective lists, honors, gen-ed
The results from all pages / all uploaded PDFs are merged into one program.
"""
import re, math, hashlib
import pymupdf

CODE_RE = re.compile(r"\b([A-Z][A-Z&\-]{1,9})\s?(H?\d{3}[A-Z]{0,3})\b")
CRED_RE = re.compile(r"\[\s*(\d+)(?:\s*(?:or|-|–|to)\s*(\d+))?\s*cr", re.I)
TERM_RE = re.compile(r"^(Fall|Spring|Winter|Summer|Autumn)\b\s*(?:\[(.*?)\])?", re.I)
NOTE_RE = re.compile(r"^Note\s+(\d+)\s*[·•\-–:.]\s*(.+)$")
NOTEREF_RE = re.compile(r"\[Notes?\s+([\d\s&,and]+)\]", re.I)
OPT_RE = re.compile(
    r"^(?:>>\s*)?([A-Z][A-Z&\-]{1,9}\s?H?\d{3}[A-Z]{0,3}):\s*(.+?)\s*"
    r"(?:\((1st|2nd|both)\s+sem\))?\s*(?:(\d)\s*cr)?\s*[†‡*]?\s*$")
ALIASES = {"CS": "COMPSCI", "E&C-ENG": "ECE", "CMPSCI": "COMPSCI"}
NUMWORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def norm_code(subj, num):
    subj = ALIASES.get(subj.upper(), subj.upper())
    return f"{subj} {num.upper()}"


def find_code(text):
    m = CODE_RE.search(text)
    return (norm_code(*m.groups()), m) if m else (None, None)


def clean(s):
    return re.sub(r"\s+", " ", s.replace("†", "").replace("‡", "")).strip(" *·-–")


# ───────────────────────── page helpers ─────────────────────────
def page_lines(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            t = "".join(s["text"] for s in l["spans"]).strip()
            if t:
                x0, y0, x1, y1 = l["bbox"]
                out.append({"t": t, "x0": x0, "y0": y0, "x1": x1, "y1": y1})
    return out


# ───────────────────────── 1. grid parser ─────────────────────────
def parse_grid(page):
    lines = page_lines(page)
    heads = []
    for l in lines:
        m = TERM_RE.match(l["t"])
        if m and (m.group(2) is not None or len(l["t"]) < 14):
            heads.append((l, m))
    if len(heads) < 2:
        return None
    heads.sort(key=lambda h: h[0]["x0"])
    hy = max(h[0]["y1"] for h in heads)
    cols = []
    for i, (l, m) in enumerate(heads):
        season = m.group(1).lower().replace("autumn", "fall")
        tgt = None
        if m.group(2):
            nums = [int(n) for n in re.findall(r"\d+", m.group(2))]
            tgt = nums[0] if nums else None
        cols.append({"x": l["x0"], "season": season, "target": tgt, "lines": []})
    year = 0
    for i, c in enumerate(cols):
        if c["season"] == "fall" or i == 0:
            year += 1
        c["year"] = year
    # cells are left-aligned while headers are often centred: take the column
    # left edges from where the "[n cr]" lines start, if that gives one per header
    xs = sorted(l["x0"] for l in lines if l["y0"] >= hy - 1 and CRED_RE.match(l["t"]))
    clusters = []
    for x in xs:
        if clusters and x - clusters[-1][0] < 12:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    clusters = [c for c in clusters if len(c) >= 2]
    if len(clusters) == len(cols):
        for c, cl in zip(cols, clusters):
            c["x"] = cl[0]
    else:
        gap = (heads[-1][0]["x0"] - heads[0][0]["x0"]) / max(1, len(heads) - 1)
        for c, (l, m) in zip(cols, heads):
            c["x"] = (l["x0"] + l["x1"]) / 2 - gap / 2
    for l in lines:
        if l["y0"] < hy - 1:
            continue
        ci = None
        for i, c in enumerate(cols):
            if l["x0"] >= c["x"] - 6:
                ci = i
        if ci is not None:
            cols[ci]["lines"].append(l)

    terms, courses, honors, extra, subs = [], {}, [], [], []
    slot_n, sub = 0, None  # sub = an open "Substitute ... for CODE" block collecting its numbered alternates
    for c in cols:
        ls = sorted(c["lines"], key=lambda l: (l["y0"], l["x0"]))
        cells, cur = [], []
        for l in ls:
            if cur and l["y0"] - cur[-1]["y1"] > 5.5:
                cells.append(cur); cur = []
            if cur and cur[-1]["t"] == l["t"]:
                continue
            cur.append(l)
        if cur:
            cells.append(cur)
        items = []
        for cell in cells:
            text = " ".join(l["t"] for l in cell)
            first = cell[0]["t"]
            if "honors" in text.lower() and len(text) > 60:
                honors.append(clean(text)); continue
            cm = CRED_RE.search(text)
            sm = re.search(r"substitut\w*\b.*?\bfor\s+([A-Z][A-Z&\-]{1,9}\s?H?\d{3}[A-Z]{0,3})", text, re.I)
            if sm and not cm:
                sub = {"replaces": [find_code(sm.group(1))[0]], "with": [],
                       "label": clean(re.sub(r"[:(].*$", "", text)), "source": "pdf"}
                subs.append(sub); continue
            if not cm or "not used for" in text.lower():
                continue
            lo = int(cm.group(1)); hi = int(cm.group(2) or lo)
            alt = bool(re.match(r"^(\*|\d+\.)\s", first))
            head = text[:cm.start()]
            code, m = find_code(head)
            refs = []
            for r in NOTEREF_RE.findall(text):
                refs += [int(n) for n in re.findall(r"\d+", r)]
            flag_h = "‡" in text
            if code and m.start() < 6 + (2 if alt else 0) + (3 if alt else 0):
                title = clean(head[m.end():])
                # widget overlays duplicate the code; strip repeats
                title = clean(title.replace(m.group(0), ""))
                rec = {"code": code, "title": title, "credits": lo, "kind": "required",
                       "note_refs": refs, "honors": flag_h}
                if alt:
                    rec["kind"] = "alternate"
                    extra.append(rec)
                    # "* A", "2. B", "3. C" under a substitute header: keep them only while the numbering runs on
                    num = re.match(r"^(\*|\d+)", first).group(1)
                    if sub is not None and (1 if num == "*" else int(num)) == len(sub["with"]) + 1:
                        sub["with"].append(code)
                elif code not in courses:
                    courses[code] = rec; items.append(code)
            elif not alt:
                slot_n += 1
                sid = f"SLOT {slot_n}"
                label = clean(head)
                tagm = re.search(r"cr\s*,\s*([^\]]+)\]", text)
                courses[sid] = {"code": sid, "title": label, "credits": lo, "credits_max": hi,
                                "kind": "slot", "note_refs": refs, "honors": flag_h,
                                "tag": tagm.group(1).strip() if tagm else ""}
                items.append(sid)
        terms.append({"year": c["year"], "season": c["season"], "target": c["target"], "items": items})
    if sum(len(t["items"]) for t in terms) < 3:
        return None
    return {"terms": terms, "courses": courses, "honors": honors, "alternates": extra,
            "substitutions": [x for x in subs if x["with"]]}


# ───────────────────────── 2. flowchart parser ─────────────────────────
def _dist_pt_rect(p, r):
    dx = max(r[0] - p[0], 0, p[0] - r[2]); dy = max(r[1] - p[1], 0, p[1] - r[3])
    return math.hypot(dx, dy)


def parse_flow(page):
    drawings = page.get_drawings()
    words = page.get_text("words")
    boxes = []
    for g in drawings:
        if "s" not in g["type"] or len(g["items"]) != 1 or g["items"][0][0] != "re":
            continue
        r = g["rect"]
        if r.width < 30 or r.height < 14 or r.width > 220:
            continue
        inside = [w for w in words if r.x0 - 1 <= (w[0] + w[2]) / 2 <= r.x1 + 1
                  and r.y0 - 1 <= (w[1] + w[3]) / 2 <= r.y1 + 1]
        inside.sort(key=lambda w: (w[1] + w[3]) / 2)
        rows = []
        for w in inside:
            yc = (w[1] + w[3]) / 2
            if rows and abs(rows[-1][0] - yc) < 4.5:
                rows[-1][1].append(w)
            else:
                rows.append([yc, [w]])
        text = " ".join(w[4] for _, row in rows for w in sorted(row, key=lambda w: w[0]))
        code, m = find_code(text)
        if not code:
            continue
        dashed = bool(g.get("dashes")) and not g["dashes"].startswith("[]")
        boxes.append({"code": code, "title": clean(text[m.end():]), "rect": tuple(r),
                      "elective": dashed})
    # bracketed text-only nodes like [MATH 233]
    line_txt = page_lines(page)
    for l in line_txt:
        m = re.fullmatch(r"\[([A-Z][A-Z&\-]{1,9}\s?\d{3}[A-Z]{0,3})\]", l["t"])
        if m:
            code, _ = find_code(m.group(1))
            boxes.append({"code": code, "title": "", "rect": (l["x0"], l["y0"], l["x1"], l["y1"]),
                          "elective": False, "external": True})
    if len(boxes) < 4:
        return None

    shafts, heads = [], []
    for g in drawings:
        if "s" not in g["type"]:
            continue
        its = [i for i in g["items"] if i[0] == "l"]
        if len(its) != len(g["items"]) or not its or (g.get("width") or 1) > 2:
            continue
        dashed = bool(g.get("dashes")) and not g["dashes"].startswith("[]")
        if len(its) == 1:
            a, b = its[0][1], its[0][2]
            shafts.append({"a": (a.x, a.y), "b": (b.x, b.y), "dashed": dashed})
        elif len(its) == 3:
            pts = [(q.x, q.y) for i in its for q in i[1:]]
            # tip = the point that appears most often
            tip = max(pts, key=lambda p: sum(1 for q in pts if math.dist(p, q) < 0.5))
            heads.append({"pts": pts, "tip": tip})

    def near_box(p, thr=9):
        best, bd = None, thr
        for b in boxes:
            d = _dist_pt_rect(p, b["rect"])
            if d < bd:
                best, bd = b, d
        return best

    for s in shafts:
        s["tip"] = None
        for h in heads:
            if min(math.dist(s["b"], q) for q in h["pts"]) < 1.5:
                s["tip"] = h["tip"]; break
            if min(math.dist(s["a"], q) for q in h["pts"]) < 1.5:
                s["a"], s["b"] = s["b"], s["a"]; s["tip"] = h["tip"]; break

    def source_of(s, depth=0):
        b = near_box(s["a"])
        if b or depth > 4:
            return b
        for o in shafts:
            if o is not s and (math.dist(o["b"], s["a"]) < 2 or math.dist(o["a"], s["a"]) < 2):
                if o["tip"] is None:
                    if math.dist(o["a"], s["a"]) < 2:
                        o = dict(o, a=o["b"], b=o["a"])
                    return source_of(o, depth + 1)
                b = near_box(o["a"])  # fan-out sharing one start point
                if b:
                    return b
        return None

    edges = []
    for s in shafts:
        if s["tip"] is None:
            continue
        src, dst = source_of(s), near_box(s["tip"])
        if not src or not dst or src["code"] == dst["code"]:
            continue
        vertical = abs(s["a"][0] - s["b"][0]) < 2.5
        typ = "coreq" if vertical else "prereq"
        if s["dashed"]:
            typ = "alt_" + typ
        edges.append({"from": src["code"], "to": dst["code"], "type": typ})
    if len(edges) < 2:
        return None
    return {"boxes": boxes, "edges": edges}


# ───────────────────────── 3. notes parser ─────────────────────────
def parse_notes(page):
    blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
    if not any(NOTE_RE.match(l.strip()) for b in blocks for l in b[4].split("\n")):
        return None
    mid = page.rect.width * 0.49
    blocks.sort(key=lambda b: (b[0] >= mid, b[1], b[0]))
    notes, cur = [], None
    for b in blocks:
        for raw in b[4].split("\n"):
            t = raw.strip()
            if not t:
                continue
            m = NOTE_RE.match(t)
            if m:
                cur = {"n": int(m.group(1)), "title": clean(m.group(2)), "lines": [], "options": []}
                notes.append(cur); continue
            if cur is None:
                continue
            cur["lines"].append(t)
            om = OPT_RE.match(t)
            if om:
                code, _ = find_code(om.group(1))
                cur["options"].append({
                    "code": code, "title": clean(om.group(2)),
                    "offered": {"1st": ["fall"], "2nd": ["spring"], "both": ["fall", "spring"]}.get(om.group(3)),
                    "credits": int(om.group(4)) if om.group(4) else None})
    for n in notes:
        n["text"] = " ".join(n.pop("lines"))
        n["checklist"] = [clean(x) for x in re.findall(r"(?:^|\s)\d\.\s+(.+?)(?=\s\d\.\s|\s{2,}|$|\sAlso,)", n["text"])][:8]
        cm = re.search(r"[Cc]hoose\s+(\w+)", n["text"])
        n["choose"] = NUMWORDS.get(cm.group(1).lower()) if cm else None
    return notes


CODE_ONLY = r"[A-Z][A-Z&\-]{1,9}\s?H?\d{3}[A-Z]{0,3}"


def note_substitutions(text):
    """Only two phrasings are trusted; anything vaguer is left out rather than guessed.
      'Students may substitute A, Title, and B, Title, for C.'  -> A + B stand in for C
      'You may use either A or B ...'                            -> B stands in for A"""
    out = []
    for sent in re.split(r"(?<=[.!?])\s+(?=[A-Z†‡*])", text):
        m = re.search(r"\bsubstitute\s+(.+?)\s+for\s+(" + CODE_ONLY + r")\b", sent, re.I)
        if m:
            w = [norm_code(*c.groups()) for c in CODE_RE.finditer(m.group(1))]
            r = find_code(m.group(2))[0]
            if w and r not in w:
                out.append({"replaces": [r], "with": list(dict.fromkeys(w)), "label": clean(sent)[:140], "source": "pdf"})
            continue
        m = re.search(r"\b(?:may|can)\s+(?:use|take)\s+either\s+(" + CODE_ONLY + r")\s+or\s+(" + CODE_ONLY + r")\b", sent)
        if m:
            a, b = find_code(m.group(1))[0], find_code(m.group(2))[0]
            if a != b:
                out.append({"replaces": [a], "with": [b], "label": clean(sent)[:140], "source": "pdf"})
    return out


def merge_substitutions(subs):
    """De-dup by what is replaced; when one list of courses contains another, keep the fuller one."""
    keep = []
    for s in subs:
        for k in keep:
            if set(k["replaces"]) == set(s["replaces"]) and (set(s["with"]) <= set(k["with"]) or set(k["with"]) <= set(s["with"])):
                if len(s["with"]) > len(k["with"]):
                    k.update(s)
                break
        else:
            keep.append(dict(s))
    for s in keep:
        s["id"] = "sub-" + hashlib.sha1(("|".join(s["replaces"]) + ">" + "|".join(s["with"])).encode()).hexdigest()[:8]
    return keep


def parse_prereq_text(page):
    """Catalog-style page: 'ECE 241 ... Prerequisite(s): ECE 122 and MATH 132.'"""
    return prereq_edges(page.get_text())


def prereq_edges(text):
    edges = []
    for m in re.finditer(r"((?:Pre|Co)-?requisites?)\s*:?\s*([^.\n]{3,160})", text, re.I):
        before = text[max(0, m.start() - 400):m.start()]
        owners = list(CODE_RE.finditer(before))
        if not owners:
            continue
        to = norm_code(*owners[0].groups()) if len(owners) == 1 else norm_code(*owners[-1].groups())
        # owner = nearest code that starts a line
        for o in reversed(owners):
            ls = before.rfind("\n", 0, o.start()) + 1
            if o.start() - ls < 4:
                to = norm_code(*o.groups()); break
        typ = "coreq" if m.group(1).lower().startswith("co") else "prereq"
        for c in CODE_RE.finditer(m.group(2)):
            frm = norm_code(*c.groups())
            if frm != to:
                edges.append({"from": frm, "to": to, "type": typ})
    return edges


# ───────────────────────── merge everything ─────────────────────────
def extract_pdfs(paths, name=None):
    courses, edges, plans, notes, honors, alternates, subs = {}, [], [], [], [], [], []
    flow_seen, title_guess, log = False, None, []
    for path in paths:
        doc = pymupdf.open(path)
        for pno, page in enumerate(doc):
            if title_guess is None:
                for l in page_lines(page):
                    if re.search(r"curriculum|flowchart|degree|program|major", l["t"], re.I) and 12 < len(l["t"]) < 110:
                        title_guess = clean(l["t"]); break
            g = parse_grid(page)
            if g:
                log.append(f"p{pno+1}: semester grid, {sum(len(t['items']) for t in g['terms'])} cells")
                if not plans:
                    plans.append(g["terms"])
                    for k, v in g["courses"].items():
                        courses.setdefault(k, {}).update({a: b for a, b in v.items() if b not in (None, "")})
                    honors += g["honors"]; alternates += g["alternates"]; subs += g["substitutions"]
                continue
            f = parse_flow(page)
            if f:
                flow_seen = True
                log.append(f"p{pno+1}: flowchart, {len(f['boxes'])} boxes, {len(f['edges'])} arrows")
                for b in f["boxes"]:
                    c = courses.setdefault(b["code"], {"code": b["code"], "credits": None})
                    if not c.get("title") and b["title"]:
                        c["title"] = b["title"]
                    if "kind" not in c:
                        c["kind"] = "external" if b.get("external") else ("elective" if b["elective"] else "required")
                edges += f["edges"]
                continue
            n = parse_notes(page)
            if n:
                log.append(f"p{pno+1}: notes, {len(n)} sections")
                notes += n
                continue
            pe = parse_prereq_text(page)
            if pe:
                log.append(f"p{pno+1}: prerequisite text, {len(pe)} links")
                edges += pe
                catalog_courses((l["t"] for l in page_lines(page)), courses)
    return assemble(courses, edges, plans[0] if plans else None, notes, honors, alternates,
                    name or title_guess or "My Program", log, subs)


def assemble(courses, edges, terms, notes, honors, alternates, name, log, subs=()):
    # de-dup notes by number
    nd = {}
    for n in notes:
        nd.setdefault(n["n"], n)
    pools, requirements = {}, []
    slots = [c for c in courses.values() if c.get("kind") == "slot"]
    for s in slots:
        pool_note = next((nd[r] for r in s.get("note_refs", []) if r in nd and len(nd[r]["options"]) >= 3), None)
        if pool_note:
            pid = f"note{pool_note['n']}"
            p = pools.setdefault(pid, {"id": pid, "label": pool_note["title"], "options": [],
                                       "choose": 0, "rule": re.split(r"\s[A-Z][A-Z&\-]+ H?\d{3}[A-Z]*:", pool_note["text"])[0].strip()[:320]})
            p["choose"] += 1
            s["pool"] = pid
            for o in pool_note["options"]:
                if o["code"] not in p["options"]:
                    p["options"].append(o["code"])
                c = courses.setdefault(o["code"], {"code": o["code"]})
                c.setdefault("kind", "elective")
                if c["kind"] == "required" and o["code"] not in [i for t in (terms or []) for i in t["items"]]:
                    c["kind"] = "elective"
                if not c.get("title") or len(o["title"]) > len(c.get("title", "")):
                    c["title"] = o["title"]
                c["credits"] = o["credits"] or c.get("credits") or s["credits"]
                if o["offered"]:
                    c["offered"] = o["offered"]
        else:
            ref = next((nd[r] for r in s.get("note_refs", []) if r in nd), None)
            if ref and not any(r["id"] == f"note{ref['n']}" for r in requirements):
                requirements.append({"id": f"note{ref['n']}", "label": ref["title"],
                                     "items": ref["checklist"], "text": ref["text"]})
            if ref:
                s["req"] = f"note{ref['n']}"
    for n in nd.values():
        if re.search(r"honors", n["text"], re.I):
            for sent in re.split(r"(?<=[.!?])\s+", n["text"]):
                if re.search(r"honors|\bDH\b|\bCHC\b", sent) and len(sent) > 25:
                    honors.append(clean(sent))
    for a in alternates:
        c = courses.setdefault(a["code"], a)
        c.setdefault("kind", "alternate"); c.setdefault("title", a["title"]); c["credits"] = c.get("credits") or a["credits"]

    subs = merge_substitutions(list(subs) + [x for n in nd.values() for x in note_substitutions(n["text"])])
    for sb in subs:
        cr = sum(courses.get(r, {}).get("credits") or 0 for r in sb["replaces"]) or 3
        for code in sb["replaces"] + sb["with"]:
            courses.setdefault(code, {"code": code, "kind": "alternate", "title": "", "credits": cr})
    if subs:
        log.append(f"{len(subs)} substitution{'s' if len(subs) > 1 else ''} found")

    # edges: dedupe, keep only known endpoints
    seen, E = set(), []
    for e in edges:
        k = (e["from"], e["to"], e["type"])
        if k in seen or e["from"] not in courses or e["to"] not in courses:
            if e["from"] not in courses or e["to"] not in courses:
                for code in (e["from"], e["to"]):
                    courses.setdefault(code, {"code": code, "kind": "external", "title": ""})
            if k in seen:
                continue
        seen.add(k); E.append(e)

    if not terms:
        terms = auto_plan(courses, E)
        log.append("no semester grid found - built a plan from the prerequisite order")
    placed = {i for t in terms for i in t["items"]}
    for c in courses.values():
        c.setdefault("title", ""); c.setdefault("kind", "required")
        if c.get("credits") is None:
            c["credits"] = 3
        if c["kind"] == "required" and c["code"] not in placed:
            c["kind"] = "external" if not c["title"] else "elective"
        c["note_text"] = [f"Note {r} · {nd[r]['title']}: {nd[r]['text'][:420]}" for r in c.pop("note_refs", []) if r in nd]
    pid = hashlib.sha1((name + "".join(sorted(courses))).encode()).hexdigest()[:10]
    return {"id": pid, "name": name, "courses": courses, "edges": E, "terms": terms,
            "pools": pools, "requirements": requirements, "substitutions": subs,
            "honors": list(dict.fromkeys(honors)),
            "notes": [{"n": n["n"], "title": n["title"], "text": n["text"]} for n in sorted(nd.values(), key=lambda n: n["n"])],
            "log": log}


def auto_plan(courses, edges, cap=16):
    """No grid in the PDF: layer courses by prerequisite depth, cap credits per term."""
    req = [c for c, v in courses.items() if v.get("kind", "required") == "required"]
    pre = {c: [e["from"] for e in edges if e["to"] == c and e["type"].endswith("prereq") and e["from"] in req] for c in req}
    co = {c: [e["from"] for e in edges if e["to"] == c and e["type"].endswith("coreq") and e["from"] in req] for c in req}
    term_of, load, guard = {}, {}, 0
    pending = sorted(req)
    while pending and guard < 500:
        guard += 1
        for c in list(pending):
            if any(p not in term_of for p in pre[c] + co[c]):
                continue
            t = max([term_of[p] + 1 for p in pre[c]] + [term_of[p] for p in co[c]] + [0])
            cr = courses[c].get("credits") or 3
            while load.get(t, 0) + cr > cap:
                t += 1
            term_of[c] = t; load[t] = load.get(t, 0) + cr; pending.remove(c)
    for c in pending:
        term_of[c] = 0
    n = max(term_of.values(), default=0) + 1
    return [{"year": i // 2 + 1, "season": "fall" if i % 2 == 0 else "spring", "target": None,
             "items": [c for c in req if term_of[c] == i]} for i in range(n + (n % 2))]


COURSE_LINE_RE = re.compile(r"^([A-Z][A-Z&\-]{1,9}\s?H?\d{3}[A-Z]{0,3})[\s:.–-]+(.{4,70}?)\.?"
                            r"(?:\s*\(?(\d)\s*(?:cr|credits?)\.?\)?)?\.?$", re.I)


def catalog_courses(lines, courses):
    """Course header lines in catalog text: 'ECE 241 - Advanced Programming (3 credits)'."""
    for t in lines:
        m = COURSE_LINE_RE.match(t.strip())
        if m and CODE_RE.fullmatch(m.group(1)):
            code, _ = find_code(m.group(1))
            c = courses.setdefault(code, {"code": code, "kind": "required"})
            c.setdefault("title", clean(m.group(2)).rstrip("."))
            if m.group(3):
                c["credits"] = int(m.group(3))
    return courses


def parse_catalog(text, name="My Program"):
    """Pasted catalog text (no PDF): the same course-line + 'Prerequisite:' parsing used on catalog pages."""
    courses = catalog_courses(text.splitlines(), {})
    edges = prereq_edges(text)
    log = [f"catalog text: {len(courses)} courses, {len(edges)} links"]
    return assemble(courses, edges, None, [], [], [], name, log)


def parse_typed(text, name="My Program"):
    """One course per line:  ECE 241 | Advanced Programming | 3 | prereq: ECE 122, MATH 132 | coreq: X | term: 2 fall"""
    courses, edges, placed = {}, [], {}
    for raw in text.splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        code, m = find_code(raw)
        if not code:
            continue
        rest = raw[m.end():]
        parts = [p.strip() for p in re.split(r"[|;]", rest) if p.strip()]
        c = {"code": code, "title": "", "credits": 3, "kind": "required"}
        for p in parts:
            low = p.lower()
            if low.startswith(("prereq", "pre:", "coreq", "co:")):
                typ = "coreq" if low.startswith("co") else "prereq"
                for x in CODE_RE.finditer(p):
                    edges.append({"from": norm_code(*x.groups()), "to": code, "type": typ})
            elif low.startswith(("term", "sem")):
                y = re.search(r"\d", p); s = re.search(r"fall|spring|winter|summer", low)
                if y and s:
                    placed[code] = (int(y.group()), s.group())
            elif re.fullmatch(r"\d(\s*cr.*)?", low):
                c["credits"] = int(low[0])
            elif low.startswith("elective"):
                c["kind"] = "elective"
            elif not c["title"]:
                c["title"] = p.lstrip(":,- ")
        courses[code] = c
    terms = None
    if placed and len(placed) >= len(courses) * 0.6:
        ys = max(y for y, _ in placed.values())
        terms = [{"year": y, "season": s, "target": None,
                  "items": [c for c, v in placed.items() if v == (y, s)]}
                 for y in range(1, ys + 1) for s in ("fall", "winter", "spring", "summer")]
        terms = [t for t in terms if t["items"] or t["season"] in ("fall", "spring")]
    return assemble(courses, edges, terms, [], [], [], name, ["typed input"])


if __name__ == "__main__":
    import sys, json
    p = extract_pdfs(sys.argv[1:])
    print(p["name"], "|", len(p["courses"]), "courses,", len(p["edges"]), "edges")
    print("\n".join(p["log"]))
    for t in p["terms"]:
        print(f"Y{t['year']} {t['season']:6} [{t['target']}]", [f"{i}:{p['courses'][i]['credits']}" if not i.startswith('SLOT') else p['courses'][i]['title'] for i in t["items"]])
    print("EDGES", sorted(f"{e['from']}>{e['to']}{'' if e['type']=='prereq' else '('+e['type']+')'}" for e in p["edges"]))
    print("POOLS", {k: (v["label"], v["choose"], len(v["options"])) for k, v in p["pools"].items()})
    print("REQS", json.dumps(p["requirements"])[:700])
    print("HONORS", p["honors"])
    print("SUBS", [(x["replaces"], x["with"], x["label"]) for x in p["substitutions"]])
    print("ALT/ext", [(c["code"], c["kind"]) for c in p["courses"].values() if c["kind"] in ("alternate", "external")])
