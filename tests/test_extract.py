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
