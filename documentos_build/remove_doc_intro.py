from pathlib import Path

from docx import Document


DOCUMENT_PATH = Path(
    '/Users/os/Documents/ChatGPT/velmorax/fullstack-docker/documentacion/'
    'Evidencia Tecnica Full Stack Docker.docx'
)
TEXT_TO_REMOVE = {
    'Proyecto fullstack-docker. Verificación local en el puerto 8080.',
    'Esta ficha registra la composición que publica una lista de tareas con Astro React, Express y MySQL. '
    'La evidencia se tomó con los tres servicios activos y el CRUD disponible por el proxy Nginx.',
}


def remove_paragraph(paragraph):
    element = paragraph._element
    element.getparent().remove(element)
    paragraph._p = paragraph._element = None


document = Document(DOCUMENT_PATH)
paragraphs = [paragraph for paragraph in document.paragraphs if paragraph.text.strip() in TEXT_TO_REMOVE]

if len(paragraphs) != len(TEXT_TO_REMOVE):
    raise RuntimeError('No se encontraron todas las líneas solicitadas para eliminar.')

for paragraph in paragraphs:
    remove_paragraph(paragraph)

document.save(DOCUMENT_PATH)
