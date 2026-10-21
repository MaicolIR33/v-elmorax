from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn

PATH = "Tabla de fuentes sensor buses Medellin.docx"
HEADINGS = {
    "Marco teórico inicial": 15,
    "Introducción al marco teórico": 12,
    "Desarrollo conceptual": 12,
    "Emisiones vehiculares y contaminación atmosférica": 12,
    "Sensor de monitoreo de emisiones": 12,
    "Variables clave del proyecto": 12,
}

doc = Document(PATH)
for p in doc.paragraphs:
    label = p.text.strip()
    if label in HEADINGS:
        p.paragraph_format.left_indent = Pt(0)
        p.paragraph_format.first_line_indent = Pt(0)
        p.paragraph_format.space_before = Pt(12 if label == "Marco teórico inicial" else 9)
        p.paragraph_format.space_after = Pt(5)
        p.paragraph_format.keep_with_next = True
        for run in p.runs:
            run.font.name = "Aptos"
            run._element.rPr.rFonts.set(qn("w:ascii"), "Aptos")
            run._element.rPr.rFonts.set(qn("w:hAnsi"), "Aptos")
            run.font.size = Pt(HEADINGS[label])
            run.bold = True
doc.save(PATH)
print(PATH)
