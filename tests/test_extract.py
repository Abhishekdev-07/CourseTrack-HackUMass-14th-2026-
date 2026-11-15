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
