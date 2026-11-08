"""Builds docs/SockLock_MarTech_HW3_Відповіді_1-4.docx from docs/Відповіді_кроки_1-4_людською.md.
Run from socklock-quizleak/:  .venv/bin/python docs/build_docx_answers.py"""
import re
from pathlib import Path
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HERE = Path(__file__).parent
SRC = HERE / "Відповіді_кроки_1-4_людською.md"
OUT = HERE / "SockLock_MarTech_HW3_Відповіді_1-4.docx"
ACCENT = RGBColor(0x1F, 0x4E, 0x79)

doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21), Cm(29.7)
sec.left_margin = sec.right_margin = Cm(2.0)
sec.top_margin = sec.bottom_margin = Cm(1.8)
base = doc.styles["Normal"]
base.font.name, base.font.size = "Calibri", Pt(10.5)
base.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
base.paragraph_format.space_after = Pt(5)
base.paragraph_format.line_spacing = 1.05
for name in ("List Bullet", "List Number"):
    doc.styles[name].font.name, doc.styles[name].font.size = "Calibri", Pt(10.5)

TOKEN = re.compile(r"(\*\*.+?\*\*|`.+?`)")


def runs(p, text, size=None):
    for part in TOKEN.split(text):
        if not part:
            continue
        if part.startswith("**"):
            r = p.add_run(part[2:-2]); r.bold = True
        elif part.startswith("`"):
            r = p.add_run(part[1:-1]); r.font.name = "Consolas"
        else:
            r = p.add_run(part)
        if size:
            r.font.size = Pt(size)


def heading(text, level):
    p = doc.add_paragraph()
    size = {1: 18, 2: 14, 3: 12}[level]
    p.paragraph_format.space_before = Pt(14 if level == 2 else 8)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text); r.bold = True; r.font.size = Pt(size); r.font.color.rgb = ACCENT


def shade(cell, hex_):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), hex_)
    tcPr.append(shd)


def table(lines):
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]
    aligns = [("R" if c.strip().endswith(":") else "L") for c in lines[1].strip().strip("|").split("|")]
    rows = [rows[0]] + rows[2:]
    t = doc.add_table(rows=len(rows), cols=len(rows[0]))
    t.style = "Table Grid"
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            c = t.cell(i, j); c.text = ""
            p = c.paragraphs[0]; p.paragraph_format.space_after = Pt(0)
            if aligns[j] == "R" and i > 0:
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            runs(p, val, size=10)
            if i == 0:
                for r in p.runs:
                    r.bold = True
                shade(c, "DCE6F1")
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


lines = SRC.read_text(encoding="utf-8").splitlines()
i = 0
while i < len(lines):
    ln = lines[i]
    if not ln.strip():
        i += 1; continue
    if ln.startswith("# "):
        heading(ln[2:], 1)
    elif ln.startswith("## "):
        heading(ln[3:], 2)
    elif ln.startswith("### "):
        heading(ln[4:], 3)
    elif ln.startswith("|"):
        block = []
        while i < len(lines) and lines[i].startswith("|"):
            block.append(lines[i]); i += 1
        table(block); continue
    elif re.match(r"\d+\. ", ln):
        p = doc.add_paragraph(style="List Number"); runs(p, re.sub(r"^\d+\. ", "", ln))
        p.paragraph_format.space_after = Pt(2)
    elif ln.startswith("- "):
        p = doc.add_paragraph(style="List Bullet"); runs(p, ln[2:])
        p.paragraph_format.space_after = Pt(2)
    else:
        p = doc.add_paragraph(); runs(p, ln)
    i += 1

doc.save(OUT)
print(OUT)
