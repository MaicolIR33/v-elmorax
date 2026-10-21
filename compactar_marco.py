from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

PATH = "Tabla de fuentes sensor buses Medellin.docx"
HEADINGS = {
    "3. Redacción del marco teórico inicial", "Marco teórico", "Introducción al marco teórico",
    "Desarrollo conceptual", "Emisiones vehiculares y contaminación atmosférica",
    "Sensor de monitoreo de emisiones", "Variables clave del proyecto"
}

doc = Document(PATH)
in_marco = False
for p in doc.paragraphs:
    if p.text.strip() == "3. Redacción del marco teórico inicial":
        in_marco = True
    if in_marco and p.text.strip() not in HEADINGS and p.text.strip():
        p.paragraph_format.line_spacing = 1.04
        p.paragraph_format.space_after = Pt(5)
        for run in p.runs:
            run.font.size = Pt(10.5)
    elif p.text.strip() in HEADINGS:
        if p.text.strip() != "3. Redacción del marco teórico inicial":
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.left_indent = Pt(0)
        p.paragraph_format.first_line_indent = Pt(0)
doc.save(PATH)
print(PATH)
