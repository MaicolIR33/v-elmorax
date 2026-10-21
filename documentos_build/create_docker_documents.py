from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path('/Users/os/Documents/ChatGPT/velmorax')


def set_cell_shading(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn('w:shd'))
    if shd is None:
        shd = OxmlElement('w:shd')
        tc_pr.append(shd)
    shd.set(qn('w:fill'), fill)


def set_cell_border(cell, color='D9D9D9', size='6'):
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in('w:tcBorders')
    if borders is None:
        borders = OxmlElement('w:tcBorders')
        tc_pr.append(borders)
    for edge in ('top', 'left', 'bottom', 'right'):
        tag = qn(f'w:{edge}')
        element = borders.find(tag)
        if element is None:
            element = OxmlElement(f'w:{edge}')
            borders.append(element)
        element.set(qn('w:val'), 'single')
        element.set(qn('w:sz'), size)
        element.set(qn('w:color'), color)


def set_cell_margin(cell, top=100, start=120, bottom=100, end=120):
    tc_pr = cell._tc.get_or_add_tcPr()
    mar = tc_pr.first_child_found_in('w:tcMar')
    if mar is None:
        mar = OxmlElement('w:tcMar')
        tc_pr.append(mar)
    for side, value in (('top', top), ('start', start), ('bottom', bottom), ('end', end)):
        node = mar.find(qn(f'w:{side}'))
        if node is None:
            node = OxmlElement(f'w:{side}')
            mar.append(node)
        node.set(qn('w:w'), str(value))
        node.set(qn('w:type'), 'dxa')


def set_repeat_table_header(row):
    tr_pr = row._tr.get_or_add_trPr()
    repeat = OxmlElement('w:tblHeader')
    repeat.set(qn('w:val'), 'true')
    tr_pr.append(repeat)


def add_page_number(paragraph):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run('Página ')
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(95, 95, 95)
    field = OxmlElement('w:fldSimple')
    field.set(qn('w:instr'), 'PAGE')
    paragraph._p.append(field)


def configure_document(document):
    section = document.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(0.68)
    section.bottom_margin = Inches(0.62)
    section.left_margin = Inches(0.72)
    section.right_margin = Inches(0.72)

    normal = document.styles['Normal']
    normal.font.name = 'Aptos'
    normal._element.rPr.rFonts.set(qn('w:eastAsia'), 'Aptos')
    normal.font.size = Pt(10.5)
    normal.paragraph_format.space_after = Pt(6)

    title = document.styles['Title']
    title.font.name = 'Aptos Display'
    title._element.rPr.rFonts.set(qn('w:eastAsia'), 'Aptos Display')
    title.font.size = Pt(25)
    title.font.bold = True
    title.font.color.rgb = RGBColor(0, 0, 0)
    title.paragraph_format.space_after = Pt(4)

    for style_name, size in [('Heading 1', 14), ('Heading 2', 11)]:
        style = document.styles[style_name]
        style.font.name = 'Aptos'
        style._element.rPr.rFonts.set(qn('w:eastAsia'), 'Aptos')
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.paragraph_format.space_before = Pt(13)
        style.paragraph_format.space_after = Pt(5)

    add_page_number(section.footer.paragraphs[0])


def add_title(document, title, subtitle):
    paragraph = document.add_paragraph(style='Title')
    # The built-in Word "Title" style can inherit a bottom border. Override it
    # explicitly so the title remains plain black in Word and LibreOffice.
    paragraph_properties = paragraph._p.get_or_add_pPr()
    existing_borders = paragraph_properties.find(qn('w:pBdr'))
    if existing_borders is not None:
        paragraph_properties.remove(existing_borders)
    borders = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'nil')
    borders.append(bottom)
    paragraph_properties.append(borders)
    paragraph.add_run(title)
    meta = document.add_paragraph()
    meta.paragraph_format.space_after = Pt(12)
    run = meta.add_run(subtitle)
    run.font.size = Pt(9.5)
    run.font.color.rgb = RGBColor(92, 92, 92)


def add_paragraph(document, text):
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.line_spacing = 1.12
    paragraph.add_run(text)
    return paragraph


def add_heading(document, text):
    paragraph = document.add_paragraph(text, style='Heading 1')
    paragraph.paragraph_format.keep_with_next = True
    return paragraph


def add_code(document, code, fill):
    table = document.add_table(rows=1, cols=1)
    table.autofit = False
    table.allow_autofit = False
    cell = table.cell(0, 0)
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    set_cell_shading(cell, fill)
    set_cell_border(cell, 'C7D0DA', '6')
    set_cell_margin(cell, top=100, start=145, bottom=100, end=145)
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.line_spacing = 1.02
    run = paragraph.add_run(code.strip())
    run.font.name = 'Courier New'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'Courier New')
    run.font.size = Pt(8.15)
    run.font.color.rgb = RGBColor(25, 36, 51)
    document.add_paragraph().paragraph_format.space_after = Pt(0)
    return table


def add_table(document, headers, rows, header_fill):
    table = document.add_table(rows=1, cols=len(headers))
    table.style = 'Table Grid'
    table.autofit = True
    table.alignment = WD_ALIGN_PARAGRAPH.CENTER
    header_cells = table.rows[0].cells
    set_repeat_table_header(table.rows[0])
    for index, header in enumerate(headers):
        cell = header_cells[index]
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        set_cell_shading(cell, header_fill)
        set_cell_border(cell, 'D9D9D9', '6')
        set_cell_margin(cell)
        paragraph = cell.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run(header)
        run.font.size = Pt(8.5)
        run.font.bold = True
        run.font.color.rgb = RGBColor(255, 255, 255)

    for row_index, row in enumerate(rows):
        cells = table.add_row().cells
        for index, value in enumerate(row):
            cell = cells[index]
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            set_cell_border(cell, 'D9D9D9', '6')
            set_cell_margin(cell)
            if row_index % 2 == 1:
                set_cell_shading(cell, 'F7F9FB')
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(0)
            run = paragraph.add_run(value)
            run.font.size = Pt(8.7)
    document.add_paragraph().paragraph_format.space_after = Pt(0)
    return table


def add_bullets(document, items):
    for item in items:
        paragraph = document.add_paragraph(style='List Bullet')
        paragraph.paragraph_format.space_after = Pt(2)
        paragraph.add_run(item)


def create_technical_evidence(output_path):
    doc = Document()
    configure_document(doc)
    add_title(doc, 'Evidencia Técnica Full Stack Docker', 'Proyecto fullstack-docker. Verificación local en el puerto 8080.')
    add_paragraph(
        doc,
        'Esta ficha registra la composición que publica una lista de tareas con Astro React, Express y MySQL. '
        'La evidencia se tomó con los tres servicios activos y el CRUD disponible por el proxy Nginx.',
    )

    add_heading(doc, 'Servicios dentro de Docker')
    add_table(
        doc,
        ['Servicio', 'Responsabilidad', 'Prueba local'],
        [
            ('database', 'MySQL 8 con tabla task y volumen mysql data', 'healthy  3306 interno'),
            ('backend', 'API Express y consultas MySQL', 'healthy  3000 publicado'),
            ('frontend', 'Astro React y proxy Nginx', '8080 hacia el navegador'),
        ],
        '17365D',
    )

    add_heading(doc, 'Composición Docker')
    add_code(
        doc,
        '''services:
  database:
    image: mysql:8.0
    volumes:
      - mysql_data:/var/lib/mysql
      - ./database/init.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "mysqladmin ping -h localhost -uroot -p$$MYSQL_ROOT_PASSWORD --silent"]

  backend:
    build: ./backend
    depends_on:
      database:
        condition: service_healthy
    ports: ["3000:3000"]

  frontend:
    build: ./frontend
    ports: ["8080:80"]''',
        'EEF4FB',
    )

    doc.add_page_break()
    add_heading(doc, 'Empaquetado del backend')
    add_code(
        doc,
        '''FROM node:22-alpine AS dependencies
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev

FROM node:22-alpine AS production
WORKDIR /app
ENV NODE_ENV=production
COPY --from=dependencies /app/node_modules ./node_modules
COPY --chown=node:node src ./src
USER node
CMD ["node", "src/index.js"]''',
        'EEF4FB',
    )

    add_heading(doc, 'Pruebas ejecutadas')
    add_code(
        doc,
        '''$ docker compose ps
database   healthy   3306 interno
backend    healthy   3000 publicado
frontend   running   8080 publicado

$ curl http://localhost:8080/api/health
{"status":"ok","db":"connected"}

$ POST  PUT  DELETE /api/tasks/:id
creación  actualización  eliminación  verificadas''',
        'F4F7FA',
    )

    add_heading(doc, 'Resultado')
    add_paragraph(
        doc,
        'La aplicación inicia en orden: MySQL queda saludable, Express se conecta a la tabla task y Nginx expone la interfaz en el puerto 8080. '
        'Las rutas GET, POST, PUT y DELETE se validaron mediante el mismo proxy que usa el navegador.',
    )
    doc.save(output_path)


def create_operational_guide(output_path):
    doc = Document()
    configure_document(doc)
    add_title(doc, 'Guia Operativa Tablero Docker', 'Variante de interfaz  Despliegue y control  Puerto 8180')
    add_paragraph(
        doc,
        'Esta guía explica cómo levantar y comprobar la variante visual del tablero. La funcionalidad es la misma API de tareas, '
        'pero el documento se concentra en el recorrido de una petición, los comandos de operación y la evidencia CRUD.',
    )

    add_heading(doc, 'Arranque controlado')
    add_code(
        doc,
        '''cd fullstack-docker-nova
docker compose up -d --build --wait

# Detener sin borrar las tareas
docker compose down --remove-orphans

# Consultar el estado de los servicios
docker compose ps''',
        'FBF5F1',
    )

    add_heading(doc, 'Ruta de una solicitud')
    add_table(
        doc,
        ['Paso', 'Componente', 'Resultado esperado'],
        [
            ('1', 'Navegador 8180', 'Carga el tablero y solicita /api/tasks'),
            ('2', 'Nginx', 'Reenvía /api al backend interno'),
            ('3', 'Express 3000', 'Valida datos y ejecuta SQL parametrizado'),
            ('4', 'MySQL 8', 'Guarda o devuelve filas de la tabla task'),
        ],
        '5B405B',
    )

    add_heading(doc, 'Proxy incluido en el frontend')
    add_code(
        doc,
        '''server {
  listen 80;
  root /usr/share/nginx/html;

  location /api/ {
    proxy_pass http://backend:3000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  }
}''',
        'FBF5F1',
    )

    doc.add_page_break()
    add_heading(doc, 'Prueba CRUD por el puerto publico')
    add_code(
        doc,
        '''$ curl -X POST http://localhost:8180/api/tasks
{"id":4,"title":"verificación temporal CRUD","completed":false}

$ curl -X PUT http://localhost:8180/api/tasks/4
{"id":4,"title":"verificación temporal CRUD actualizada","completed":true}

$ curl -X DELETE http://localhost:8180/api/tasks/4
DELETE: 204''',
        'F7F1F4',
    )

    add_heading(doc, 'Puntos de control')
    add_table(
        doc,
        ['Dirección', 'Qué confirma'],
        [
            ('http://localhost:8180', 'Interfaz alternativa y botones Añadir Editar Eliminar'),
            ('http://localhost:8180/api/health', 'Respuesta ok y base de datos connected'),
            ('docker compose ps', 'database y backend en estado healthy'),
        ],
        '5B405B',
    )

    add_heading(doc, 'Criterio de cierre')
    add_paragraph(
        doc,
        'El despliegue queda validado cuando la interfaz carga tareas, el estado puede cambiarse, una tarea puede editarse o eliminarse y la respuesta health confirma la conexión con MySQL.',
    )
    doc.save(output_path)


def main():
    create_technical_evidence(
        ROOT / 'fullstack-docker/documentacion/Evidencia Tecnica Full Stack Docker.docx',
    )
    create_operational_guide(
        ROOT / 'fullstack-docker-nova/documentacion/Guia Operativa Tablero Docker.docx',
    )


if __name__ == '__main__':
    main()
