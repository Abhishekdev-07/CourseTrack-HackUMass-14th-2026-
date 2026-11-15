"""Golden checks: the CompE worksheet must keep extracting the same way."""
import os, pytest
import extract
from conftest import SAMPLES


@pytest.fixture(scope="module")
def compe():
    return extract.extract_pdfs([os.path.join(SAMPLES, "CompE_worksheet.pdf")])


def edge_type(p, a, b):
    return next((e["type"] for e in p["edges"] if e["from"] == a and e["to"] == b), None)


def test_terms_and_cells(compe):
    assert len(compe["terms"]) == 8
    assert sum(len(t["items"]) for t in compe["terms"]) == 37


def test_edges(compe):
    assert len(compe["edges"]) == 61
    assert edge_type(compe, "ECE 322", "ECE 371") == "coreq"
    assert edge_type(compe, "MATH 132", "ECE 201") == "prereq"


def test_pools(compe):
    assert {"note5", "note6"} <= set(compe["pools"])


def test_substitutions(compe):
    subs = {tuple(s["replaces"]): s for s in compe["substitutions"]}
    math = subs[("ECE 201",)]
    assert math["with"] == ["MATH 235", "MATH 331", "ECE 296C"] and math["source"] == "pdf" and math["id"]
    assert subs[("ECE 341",)]["with"] == ["COMPSCI 311"]
    assert len(compe["substitutions"]) == 2                     # nothing guessed from vaguer sentences


def test_note_substitution_phrasing():
    assert extract.note_substitutions("Students must complete ECE 213 or ECE 214 first.") == []
    s = extract.note_substitutions("Students may substitute MATH 235, Linear Algebra, and MATH 331 for ECE 201. Other text.")
    assert s[0]["replaces"] == ["ECE 201"] and s[0]["with"] == ["MATH 235", "MATH 331"]


CATALOG = """ECE 122 - Introduction to Programming (4 credits)
Basic programming in Python.
ECE 241. Advanced Programming. 3 Credits.
Data structures and algorithms.
Prerequisite: ECE 122 and MATH 132.
ECE 322: Systems Programming (3 cr)
Prerequisites: ECE 241. Corequisite: ECE 371.
"""


def test_parse_catalog_text():
    p = extract.parse_catalog(CATALOG, "Pasted")
    c = p["courses"]
    assert c["ECE 122"]["title"] == "Introduction to Programming" and c["ECE 122"]["credits"] == 4
    assert c["ECE 241"]["title"] == "Advanced Programming" and c["ECE 241"]["credits"] == 3
    got = {(e["from"], e["to"], e["type"]) for e in p["edges"]}
    assert {("ECE 122", "ECE 241", "prereq"), ("MATH 132", "ECE 241", "prereq"),
            ("ECE 241", "ECE 322", "prereq"), ("ECE 371", "ECE 322", "coreq")} <= got
    placed = {i: t for t in p["terms"] for i in t["items"]}
    assert p["terms"].index(placed["ECE 122"]) < p["terms"].index(placed["ECE 241"]) < p["terms"].index(placed["ECE 322"])


def test_program_names_are_short_and_distinct(compe):
    assert compe["name"] == "Computer Engineering (2021–2028)"
    assert extract.program_name("Curriculum Worksheet for the Electrical Engineering Classes of 2021 through 2028") == "Electrical Engineering (2021–2028)"
    assert extract.program_name("Prerequisite Flowchart for Computer Engineering") == "Computer Engineering"
    assert extract.program_name("BS in Biology") == "BS in Biology"


def test_pool_never_offers_a_required_course(compe):
    required = {i for t in compe["terms"] for i in t["items"]}
    for pool in compe["pools"].values():
        assert not required & set(pool["options"])
    opts = [{"code": c, "title": c, "offered": None, "credits": 3} for c in ("ECE 331", "ECE 341", "ECE 344")]
    courses = {"ECE 331": {"code": "ECE 331", "title": "HW Org", "credits": 3, "kind": "required"},
               "SLOT 1": {"code": "SLOT 1", "title": "Elective", "credits": 3, "kind": "slot", "note_refs": [6]}}
    p = extract.assemble(courses, [], [{"year": 1, "season": "fall", "target": None, "items": ["ECE 331", "SLOT 1"]}],
                         [{"n": 6, "title": "Electives", "text": "Choose one.", "options": opts, "checklist": []}], [], [], "T", [])
    assert p["pools"]["note6"]["options"] == ["ECE 341", "ECE 344"]
    assert p["courses"]["ECE 331"]["kind"] == "required"
