"""Builds small curriculum PDFs laid out as TABLES (not grids, not flowcharts), the way many
departments publish them. Used by test_extract.py; run directly to write them to samples/.
  stacked:     'Year 1 - Fall Semester' heading, then Course | Title | Credits | Prerequisites rows
  sidebyside:  Fall and Spring tables next to each other under 'First Year', 'Second Year'
  plain:       one table with a header row and no terms at all
"""
import os, pymupdf

STACKED = [
    ("Year 1 - Fall Semester", [("MATH 131", "Calculus I", "4", ""), ("ECE 122", "Introduction to Programming", "4", ""),
                                ("ENGLWRIT 112", "College Writing", "3", ""), ("Gen Ed Elective", "", "4", "")]),
    ("Year 1 - Spring Semester", [("MATH 132", "Calculus II", "4", "MATH 131"), ("ECE 241", "Advanced Programming", "3", "ECE 122"),
                                  ("PHYSICS 151", "Physics I", "4", "Coreq: MATH 131")]),
    ("Year 2 - Fall Semester", [("ECE 201", "Analytical Tools", "4", "MATH 132"), ("ECE 242", "Data Structures", "3", "ECE 241 or COMPSCI 187"),
                                ("Technical Elective", "", "3", "")]),
    ("Year 2 - Spring Semester", [("ECE 213", "Signals and Systems", "4", "ECE 201 and MATH 132")]),
]


def table(page, x, y, rows, header=True):
    cols = [x, x + 70, x + 230, x + 280]
    if header:
        for cx, h in zip(cols, ("Course", "Title", "Credits", "Prerequisites")):
            page.insert_text((cx, y), h, fontsize=9, fontname="hebo")
        y += 14
    for r in rows:
        for cx, v in zip(cols, r):
            if v:
                page.insert_text((cx, y), v, fontsize=9)
        y += 13
    return y


def stacked(path):
    doc = pymupdf.open(); page = doc.new_page(width=612, height=792)
    page.insert_text((40, 40), "BS Widget Engineering - Four Year Plan", fontsize=13, fontname="hebo")
    y = 70
    for head, rows in STACKED:
        page.insert_text((40, y), head, fontsize=11, fontname="hebo"); y = table(page, 40, y + 16, rows) + 12
    doc.save(path)


def sidebyside(path):
    doc = pymupdf.open(); page = doc.new_page(width=792, height=612)
    page.insert_text((40, 36), "Sample Plan of Study: Widget Science", fontsize=13, fontname="hebo")
    blocks = [("First Year", STACKED[0][1], STACKED[1][1]), ("Second Year", STACKED[2][1], STACKED[3][1])]
    y = 64
    for year, fall, spring in blocks:
        page.insert_text((40, y), year, fontsize=11, fontname="hebo")
        page.insert_text((40, y + 16), "Fall", fontsize=10, fontname="hebo")
        page.insert_text((410, y + 16), "Spring", fontsize=10, fontname="hebo")
        y1 = table(page, 40, y + 30, [r[:3] + (r[3],) for r in fall])
        y2 = table(page, 410, y + 30, spring)
        y = max(y1, y2) + 18
    doc.save(path)


def plain(path):
    doc = pymupdf.open(); page = doc.new_page(width=612, height=792)
    page.insert_text((40, 40), "Required Courses", fontsize=13, fontname="hebo")
    table(page, 40, 70, [r for _, rows in STACKED for r in rows if r[0][0].isupper() and r[0].split()[-1][:1].isdigit()])
    doc.save(path)


def build(folder):
    out = {}
    for name, fn in (("stacked", stacked), ("sidebyside", sidebyside), ("plain", plain)):
        out[name] = os.path.join(folder, f"table_{name}.pdf"); fn(out[name])
    return out


if __name__ == "__main__":
    print(build(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")))
