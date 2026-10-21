from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor


DOCUMENT_PATH = Path(
    '/Users/os/Documents/ChatGPT/velmorax/fullstack-docker/documentacion/'
    'Evidencia Tecnica Full Stack Docker.docx'
)


def remove_title_border(paragraph):
    properties = paragraph._p.get_or_add_pPr()
    existing = properties.find(qn('w:pBdr'))
    if existing is not None:
        properties.remove(existing)

    borders = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'nil')
    borders.append(bottom)
    properties.append(borders)


def add_centered_paragraph(document, text, size, *, bold=False, before=0, after=0, style=None):
    paragraph = document.add_paragraph(style=style) if style else document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(before)
    paragraph.paragraph_format.space_after = Pt(after)
    run = paragraph.add_run(text)
    run.font.name = 'Aptos'
    run._element.rPr.rFonts.set(qn('w:ascii'), 'Aptos')
    run._element.rPr.rFonts.set(qn('w:hAnsi'), 'Aptos')
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor(0, 0, 0)
    return paragraph


document = Document(DOCUMENT_PATH)

if any(paragraph.text.strip() == 'Maicol Andrés Ospina' for paragraph in document.paragraphs):
    raise RuntimeError('La portada ya está incluida en el documento.')

first_content = document.paragraphs[0]._p
cover = []

title = add_centered_paragraph(
    document,
    'Evidencia Técnica Full Stack Docker',
    29,
    bold=True,
    before=180,
    after=16,
    style='Title',
)
remove_title_border(title)
cover.append(title)

cover.append(add_centered_paragraph(document, 'Documentación técnica', 13, before=0, after=0))
cover.append(add_centered_paragraph(document, 'Maicol Andrés Ospina', 14, bold=True, before=112, after=8))
cover.append(add_centered_paragraph(document, 'Ficha 3229209', 11.5, before=0, after=0))

page_break = document.add_paragraph()
page_break.add_run().add_break(WD_BREAK.PAGE)
cover.append(page_break)

body = first_content.getparent()
insert_at = body.index(first_content)
for paragraph in cover:
    body.remove(paragraph._p)
    body.insert(insert_at, paragraph._p)
    insert_at += 1

document.save(DOCUMENT_PATH)
