from docx import Document
from docx.shared import Pt, RGBColor
from docx.oxml import OxmlElement
from docx.text.paragraph import Paragraph
from docx.oxml.ns import qn

PATH = "Tabla de fuentes sensor buses Medellin.docx"

def set_run(run, size, bold=True):
    run.font.name = "Aptos"
    run._element.rPr.rFonts.set(qn("w:ascii"), "Aptos")
    run._element.rPr.rFonts.set(qn("w:hAnsi"), "Aptos")
    run.font.size = Pt(size)
    run.bold = bold
    run.font.color.rgb = RGBColor(0, 0, 0)

def insert_after(paragraph, text):
    new_p = OxmlElement("w:p")
    paragraph._p.addnext(new_p)
    return Paragraph(new_p, paragraph._parent)

doc = Document(PATH)
target = next(p for p in doc.paragraphs if p.text.strip() == "Marco teórico inicial")

target.text = "3. Redacción del marco teórico inicial"
target.paragraph_format.space_before = Pt(0)
target.paragraph_format.space_after = Pt(12)
for r in target.runs:
    set_run(r, 13)

marco = insert_after(target, "Marco teórico")
marco.paragraph_format.space_before = Pt(0)
marco.paragraph_format.space_after = Pt(8)
marco.paragraph_format.keep_with_next = True
r = marco.add_run("Marco teórico")
set_run(r, 15)

doc.save(PATH)
print(PATH)
