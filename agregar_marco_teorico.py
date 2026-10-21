from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

PATH = "Tabla de fuentes sensor buses Medellin.docx"

def set_font(run, size=11, bold=False, italic=False):
    run.font.name = "Aptos"
    run._element.rPr.rFonts.set(qn("w:ascii"), "Aptos")
    run._element.rPr.rFonts.set(qn("w:hAnsi"), "Aptos")
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Aptos")
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    run.font.color.rgb = RGBColor(0, 0, 0)

def heading(doc, text, level):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12 if level == 1 else 8)
    p.paragraph_format.space_after = Pt(5)
    r = p.add_run(text)
    set_font(r, 15 if level == 1 else 12, bold=True)
    return p

def body(doc, parts):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_after = Pt(7)
    p.paragraph_format.line_spacing = 1.15
    for text, italic in parts:
        r = p.add_run(text)
        set_font(r, 11, italic=italic)
    return p

doc = Document(PATH)
doc.add_page_break()

heading(doc, "Marco teórico inicial", 1)
heading(doc, "Introducción al marco teórico", 2)
body(doc, [
    ("El marco teórico reúne los conceptos y antecedentes que orientan el proyecto de un sensor para buses del área metropolitana de Medellín. Su propósito es explicar la relación entre las emisiones generadas por el transporte, la contaminación atmosférica y el monitoreo en tiempo real. A partir de estas bases, el proyecto busca diseñar una solución que permita identificar comportamientos anómalos en las emisiones de un bus y aportar información útil para el mantenimiento preventivo y la reducción de la contaminación. ", False),
    ("La propuesta no elimina por sí sola el dióxido de carbono; su aporte consiste en medir y comunicar datos que permitan tomar decisiones oportunas.", True),
])

heading(doc, "Desarrollo conceptual", 2)
heading(doc, "Emisiones vehiculares y contaminación atmosférica", 2)
body(doc, [
    ("Las emisiones vehiculares son los gases y partículas que se liberan durante la combustión del combustible. Entre los contaminantes relevantes se encuentran el dióxido de carbono (CO₂), asociado al consumo de combustible y al cambio climático, y contaminantes como los óxidos de nitrógeno (NOx), el monóxido de carbono (CO) y el material particulado, que deterioran la calidad del aire y pueden afectar la salud. En el Valle de Aburrá, el análisis del parque automotor y de sus emisiones es necesario para proponer estrategias de disminución de la contaminación (Toro-Gómez & Quiceno-Rendón, 2015).", False),
])
body(doc, [
    ("El transporte público colectivo también influye en la calidad del aire de Medellín. Echeverri et al. (2012) señalan que los cambios en las rutas y la operación de los buses pueden modificar la concentración de contaminantes en zonas específicas. Por ello, la medición de emisiones de cada vehículo puede complementar las estrategias de movilidad y de control ambiental de la ciudad.", False),
])

heading(doc, "Sensor de monitoreo de emisiones", 2)
body(doc, [
    ("Un sensor de monitoreo de emisiones es un dispositivo que capta variables relacionadas con los gases producidos por un vehículo y las convierte en datos que pueden ser consultados por el conductor, la empresa operadora o el personal de mantenimiento. Para este proyecto, el sensor podría ubicarse en el sistema de escape o conectarse a la computadora del bus, siempre que sea compatible con el vehículo. Su función sería registrar cambios inusuales en las emisiones y generar una alerta cuando los valores superen parámetros definidos.", False),
])
body(doc, [
    ("El uso de sensores en buses permite obtener información con mayor detalle temporal y espacial que la de una estación fija. Kaivonen y Ngai (2020) demostraron que los sensores instalados en buses pueden apoyar el monitoreo de la contaminación en tiempo real. Esta idea respalda el uso de un sistema móvil de medición en las rutas del área metropolitana de Medellín.", False),
])

heading(doc, "Variables clave del proyecto", 2)
body(doc, [
    ("Las variables principales son: (a) concentración o nivel estimado de CO₂ y otros contaminantes del escape, como variable de emisión; (b) consumo de combustible, revoluciones del motor y tiempo de ralentí, como variables de operación del bus; (c) ubicación y hora de recorrido, como variables de contexto; y (d) alertas de mantenimiento, como resultado del sistema. La integración de estas variables permite relacionar el estado operativo del vehículo con su comportamiento ambiental.", False),
])
body(doc, [
    ("Además, los sensores de bajo costo con registro de datos y geolocalización pueden facilitar el seguimiento de condiciones variables durante los recorridos. Salthammer et al. (2022) encontraron que el registro en línea de parámetros ambientales y de ubicación es útil para analizar condiciones de calidad del aire según el tiempo y el lugar. En este proyecto, dichos datos servirían para identificar tendencias y priorizar la revisión técnica de los buses con mayores señales de emisión anómala.", False),
])

doc.save(PATH)
print(PATH)
