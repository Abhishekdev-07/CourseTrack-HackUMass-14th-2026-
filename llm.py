"""Optional AI pass. Runs ONCE per upload, in a background thread, and is cached
by file hash - so it never blocks the page and never runs twice for the same PDF.

The geometric parser already produced the courses, plan and arrows. The model is
only asked for a small JSON *patch* (missed links, rules hidden in footnotes),
which keeps the response short and the call fast.

The app works with NO key at all. To switch the AI pass on, set ONE of:
    export GEMINI_API_KEY=...          (Google AI Studio key)
    export ANTHROPIC_API_KEY=sk-ant-...
Optional:  export COURSETRACK_MODEL=<model id>   to override the default model
"""
import os, json, base64, re, urllib.request

PROVIDER = "gemini" if os.environ.get("GEMINI_API_KEY") else "anthropic"
MODEL = os.environ.get("COURSETRACK_MODEL") or ("gemini-2.5-flash" if PROVIDER == "gemini" else "claude-sonnet-5-5")
API_URL = "https://api.anthropic.com/v1/messages"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PROMPT = """You are checking an automatic extraction of a university curriculum PDF.
Below is the draft (course codes and prerequisite links) produced by a geometric parser.
Read the attached PDF(s) and return ONLY a JSON object, no prose, with this shape:

{
 "add_edges":    [{"from":"CODE","to":"CODE","type":"prereq|coreq|alt_prereq","why":"short"}],
 "remove_edges": [{"from":"CODE","to":"CODE"}],
 "courses":      [{"code":"CODE","title":"...","credits":3,"offered":["fall","spring"]}],
 "rules":        ["short plain-English rule a student must know, e.g. 'At least two electives must be 500-level'"],
 "honors":       ["short honors-track requirement"],
 "total_credits": 124
}

Only include things you can see in the PDF. Use the exact course codes from the draft
where they exist. Keep it small: only corrections and additions, do not repeat the draft.

DRAFT:
"""


def enabled():
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("GEMINI_API_KEY"))


def _post(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={**headers, "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


def _pdf_b64(path):
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode()


def _ask_gemini(pdf_paths, prompt):
    parts = [{"inline_data": {"mime_type": "application/pdf", "data": _pdf_b64(p)}} for p in pdf_paths]
    parts.append({"text": prompt})
    out = _post(GEMINI_URL.format(model=MODEL),
                {"contents": [{"parts": parts}], "generationConfig": {"responseMimeType": "application/json"}},
                {"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    return "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"])


def _ask_anthropic(pdf_paths, prompt):
    content = [{"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                               "data": _pdf_b64(p)}} for p in pdf_paths]
    content.append({"type": "text", "text": prompt})
    out = _post(API_URL, {"model": MODEL, "max_tokens": 2500, "messages": [{"role": "user", "content": content}]},
                {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
    return "".join(b.get("text", "") for b in out.get("content", []))


def refine(pdf_paths, program):
    draft = {"courses": sorted(program["courses"]),
             "edges": [f"{e['from']} -> {e['to']} ({e['type']})" for e in program["edges"]]}
    prompt = PROMPT + json.dumps(draft)
    text = _ask_gemini(pdf_paths, prompt) if PROVIDER == "gemini" else _ask_anthropic(pdf_paths, prompt)
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


def apply_patch(program, patch):
    """Merge the AI patch into the program. Everything it adds is tagged source='ai'."""
    C, added = program["courses"], 0
    for c in patch.get("courses", []):
        code = c.get("code")
        if not code:
            continue
        cur = C.setdefault(code, {"code": code, "title": "", "credits": 3, "kind": "elective", "note_text": []})
        for k in ("title", "credits", "offered"):
            if c.get(k) and not cur.get(k):
                cur[k] = c[k]
    rm = {(e.get("from"), e.get("to")) for e in patch.get("remove_edges", [])}
    program["edges"] = [e for e in program["edges"] if (e["from"], e["to"]) not in rm]
    have = {(e["from"], e["to"]) for e in program["edges"]}
    for e in patch.get("add_edges", []):
        if e.get("from") in C and e.get("to") in C and (e["from"], e["to"]) not in have:
            program["edges"].append({"from": e["from"], "to": e["to"],
                                     "type": e.get("type", "prereq"), "source": "ai", "why": e.get("why", "")})
            added += 1
    program["rules"] = list(dict.fromkeys(program.get("rules", []) + patch.get("rules", [])))
    program["honors"] = list(dict.fromkeys(program.get("honors", []) + patch.get("honors", [])))
    if patch.get("total_credits"):
        program["total_credits"] = patch["total_credits"]
    program["log"].append(f"AI pass ({MODEL}): +{added} links, -{len(rm)} links, {len(patch.get('rules', []))} rules")
    return program
