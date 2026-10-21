"""Generación ligera de PDFs clínicos sin depender de servicios externos."""

from __future__ import annotations

from datetime import datetime
from textwrap import wrap


PAGE_WIDTH = 595
PAGE_HEIGHT = 842
LEFT = 46
RIGHT = 549
TOP = 794
BOTTOM = 48


def _text(value: object) -> str:
    """Convierte valores opcionales a texto seguro para un PDF básico."""
    return str(value or "").replace("\r", " ").replace("\n", " ").strip()


def _pdf_escape(value: str) -> str:
    # Helvetica admite Windows-1252; los caracteres no representables se sustituyen
    # para evitar que una observación clínica invalide la descarga completa.
    encoded = value.encode("cp1252", "replace").decode("latin-1")
    return encoded.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _label_value(label: str, value: object) -> tuple[str, str] | None:
    text = _text(value)
    return (label, text) if text else None


def build_patient_history_pdf(patient: dict, records: list[dict]) -> bytes:
    """Crea un informe clínico listo para compartir con una presentación institucional."""
    navy = (0.10, 0.15, 0.20)
    slate = (0.16, 0.23, 0.29)
    ink = (0.12, 0.16, 0.21)
    muted = (0.36, 0.43, 0.51)
    line_color = (0.76, 0.81, 0.86)
    teal = (0.08, 0.45, 0.42)
    pale_teal = (0.91, 0.96, 0.95)
    pale_gold = (0.99, 0.96, 0.88)
    pages: list[list[str]] = [[]]
    cursor_y = 700

    def color(values: tuple[float, float, float]) -> str:
        return " ".join(f"{value:.3f}" for value in values)

    def add_text(x: float, y: float, value: object, size: int = 10, bold: bool = False,
                 fill: tuple[float, float, float] = ink) -> None:
        text = _text(value)
        if text:
            font = "F2" if bold else "F1"
            pages[-1].append(
                f"q {color(fill)} rg BT /{font} {size} Tf {x:.1f} {y:.1f} Td ({_pdf_escape(text)}) Tj ET Q"
            )

    def rectangle(x: float, y_top: float, width: float, height: float,
                  fill: tuple[float, float, float] | None = None,
                  stroke: tuple[float, float, float] | None = None) -> None:
        command = "q "
        if fill:
            command += f"{color(fill)} rg "
        if stroke:
            command += f"{color(stroke)} RG 0.7 w "
        command += f"{x:.1f} {y_top - height:.1f} {width:.1f} {height:.1f} re "
        command += "B Q" if fill and stroke else "f Q" if fill else "S Q"
        pages[-1].append(command)

    def rule(y: float) -> None:
        pages[-1].append(f"q {color(line_color)} RG 0.7 w {LEFT} {y:.1f} m {RIGHT} {y:.1f} l S Q")

    def header(continued: bool = False) -> None:
        nonlocal cursor_y
        rectangle(0, PAGE_HEIGHT, PAGE_WIDTH, 120, fill=navy)
        add_text(LEFT, 792, "VELMORAX", 13, True, (0.85, 0.91, 0.90))
        add_text(LEFT, 763, "Historial clínico" if not continued else "Historial clínico · continuación", 23, True, (1, 1, 1))
        add_text(LEFT, 739, "Clínica veterinaria · Documento confidencial", 9, False, (0.77, 0.84, 0.85))
        cursor_y = 692

    def new_page() -> None:
        pages.append([])
        header(continued=True)

    def ensure(space: float) -> None:
        if cursor_y - space < BOTTOM:
            new_page()

    def wrapped(value: object, *, x: float = LEFT, width: float = RIGHT - LEFT,
                size: int = 10, bold: bool = False, fill: tuple[float, float, float] = ink,
                leading: float | None = None) -> float:
        nonlocal cursor_y
        text = _text(value)
        if not text:
            return 0
        line_height = leading or size + 4
        chars = max(22, int(width / (size * 0.51)))
        lines = wrap(text, width=chars, break_long_words=False, break_on_hyphens=False) or [text]
        ensure(len(lines) * line_height + 2)
        for part in lines:
            add_text(x, cursor_y, part, size, bold, fill)
            cursor_y -= line_height
        return len(lines) * line_height

    def section_title(title: str, subtitle: str = "") -> None:
        nonlocal cursor_y
        ensure(38)
        add_text(LEFT, cursor_y, title, 14, True, slate)
        if subtitle:
            add_text(RIGHT - 120, cursor_y + 1, subtitle, 8, False, muted)
        cursor_y -= 12
        rule(cursor_y)
        cursor_y -= 18

    def field(x: float, label: str, value: object) -> None:
        nonlocal cursor_y
        add_text(x, cursor_y, label.upper(), 7, True, muted)
        cursor_y -= 12
        wrapped(value or "Sin registrar", x=x, width=218, size=10, fill=ink, leading=13)

    def soap_block(label: str, value: object, accent: tuple[float, float, float] = teal) -> None:
        nonlocal cursor_y
        text = _text(value)
        if not text:
            return
        ensure(42)
        rectangle(LEFT, cursor_y + 5, 4, 28, fill=accent)
        add_text(LEFT + 13, cursor_y, label.upper(), 8, True, muted)
        cursor_y -= 14
        wrapped(text, x=LEFT + 13, width=RIGHT - LEFT - 13, size=10, fill=ink, leading=14)
        cursor_y -= 6

    header()
    add_text(LEFT, cursor_y, _text(patient.get("display_name")) or "Paciente", 20, True, ink)
    add_text(LEFT, cursor_y - 18, "Resumen de historia clínica", 9, False, muted)
    cursor_y -= 42

    section_title("Perfil del paciente", "DATOS DE REFERENCIA")
    species = " · ".join(part for part in (_text(patient.get("species")), _text(patient.get("breed"))) if part)
    left_fields = [("Especie y raza", species), ("Sexo", patient.get("sex")), ("Peso registrado", f"{patient.get('weight_kg')} kg" if patient.get("weight_kg") not in (None, "") else "")]
    right_fields = [("Tutor", patient.get("owner_name")), ("Teléfono", patient.get("phone")), ("Vacunación", patient.get("vaccine_status"))]
    start_y = cursor_y
    for label, value in left_fields:
        field(LEFT, label, value)
        cursor_y -= 5
    left_end = cursor_y
    cursor_y = start_y
    for label, value in right_fields:
        field(310, label, value)
        cursor_y -= 5
    cursor_y = min(left_end, cursor_y) - 8

    alerts = [
        _label_value("Alergias", patient.get("allergies")),
        _label_value("Condiciones previas", patient.get("preexisting_conditions")),
        _label_value("Alerta clínica", patient.get("clinical_alert")),
    ]
    alerts = [item for item in alerts if item]
    if alerts:
        ensure(38)
        alert_text = " · ".join(f"{label}: {value}" for label, value in alerts)
        rectangle(LEFT, cursor_y + 4, RIGHT - LEFT, 30, fill=pale_gold, stroke=(0.85, 0.72, 0.39))
        add_text(LEFT + 12, cursor_y - 7, alert_text, 8, False, ink)
        cursor_y -= 40

    section_title("Atenciones clínicas", f"{len(records)} REGISTRADA{'S' if len(records) != 1 else ''}")
    if not records:
        wrapped("No hay atenciones registradas para esta mascota.", size=10, fill=muted)

    for index, record in enumerate(records, start=1):
        ensure(116)
        rectangle(LEFT, cursor_y + 6, RIGHT - LEFT, 34, fill=pale_teal, stroke=(0.61, 0.77, 0.73))
        add_text(LEFT + 12, cursor_y - 4, f"{index:02d}", 9, True, teal)
        add_text(LEFT + 38, cursor_y - 4, _text(record.get("reason")) or "Atención clínica", 12, True, slate)
        add_text(RIGHT - 104, cursor_y - 4, record.get("encounter_date") or "", 9, True, muted)
        cursor_y -= 48
        details = " · ".join(part for part in (
            _text(record.get("service_performed")),
            _text(record.get("professional")),
            _text(record.get("status")),
        ) if part)
        if details:
            add_text(LEFT, cursor_y, details, 8, False, muted)
            cursor_y -= 18
        soap_block("Motivo y observaciones", record.get("note"))
        soap_block("Evaluación", record.get("vital_signs"))
        soap_block("Valoración clínica", record.get("diagnosis"))
        plan_parts = [part for part in (_text(record.get("treatment_plan")), _text(record.get("prescription"))) if part]
        soap_block("Plan de manejo", " · ".join(dict.fromkeys(plan_parts)))
        follow_up = " · ".join(
            f"{label}: {value}" for label, value in (
                ("Control", _text(record.get("follow_up_date"))),
                ("Próxima vacuna", _text(record.get("next_vaccine_due"))),
                ("Indicaciones", _text(record.get("discharge_notes"))),
            ) if value
        )
        if follow_up:
            ensure(32)
            rectangle(LEFT, cursor_y + 4, RIGHT - LEFT, 28, fill=(0.95, 0.97, 0.98), stroke=line_color)
            add_text(LEFT + 11, cursor_y - 6, follow_up, 8, False, slate)
            cursor_y -= 38
        cursor_y -= 10

    objects: list[bytes] = []
    page_refs: list[int] = []
    content_refs: list[int] = []
    font_regular = 3
    font_bold = 4

    # El catálogo y el árbol de páginas se completan tras conocer los objetos.
    objects.extend([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [] /Count 0 >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ])
    for page in pages:
        commands = list(page)
        page_number = len(content_refs) + 1
        commands.append(f"q {color(muted)} rg BT /F1 8 Tf {LEFT} 28 Td (Velmorax · Historial clínico confidencial) Tj ET Q")
        commands.append(f"q {color(muted)} rg BT /F1 8 Tf {RIGHT - 45} 28 Td (Página {page_number} de {len(pages)}) Tj ET Q")
        content = "\n".join(commands).encode("latin-1")
        content_refs.append(len(objects) + 1)
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
        page_refs.append(len(objects) + 1)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >> >> "
            f"/Contents {content_refs[-1]} 0 R >>".encode()
        )

    kids = " ".join(f"{ref} 0 R" for ref in page_refs)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_refs)} >>".encode()
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return bytes(output)
