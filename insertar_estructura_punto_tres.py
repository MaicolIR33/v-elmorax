from docx import Document
from docx.shared import Pt, RGBColor
from docx.oxml import OxmlElement
from docx.text.paragraph import Paragraph
from docx.oxml.ns import qn

PATH = "Tabla de fuentes sensor buses Medellin.docx"

def insert_after(paragraph):
    new_p = OxmlElement("w:p")
    paragraph._p.addnext(new_p)
    return Paragraph(new_p, paragraph._parent)

doc = Document(PATH)
point = next(p for p in doc.paragraphs if p.text.strip() == "3. Redacción del marco teórico inicial")

# Insert only if the subheading is not already present.
if not any(p.text.strip() == "a. Estructura y contenido" for p in doc.paragraphs):
    p = insert_after(point)
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(8)
    r = p.add_run("a. Estructura y contenido")
    r.font.name = "Aptos"
    r._element.rPr.rFonts.set(qn("w:ascii"), "Aptos")
    r._element.rPr.rFonts.set(qn("w:hAnsi"), "Aptos")
    r.font.size = Pt(12)
    r.bold = True
    r.font.color.rgb = RGBColor(0, 0, 0)

doc.save(PATH)
print(PATH)
