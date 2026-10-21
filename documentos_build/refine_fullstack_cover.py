from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor


DOCUMENT_PATH = Path(
    '/Users/os/Documents/ChatGPT/velmorax/fullstack-docker/documentacion/'
    'Evidencia Tecnica Full Stack Docker.docx'
)
SIZES = (29, 13, 14, 11.5)


def set_cover_font(run, size, bold=False):
    run.font.name = 'Liberation Sans'
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor(0, 0, 0)

    properties = run._element.get_or_add_rPr()
    fonts = properties.rFonts
    if fonts is None:
        fonts = OxmlElement('w:rFonts')
        properties.insert(0, fonts)
    for attribute in ('ascii', 'hAnsi', 'eastAsia', 'cs'):
        fonts.set(qn(f'w:{attribute}'), 'Liberation Sans')
    for attribute in ('asciiTheme', 'hAnsiTheme', 'eastAsiaTheme', 'cstheme'):
        fonts.attrib.pop(qn(f'w:{attribute}'), None)

    spacing = properties.find(qn('w:spacing'))
    if spacing is None:
        spacing = OxmlElement('w:spacing')
        properties.append(spacing)
    spacing.set(qn('w:val'), '0')


document = Document(DOCUMENT_PATH)
cover_paragraphs = document.paragraphs[:4]

if [paragraph.text for paragraph in cover_paragraphs] != [
    'Evidencia Técnica Full Stack Docker',
    'Documentación técnica',
    'Maicol Andrés Ospina',
    'Ficha 3229209',
]:
    raise RuntimeError('La portada no tiene el contenido esperado.')

for paragraph, size in zip(cover_paragraphs, SIZES):
    for run in paragraph.runs:
        set_cover_font(run, size, bold=paragraph.text in {
            'Evidencia Técnica Full Stack Docker',
            'Maicol Andrés Ospina',
        })

document.save(DOCUMENT_PATH)
