from __future__ import annotations

from pathlib import Path
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path("/Users/os/Documents/ChatGPT/velmorax")
OUT = ROOT / "outputs" / "01a06dff-d0de-74e3-9cd7-d01803d9682b"
OUTPUT = OUT / "Maicol_Ospina_Juan_Bastidas_Emanuel_Castano_Plan_Continuidad_Velmorax.docx"

NAVY = "1F4E78"
LIGHT_BLUE = "D9EAF7"
PALE_BLUE = "EEF5FA"
LIGHT_GRAY = "F2F2F2"
BORDER = "D9D9D9"
BLACK = RGBColor(0, 0, 0)


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_border(cell, color: str = BORDER, size: str = "6") -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = qn(f"w:{edge}")
        element = borders.find(tag)
        if element is None:
            element = OxmlElement(f"w:{edge}")
            borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), size)
        element.set(qn("w:color"), color)


def set_cell_margins(cell, top=90, start=100, bottom=90, end=100) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{margin}"))
        if node is None:
            node = OxmlElement(f"w:{margin}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def keep_paragraph(paragraph, next_para=False) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    tag_name = "keepNext" if next_para else "keepLines"
    if p_pr.find(qn(f"w:{tag_name}")) is None:
        p_pr.append(OxmlElement(f"w:{tag_name}"))


def style_table(table, widths=None, font_size=8.6) -> None:
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    repeat_table_header(table.rows[0])
    for row_index, row in enumerate(table.rows):
        for col_index, cell in enumerate(row.cells):
            set_cell_border(cell)
            set_cell_margins(cell)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if widths and col_index < len(widths):
                cell.width = Inches(widths[col_index])
            set_cell_shading(cell, NAVY if row_index == 0 else (PALE_BLUE if row_index % 2 == 0 else "FFFFFF"))
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_after = Pt(0)
                paragraph.paragraph_format.line_spacing = 1.05
                for run in paragraph.runs:
                    run.font.name = "Aptos"
                    run.font.size = Pt(font_size if row_index else font_size + 0.2)
                    run.font.color.rgb = RGBColor(255, 255, 255) if row_index == 0 else BLACK
                    run.bold = row_index == 0


def add_table(doc, headers, rows, widths=None, font_size=8.6):
    table = doc.add_table(rows=1, cols=len(headers))
    table.rows[0].cells[0].text = headers[0]
    for i, value in enumerate(headers[1:], 1):
        table.rows[0].cells[i].text = value
    for values in rows:
        cells = table.add_row().cells
        for i, value in enumerate(values):
            cells[i].text = str(value)
    style_table(table, widths, font_size)
    doc.add_paragraph()
    return table


def add_bullet(doc, text, level=0):
    p = doc.add_paragraph(style="List Bullet" if level == 0 else "List Bullet 2")
    p.add_run(text)
    return p


def add_number(doc, text):
    p = doc.add_paragraph(style="List Number")
    p.add_run(text)
    return p


def add_manual_number(doc, number, text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.28)
    p.paragraph_format.first_line_indent = Inches(-0.28)
    p.add_run(f"{number}.  ").bold = True
    p.add_run(text)
    return p


def add_heading(doc, text, level=1):
    p = doc.add_heading(text, level=level)
    keep_paragraph(p, next_para=True)
    return p


def set_repeatable_footer(section) -> None:
    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run("Velmorax  Plan de usuarios backup recuperación y continuidad   Ficha 3229209   ")
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    p._p.append(fld)
    for run in p.runs:
        run.font.name = "Aptos"
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(90, 90, 90)


def build_document() -> Document:
    doc = Document()
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.65)
    section.left_margin = Inches(0.72)
    section.right_margin = Inches(0.72)
    set_repeatable_footer(section)

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Aptos"
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = BLACK
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.12
    for style_name, size in (("Title", 24), ("Heading 1", 16), ("Heading 2", 12.5), ("Heading 3", 11)):
        style = styles[style_name]
        style.font.name = "Aptos Display" if style_name != "Normal" else "Aptos"
        style.font.size = Pt(size)
        style.font.color.rgb = BLACK
        style.font.bold = True
        style.font.underline = False
    styles["Heading 1"].paragraph_format.space_before = Pt(12)
    styles["Heading 1"].paragraph_format.space_after = Pt(6)
    styles["Heading 2"].paragraph_format.space_before = Pt(8)
    styles["Heading 2"].paragraph_format.space_after = Pt(4)

    # Cover
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(48)
    r = p.add_run("SERVICIO NACIONAL DE APRENDIZAJE SENA")
    r.bold = True; r.font.name = "Aptos"; r.font.size = Pt(13); r.font.color.rgb = BLACK
    title = doc.add_paragraph(style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = Pt(48)
    title.add_run("Plan de gestión de usuarios backup recuperación y continuidad de Velmorax")
    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.paragraph_format.space_before = Pt(12)
    subtitle.add_run("Evidencia de la clase 6").bold = True
    meta = doc.add_table(rows=4, cols=2)
    meta.alignment = WD_TABLE_ALIGNMENT.CENTER
    meta_rows = [
        ("Aprendices", "Maicol Andrés Ospina, Juan David Bastidas y Emanuel Castaño"),
        ("Ficha", "3229209"),
        ("Programa", "Análisis y Desarrollo de Software"),
        ("Sistema", "Velmorax  Flujo veterinario"),
    ]
    for i, (key, value) in enumerate(meta_rows):
        meta.cell(i, 0).text = key
        meta.cell(i, 1).text = value
        set_cell_shading(meta.cell(i, 0), LIGHT_BLUE)
        for cell in meta.rows[i].cells:
            set_cell_border(cell); set_cell_margins(cell, 120, 130, 120, 130)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        meta.cell(i, 0).paragraphs[0].runs[0].bold = True
    meta.columns[0].width = Inches(1.5); meta.columns[1].width = Inches(4.8)
    p = doc.add_paragraph("Septiembre de 2026")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(46)
    doc.add_page_break()

    add_heading(doc, "Introducción", 1)
    doc.add_paragraph(
        "Este plan define cómo controlaremos las cuentas, los respaldos y la recuperación de Velmorax. "
        "El alcance se concentra en el flujo veterinario que está implementado en el repositorio: acceso por roles, "
        "agenda, pacientes, historia clínica, inventario por lotes, administración de sedes y auditoría. La prioridad "
        "es recuperar primero la operación clínica y evitar que una falla técnica produzca pérdida de información o "
        "accesos indebidos."
    )
    doc.add_paragraph(
        "El sistema ya cuenta con PostgreSQL para producción, una opción local con SQLite, endpoints de salud, registros "
        "de auditoría y un ciclo automatizado de backup cifrado. El documento separa lo que existe hoy de las reglas "
        "operativas que proponemos para usar esas capacidades de forma controlada."
    )

    add_heading(doc, "Descripción del sistema", 1)
    doc.add_paragraph(
        "Velmorax es una aplicación web construida con FastAPI y plantillas Jinja. Su propósito es apoyar la operación "
        "de una clínica veterinaria sin perder la separación entre organizaciones y sedes. La aplicación centraliza "
        "la atención de mascotas, la agenda del personal, el consumo de insumos y los movimientos de inventario."
    )
    add_heading(doc, "Módulos principales", 2)
    add_table(doc, ["Módulo", "Uso principal", "Datos críticos"], [
        ["Acceso y administración", "Inicio de sesión, recuperación de contraseña, usuarios, roles, sedes y configuración.", "Credenciales cifradas, estado de cuenta, permisos, organización y sede."],
        ["Agenda", "Creación y seguimiento de citas y disponibilidad del profesional.", "Paciente, tutor, fecha, hora, sede, profesional y estado."],
        ["Clínica veterinaria", "Pacientes, consultas, diagnósticos, evolución y cierre diario.", "Identificación de mascota y tutor, antecedentes, diagnóstico y tratamiento."],
        ["Inventario", "Recepción, lotes, vencimientos, cadena de frío, movimientos, consumo y traslados.", "Producto, lote, cantidades, costos, vencimiento, temperatura, responsable y trazabilidad."],
        ["Auditoría y operación", "Exportación de eventos, respaldo administrativo y comprobaciones de salud.", "Actor, acción, entidad, fecha, resultado y estado de servicios."],
    ], [1.45, 2.75, 3.0], 8.5)
    doc.add_paragraph(
        "Los usuarios principales son el propietario de la organización, el administrador, el equipo clínico y el "
        "personal de inventario. Los datos más sensibles son las credenciales, la historia clínica, la identidad del tutor, "
        "la programación de citas y la trazabilidad de medicamentos o insumos."
    )

    add_heading(doc, "Gestión de usuarios y privilegios", 1)
    doc.add_paragraph(
        "Aplicaremos mínimo privilegio: cada cuenta tendrá los permisos necesarios para su función y una sede definida. "
        "Velmorax calcula los permisos a partir del rol y permite excepciones por usuario. Estas excepciones no se usarán "
        "como solución permanente; cada una deberá tener solicitud, aprobación, fecha de vencimiento y evidencia."
    )
    add_heading(doc, "Cuentas roles y responsables", 2)
    add_table(doc, ["Cuenta o rol", "Responsable", "Permisos principales", "Módulos habilitados"], [
        ["Owner", "Propietario de la organización", "Todos los permisos, incluida administración y aprobación de inventario.", "Administración, agenda, clínica, inventario y reportes."],
        ["Administrador", "Administrador designado por la clínica", "Gestiona usuarios, sedes, agenda, clínica e inventario; aprueba abastecimiento.", "Todos los módulos operativos y administración."],
        ["Equipo clínico", "Coordinador veterinario", "Consulta inventario, consume insumos, gestiona agenda y registra atención clínica.", "Agenda, pacientes, historia clínica e inventario de consulta."],
        ["Inventario", "Responsable de almacén", "Consulta y administra inventario y registra consumos; no aprueba su propia solicitud.", "Inventario y reportes relacionados."],
        ["Cuenta técnica de backup", "Responsable técnico", "Acceso solo a PostgreSQL y al almacenamiento de respaldos; sin ingreso al módulo clínico.", "Servicio de backup en infraestructura."],
    ], [1.2, 1.55, 2.75, 2.0], 8.1)

    add_heading(doc, "Alta baja y cambio", 2)
    add_number(doc, "Alta. El jefe del área solicita la cuenta indicando nombre, rol, sede, módulos y fecha de inicio. El administrador verifica la necesidad, crea la cuenta con clave temporal y registra la solicitud. El usuario cambia la clave en el primer acceso.")
    add_number(doc, "Cambio. El jefe del área solicita el ajuste de rol, sede o permisos. El administrador compara el acceso actual con el solicitado, obtiene aprobación del owner cuando aumenta privilegios, aplica el cambio y conserva el registro de auditoría.")
    add_number(doc, "Baja. Cuando una persona se retira o cambia de función, el jefe informa de inmediato. El administrador desactiva la cuenta, revoca sesiones y permisos especiales, reasigna tareas pendientes y verifica que no pueda iniciar sesión. La cuenta no se elimina para conservar trazabilidad.")
    doc.add_paragraph(
        "Cada revisión mensual comparará las cuentas activas con el personal vigente. Las cuentas sin responsable, las "
        "inactivas por más de noventa días o las que conserven permisos incompatibles se suspenderán hasta su validación."
    )

    add_heading(doc, "Privilegios temporales", 2)
    add_table(doc, ["Paso", "Control"], [
        ["Solicitud", "El jefe del área abre un registro con usuario, permiso, motivo, sede y tiempo requerido."],
        ["Aprobación", "El administrador valida el alcance. El owner aprueba permisos administrativos o de aprobación de inventario."],
        ["Duración", "Máximo ocho horas para soporte urgente y hasta siete días para reemplazos. Una extensión requiere una nueva aprobación."],
        ["Activación", "El administrador aplica una excepción individual. No comparte cuentas ni contraseñas."],
        ["Evidencia", "El log conserva actor, usuario afectado, permisos anteriores y nuevos, motivo, fecha de inicio y vencimiento."],
        ["Cierre", "Al vencer el plazo, el administrador retira la excepción y verifica los permisos efectivos. Mientras no exista vencimiento automático, esta revocación queda como tarea obligatoria con alarma de calendario."],
    ], [1.25, 5.95], 8.8)

    add_heading(doc, "Plan de backup", 1)
    doc.add_paragraph(
        "Usaremos una estrategia de respaldo completo porque el tamaño actual de Velmorax permite copiar la base cada seis "
        "horas y simplifica la restauración. El servicio de producción ejecuta pg dump en formato custom, comprueba su "
        "estructura, cifra el archivo con AES 256, calcula SHA 256 y lo restaura en una base temporal. Así se evita depender "
        "de una cadena larga de incrementales para recuperar la operación. Si el volumen crece y la ventana deja de ser "
        "suficiente, se complementará con archivos WAL para recuperación a un punto en el tiempo."
    )
    add_heading(doc, "Alcance frecuencia y retención", 2)
    add_table(doc, ["Elemento", "Tipo y frecuencia", "Retención", "Responsable"], [
        ["Base PostgreSQL", "Completo cifrado cada 6 horas y copia adicional antes de cada despliegue.", "30 días en línea; cierre mensual por 6 meses.", "Responsable técnico."],
        ["Base SQLite local", "Copia consistente cuando se use en desarrollo o demostración y antes de cambios de esquema.", "Últimas 10 copias de trabajo.", "Integrante que realiza la prueba."],
        ["Configuración", "Copia por cada cambio. Incluye ejemplos y parámetros; los secretos van en gestor seguro, no en Git.", "Versiones vigentes y dos anteriores.", "Administrador técnico."],
        ["Código fuente", "Cada cambio aprobado se conserva en Git y cada entrega se marca con una versión.", "Historial permanente del repositorio.", "Equipo de desarrollo."],
        ["Versión desplegada", "Etiqueta de imagen o commit por despliegue y registro de la versión estable anterior.", "Mínimo 6 meses.", "Responsable de despliegue."],
        ["Documentación", "Copia con cada entrega o cambio operativo.", "Historial permanente en repositorio y copia externa mensual.", "Documentador."],
    ], [1.35, 3.15, 1.45, 1.25], 8.2)

    add_heading(doc, "Almacenamiento y regla 3 2 1", 2)
    doc.add_paragraph(
        "Mantendremos tres copias: los datos de producción, el backup cifrado en un volumen o disco separado y una copia "
        "externa con versionado. Los dos medios serán el almacenamiento del servidor y el almacenamiento remoto corporativo. "
        "La copia externa quedará fuera del servidor de Velmorax mediante el destino configurado en BACKUP REMOTE. La clave "
        "de cifrado se conservará en un gestor de contraseñas empresarial y en custodia separada; no se guardará junto al backup."
    )
    doc.add_paragraph(
        "El servicio técnico revisará cada día los archivos last success at, last success file y last success status. Una copia "
        "más antigua que siete horas, un checksum inválido o una restauración temporal fallida generará un incidente de respaldo."
    )

    add_heading(doc, "Plan de restauración", 1)
    doc.add_paragraph(
        "El responsable técnico dirige la restauración y el líder del incidente autoriza el reemplazo de producción. La meta "
        "para una recuperación ordinaria es restablecer la aplicación en un máximo de cuatro horas; el tiempo real se anotará "
        "en la bitácora del incidente."
    )
    add_heading(doc, "Procedimiento", 2)
    restore_steps = [
        "Declarar el incidente, detener cambios y registrar la hora, el alcance y la última transacción conocida.",
        "Confirmar que la falla está en datos o infraestructura. Si la base sigue accesible, generar una copia de emergencia antes de modificarla.",
        "Seleccionar el backup más reciente anterior a la falla y verificar el archivo SHA 256, la fecha y el estado verified.",
        "Descifrar y restaurar primero en una base aislada mediante restore backup. Nunca se probará directamente sobre producción.",
        "Validar que existan las tablas requeridas: organizations, users, patients, appointments, inventory items, inventory movements, alerts y audit events.",
        "Ejecutar consultas de conteo y revisar una muestra de pacientes, citas, lotes y movimientos. Confirmar que no haya cantidades negativas ni relaciones rotas.",
        "Detener temporalmente la aplicación, conservar el estado fallido y reemplazar la base únicamente con autorización del líder del incidente.",
        "Iniciar PostgreSQL y Velmorax. Verificar health live, health ready y health; después probar login, consulta de agenda, historia clínica e inventario.",
        "Permitir el acceso a un grupo pequeño, observar logs y métricas durante quince minutos y luego habilitar el servicio general.",
        "Documentar backup usado, checksum, responsables, tiempos, validaciones, resultado y datos que deban reconstruirse por superar el RPO.",
    ]
    for number, step in enumerate(restore_steps, 1):
        add_manual_number(doc, number, step)
    add_heading(doc, "Criterio de aceptación", 2)
    doc.add_paragraph(
        "La restauración se considera válida cuando PostgreSQL responde, los tres endpoints de salud reportan estado correcto, "
        "un usuario autorizado puede iniciar sesión y los recorridos de agenda, paciente, historia clínica e inventario funcionan "
        "sin errores. También se compararán conteos de tablas y se revisarán logs durante quince minutos."
    )

    add_heading(doc, "Prueba de restauración", 2)
    doc.add_paragraph(
        "El ciclo actual ya restaura cada backup en una base temporal y comprueba las tablas operativas. Además de esa comprobación "
        "automática, una vez al mes haremos una prueba supervisada en un entorno aislado. El responsable técnico ejecutará la "
        "restauración y un integrante distinto validará los recorridos funcionales."
    )
    add_table(doc, ["Dato de la prueba", "Registro requerido"], [
        ["Periodicidad", "Mensual y antes de cambios importantes de infraestructura."],
        ["Entorno", "Servidor o contenedor aislado sin conexión a usuarios de producción."],
        ["Responsables", "Responsable técnico ejecuta; líder del incidente o delegado valida."],
        ["Evidencia", "Fecha, backup y checksum, comandos, hora de inicio y fin, tablas verificadas, pruebas funcionales, resultado y acciones pendientes."],
        ["Resultado esperado", "Restauración completa dentro de cuatro horas y pérdida máxima acorde con el RPO del proceso."],
    ], [1.65, 5.55], 8.8)

    add_heading(doc, "Continuidad del servicio", 1)
    doc.add_paragraph(
        "RTO es el tiempo máximo para recuperar un proceso. RPO es la cantidad máxima de información que aceptamos reconstruir "
        "desde la última copia válida. Los valores siguientes corresponden al tamaño actual del sistema y deberán revisarse cuando "
        "Velmorax atienda más sedes o urgencias durante veinticuatro horas."
    )
    add_table(doc, ["Proceso crítico", "Prioridad", "RTO", "RPO", "Justificación"], [
        ["Acceso y control de sesión", "Crítica", "1 hora", "No aplica a datos clínicos", "Sin autenticación no se puede operar de forma segura."],
        ["Consulta de pacientes e historia clínica", "Crítica", "2 horas", "6 horas", "El veterinario necesita antecedentes para atender y evitar decisiones sin contexto."],
        ["Agenda y citas", "Alta", "4 horas", "6 horas", "La clínica puede usar una lista temporal, pero debe reconciliarla al recuperar."],
        ["Inventario y consumo clínico", "Alta", "4 horas", "6 horas", "Las salidas pueden anotarse temporalmente, con riesgo controlado por lote y responsable."],
        ["Administración de usuarios y sedes", "Media", "8 horas", "24 horas", "Los accesos existentes pueden continuar mientras no se requieran altas o cambios."],
        ["Reportes y exportaciones", "Baja", "24 horas", "24 horas", "No bloquean la atención inmediata."],
    ], [2.15, .75, .65, .75, 3.0], 7.9)

    add_heading(doc, "Plan de contingencia", 1)
    doc.add_paragraph(
        "El plan se activa si health ready falla durante más de cinco minutos, la base no responde, existe pérdida o corrupción "
        "de datos, se detecta acceso no autorizado, un despliegue causa errores críticos o la copia válida más reciente supera el RPO."
    )
    add_table(doc, ["Momento", "Acción", "Responsable"], [
        ["Primeros 15 minutos", "Declarar el incidente, detener despliegues, asignar líder, conservar logs y verificar alcance.", "Líder del incidente y responsable técnico."],
        ["Contención", "Aislar el componente afectado, revocar credenciales comprometidas y bloquear operaciones que puedan empeorar los datos.", "Equipo técnico."],
        ["Operación temporal", "Usar formato controlado para citas y consumos con hora, paciente, lote y responsable. No registrar diagnósticos sensibles en chats personales.", "Coordinador clínico y almacén."],
        ["Recuperación", "Elegir entre reinicio, restauración o rollback según la evidencia. Validar en entorno aislado antes de abrir al público.", "Responsable técnico con autorización del líder."],
        ["Comunicación", "Actualizar por el canal interno acordado cada treinta minutos y comunicar a usuarios solo información confirmada.", "Responsable de comunicación."],
        ["Cierre", "Reconciliar registros temporales, confirmar estabilidad, guardar evidencias y programar revisión de causa raíz.", "Líder y documentador."],
    ], [1.15, 4.75, 1.3], 8.3)
    doc.add_paragraph(
        "El canal principal será el grupo interno de incidentes y una llamada directa al líder cuando el servicio esté totalmente "
        "caído. El correo institucional se usará para el resumen formal. Si el sistema de mensajería no está disponible, se aplicará "
        "la lista telefónica de responsables guardada fuera de Velmorax."
    )

    add_heading(doc, "Plan de reversa", 1)
    add_heading(doc, "Punto de control y activación", 2)
    doc.add_paragraph(
        "Antes de desplegar se registrarán el commit o etiqueta estable, la imagen anterior, la configuración vigente, el resultado "
        "de las pruebas y un backup verificado. Se activa la reversa si health ready no se recupera en diez minutos, aparecen errores "
        "repetidos de nivel crítico, fallan login o procesos clínicos, o una migración altera datos de forma inesperada."
    )
    add_heading(doc, "Pasos para volver a la versión estable", 2)
    rollback_steps = [
        "Detener el despliegue y bloquear nuevos cambios.",
        "Conservar logs, versión fallida y hora del primer error.",
        "Cambiar la aplicación a la imagen o commit estable anterior sin borrar volúmenes.",
        "Si hubo cambio de esquema incompatible, detener la aplicación y restaurar el backup previo al despliegue en una base aislada.",
        "Levantar PostgreSQL, aplicación y proxy; comprobar health live y health ready.",
        "Ejecutar las pruebas mínimas de login, agenda, paciente, historia clínica e inventario.",
        "Habilitar el servicio, observarlo durante treinta minutos e informar la recuperación.",
        "Registrar la causa, el cambio revertido y la condición necesaria antes de intentar un nuevo despliegue.",
    ]
    for number, step in enumerate(rollback_steps, 1):
        add_manual_number(doc, number, step)
    doc.add_paragraph(
        "El responsable técnico ejecuta la reversa. El líder del incidente autoriza restaurar datos o reabrir el servicio. Ningún "
        "rollback debe borrar volúmenes ni la evidencia de la versión fallida."
    )

    add_heading(doc, "Roles ante un incidente", 1)
    add_table(doc, ["Rol", "Responsabilidad"], [
        ["Líder del incidente", "Clasifica la severidad, define prioridades, autoriza restauración o rollback y decide el cierre."],
        ["Equipo técnico", "Diagnostica, contiene, restaura servicios, valida datos y conserva evidencia técnica."],
        ["Responsable de comunicación", "Informa a clínica, usuarios y responsables con mensajes confirmados y tiempos actualizados."],
        ["Documentador", "Registra cronología, decisiones, comandos, responsables, pruebas y acciones posteriores."],
    ], [1.7, 5.5], 9)
    doc.add_paragraph(
        "Para este ejercicio, Maicol Andrés Ospina puede asumir el liderazgo y la comunicación, Juan David Bastidas coordina "
        "la recuperación técnica y Emanuel Castaño conserva la cronología, las decisiones y las evidencias. Los tres validarán "
        "el cierre. En una instalación real, la clínica deberá aprobar los nombres y suplentes."
    )

    add_heading(doc, "Mensaje modelo de incidente", 1)
    doc.add_paragraph(
        "Asunto  Incidente activo en Velmorax\n\n"
        "A las hora y fecha detectamos una falla en componente o proceso. En este momento afecta a usuarios sedes o módulos y "
        "puede impedir describir impacto confirmado. El equipo técnico aisló el componente y está acción en curso. Estimamos "
        "recuperar el servicio a las hora estimada o emitir una nueva actualización en treinta minutos. Mientras tanto, usen el "
        "procedimiento temporal indicado por el coordinador y no repitan operaciones fallidas. Responsable de contacto nombre rol "
        "canal y teléfono."
    )
    doc.add_paragraph(
        "El mensaje se completará solo con datos confirmados. No incluirá contraseñas, historiales clínicos, nombres de pacientes "
        "ni detalles que faciliten un ataque."
    )

    add_heading(doc, "Evidencia técnica disponible", 1)
    doc.add_paragraph(
        "El plan se apoya en componentes que ya existen en el proyecto. Estas rutas permiten comprobar el estado actual y sirven "
        "como evidencia durante la entrega:"
    )
    add_table(doc, ["Evidencia", "Ubicación en el proyecto"], [
        ["Matriz real de roles y permisos", "app/services/auth.py  función role permissions"],
        ["Administración de usuarios y permisos", "app/routers/web.py  rutas admin users y permissions"],
        ["Ciclo cifrado y verificación automática", "deploy/backup-cycle.sh"],
        ["Restauración manual aislada", "deploy/restore-backup.sh"],
        ["Programación y salud del backup", "docker-compose.production.yml  servicio backup"],
        ["Comprobaciones del servicio", "app/routers/web.py  rutas health live ready y health"],
        ["Guía de producción", "deploy/README.md"],
        ["Pruebas del ciclo de backup", "tests/test_backup_configuration.py y tests/test_web.py"],
    ], [2.8, 4.4], 8.7)

    add_heading(doc, "Conclusión", 1)
    doc.add_paragraph(
        "Un archivo guardado no demuestra que los datos puedan recuperarse. Puede estar incompleto, corrupto, cifrado con una "
        "clave perdida o depender de una versión que ya no existe. Por esa razón, un backup que nunca se prueba equivale en la "
        "práctica a no tener backup. La prueba mensual y la restauración temporal automática permiten comprobar la integridad antes "
        "de una emergencia."
    )
    doc.add_paragraph(
        "La recuperación también es parte de la seguridad informática. La confidencialidad protege quién puede ver los datos, la "
        "integridad evita cambios indebidos y la disponibilidad permite continuar la atención. Velmorax necesita las tres. Los "
        "roles limitan el acceso, los logs dejan evidencia y el plan de backup, restauración y reversa reduce el tiempo durante el "
        "cual la clínica trabaja sin información confiable."
    )

    add_heading(doc, "Comentario para la entrega", 1)
    doc.add_paragraph(
        "El primer paso que activaría ante una falla crítica de Velmorax sería declarar el incidente, detener cambios y operaciones "
        "que puedan agravar la pérdida, y verificar el alcance con los endpoints de salud y los logs antes de elegir entre restauración "
        "o rollback."
    )

    # Prevent lonely headings and ensure header row repeats.
    for paragraph in doc.paragraphs:
        if paragraph.style.name.startswith("Heading"):
            keep_paragraph(paragraph, next_para=True)
        keep_paragraph(paragraph)
    return doc


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    document = build_document()
    document.save(OUTPUT)
    print(OUTPUT)
