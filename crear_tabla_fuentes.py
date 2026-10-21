from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

OUT = "Tabla de fuentes sensor buses Medellin.docx"

def shade(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)

def borders(cell):
    tc_pr = cell._tc.get_or_add_tcPr()
    borders_el = tc_pr.first_child_found_in("w:tcBorders")
    if borders_el is None:
        borders_el = OxmlElement("w:tcBorders")
        tc_pr.append(borders_el)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = "w:" + edge
        el = borders_el.find(qn(tag))
        if el is None:
            el = OxmlElement(tag)
            borders_el.append(el)
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "6")
        el.set(qn("w:color"), "D9D9D9")

def margins(cell):
    tc_pr = cell._tc.get_or_add_tcPr()
    mar = tc_pr.first_child_found_in("w:tcMar")
    if mar is None:
        mar = OxmlElement("w:tcMar")
        tc_pr.append(mar)
    for side in ("top", "start", "bottom", "end"):
        el = mar.find(qn("w:" + side))
        if el is None:
            el = OxmlElement("w:" + side)
            mar.append(el)
        el.set(qn("w:w"), "95")
        el.set(qn("w:type"), "dxa")

def set_cell_text(cell, text, bold=False, color=None, center=False, size=8):
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER if center else WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0
    r = p.add_run(text)
    r.bold = bold
    r.font.name = "Aptos"
    r._element.rPr.rFonts.set(qn("w:eastAsia"), "Aptos")
    r.font.size = Pt(size)
    if color:
        r.font.color.rgb = RGBColor(*color)

doc = Document()
sec = doc.sections[0]
sec.top_margin = Inches(0.62)
sec.bottom_margin = Inches(0.62)
sec.left_margin = Inches(0.55)
sec.right_margin = Inches(0.55)

styles = doc.styles
styles["Normal"].font.name = "Aptos"
styles["Normal"]._element.rPr.rFonts.set(qn("w:eastAsia"), "Aptos")
styles["Normal"].font.size = Pt(10)

title = doc.add_paragraph()
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
title.paragraph_format.space_after = Pt(5)
run = title.add_run("Tabla de fuentes académicas")
run.font.name = "Aptos Display"
run.font.size = Pt(27)
run.bold = True
run.font.color.rgb = RGBColor(0, 0, 0)

intro = doc.add_paragraph()
intro.alignment = WD_ALIGN_PARAGRAPH.CENTER
intro.paragraph_format.space_after = Pt(12)
ir = intro.add_run("Proyecto: Sensor para monitoreo de emisiones y contaminación en buses del área metropolitana de Medellín")
ir.italic = True
ir.font.size = Pt(10)

headers = ["Nro.", "Título de la fuente", "Tipo de fuente", "Enfoque", "Referencia completa (APA 7.ª edición)"]
rows = [
    ["1", "Estimación de la demanda energética y de las emisiones vehiculares en el Valle de Aburrá durante el periodo 2000–2010, usando el modelo LEAP", "Artículo de revista científica", "Nacional (Colombia: Valle de Aburrá/Medellín)", "Toro-Gómez, M. V., & Quiceno-Rendón, D. M. (2015). Estimación de la demanda energética y de las emisiones vehiculares en el Valle de Aburrá durante el periodo 2000–2010, usando el modelo LEAP. DYNA, 82(189), 45–51. https://doi.org/10.15446/dyna.v82n189.41991"],
    ["2", "Metodología para evaluar el impacto ambiental sobre la calidad del aire en los proyectos de rediseño de rutas de transporte público colectivo en las ciudades. Estudio de caso: Medellín", "Artículo de revista científica", "Nacional (Colombia: Medellín)", "Echeverri, C., Valencia-Hernández, G., & Acosta, A. (2012). Metodología para evaluar el impacto ambiental sobre la calidad del aire en los proyectos de rediseño de rutas de transporte público colectivo en las ciudades. Estudio de caso: Medellín. Revista Ingenierías Universidad de Medellín, 11(20), 31–42. https://revistas.udem.edu.co/index.php/ingenierias/article/view/642"],
    ["3", "Monitoreo en tiempo real de la contaminación del aire con sensores en un autobús urbano", "Artículo de revista científica", "Internacional (Suecia)", "Kaivonen, S., & Ngai, E. C.-H. (2020). Real-time air pollution monitoring with sensors on city bus. Digital Communications and Networks, 6(1), 23–30. https://doi.org/10.1016/j.dcan.2019.03.003"],
    ["4", "Seguimiento temporal y espacial de la calidad del aire en el transporte público local", "Artículo de revista científica", "Internacional (Alemania)", "Salthammer, T., Fauck, C., Omelan, A., Wientzek, S., & Uhde, E. (2022). Time and spatially resolved tracking of the air quality in local public transport. Scientific Reports, 12, Article 3262. https://doi.org/10.1038/s41598-022-07290-5"],
]

table = doc.add_table(rows=1, cols=5)
table.alignment = WD_TABLE_ALIGNMENT.CENTER
table.autofit = False
widths = [0.35, 1.45, 0.95, 1.05, 3.05]
for i, width in enumerate(widths):
    table.columns[i].width = Inches(width)
for i, h in enumerate(headers):
    c = table.rows[0].cells[i]
    c.width = Inches(widths[i])
    c.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    shade(c, "1F4E78")
    borders(c); margins(c)
    set_cell_text(c, h, bold=True, color=(255,255,255), center=True, size=8)

for idx, data in enumerate(rows):
    cells = table.add_row().cells
    fill = "F3F7FA" if idx % 2 else "FFFFFF"
    for i, value in enumerate(data):
        c = cells[i]
        c.width = Inches(widths[i])
        c.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        shade(c, fill)
        borders(c); margins(c)
        set_cell_text(c, value, center=(i == 0), size=7.5)

doc.add_paragraph().paragraph_format.space_after = Pt(0)
note = doc.add_paragraph()
note.paragraph_format.space_before = Pt(4)
note.paragraph_format.space_after = Pt(0)
nr = note.add_run("Nota: ")
nr.bold = True
note.add_run("El sensor permitiría detectar emisiones anómalas y apoyar decisiones de mantenimiento y operación. Por sí solo no elimina el CO₂.")
for r in note.runs:
    r.font.size = Pt(8.5)

doc.save(OUT)
print(OUT)
