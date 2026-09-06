from __future__ import annotations

from datetime import date, datetime, timedelta

from app.services.appointments import appointment_summary, available_slots, list_appointments
from app.services.auth import list_users
from app.services.alerts import list_notification_alerts
from app.services.clinical import (
    clinical_summary,
    daily_financial_summary,
    dental_snapshot,
    list_clinical_records,
    list_patients,
    patient_options,
    veterinary_snapshot,
)
from app.services.inventory import (
    get_inventory_item_options,
    inventory_summary,
    inventory_network_summary,
    list_inventory_categories,
    list_inventory_items,
    list_inventory_products,
    list_inventory_replenishments,
    list_recent_movements,
)
from app.services.network import list_recent_activity, resolve_scope
from app.core.database import get_connection


def create_shift_handoff(payload: dict) -> None:
    with get_connection() as connection:
        connection.execute(
            """INSERT INTO shift_handoffs
               (organization_id, location_id, created_by, summary, pending_actions, shift_label)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (payload["organization_id"], payload["location_id"], payload["created_by"],
             payload["summary"].strip(), payload.get("pending_actions", "").strip(),
             payload.get("shift_label", "").strip()),
        )
        connection.commit()


def latest_shift_handoff(organization_id: str, location_id: str) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            """SELECT shift_handoffs.*, users.full_name AS created_by_name
               FROM shift_handoffs JOIN users ON users.id = shift_handoffs.created_by
               WHERE shift_handoffs.organization_id = ? AND shift_handoffs.location_id = ?
               ORDER BY shift_handoffs.id DESC LIMIT 1""",
            (int(organization_id), int(location_id)),
        ).fetchone()
    return dict(row) if row else None


def get_dashboard_context(
    search: str = "",
    category: str = "",
    status: str = "",
    day: str = "",
    organization_id: str = "",
    location_id: str = "",
    item_type: str = "",
    storage_area: str = "",
    supplier: str = "",
    expiry: str = "",
) -> dict:
    selected_day = day or date.today().isoformat()
    selected_date = date.fromisoformat(selected_day)
    scope = resolve_scope(organization_id=organization_id, location_id=location_id)

    inventory_items = list_inventory_items(
        search=search,
        category=category,
        status=status,
        organization_id=scope["organization_id"],
        location_id=scope["location_id"],
        item_type=item_type,
        storage_area=storage_area,
        supplier=supplier,
        expiry=expiry,
    )
    summary = inventory_summary(inventory_items)
    appointments = list_appointments(
        selected_day,
        organization_id=scope["organization_id"],
        location_id=scope["location_id"],
    )
    agenda_summary = appointment_summary(appointments)
    patients = list_patients(
        organization_id=scope["organization_id"],
        location_id=scope["location_id"],
    )
    records = list_clinical_records(
        organization_id=scope["organization_id"],
        location_id=scope["location_id"],
    )
    clinical = clinical_summary(records, patients)
    daily_finance = daily_financial_summary(records, selected_day)
    vet_data = veterinary_snapshot(patients, records)
    dental_data = dental_snapshot(records)
    veterinary_appointments = [
        item for item in appointments if item["specialty"] == "Veterinaria"
    ]
    veterinary_inventory_alerts = [
        item
        for item in inventory_items
        if item["category"].strip().lower() == "veterinaria"
    ]
    veterinary_agenda_summary = appointment_summary(veterinary_appointments)
    veterinary_inventory_summary = inventory_summary(veterinary_inventory_alerts)
    active_alerts = list_notification_alerts(
        organization_id=scope["organization_id"],
        location_id=scope["location_id"],
    )
    agenda_professionals = [
        user for user in list_users()
        if user["is_active"]
        and str(user["organization_id"]) == str(scope["organization_id"])
        and (user["role"] in {"clinical", "admin", "owner"})
        and (
            user["role"] in {"admin", "owner"}
            or str(user["location_id"]) == str(scope["location_id"])
        )
    ]
    agenda_available_slots = {
        str(user["id"]): {
            str(duration): available_slots(selected_day, user, appointments, duration)
            for duration in (20, 30, 45, 60)
        }
        for user in agenda_professionals
    }
    operational_appointments = [
        item for item in veterinary_appointments
        if item["status"] not in {"Atendida", "Cancelada"}
    ]
    next_appointment = next(iter(operational_appointments), None)
    active_appointment = next(
        (item for item in veterinary_appointments if item["status"] == "En consulta"), None
    )
    completed_appointments = sum(1 for item in veterinary_appointments if item["status"] == "Atendida")
    urgent_appointments = [
        item for item in operational_appointments
        if item.get("priority") == "Urgente"
        or any(token in f"{item['service']} {item['note']}".lower() for token in ("urgencia", "urgente", "emergencia", "crítico", "critico"))
    ]
    delayed_appointments: list[dict] = []
    if selected_day == date.today().isoformat():
        current_time = datetime.now().time()
        delayed_appointments = [
            item for item in operational_appointments
            if item["status"] in {"Pendiente", "Confirmada", "En espera", "Llamar"}
            and datetime.strptime(item["time"], "%H:%M").time() < current_time
        ]
    delayed_ids = {item["id"] for item in delayed_appointments}
    urgent_ids = {item["id"] for item in urgent_appointments}
    for item in operational_appointments:
        item["is_delayed"] = item["id"] in delayed_ids
        item["is_urgent"] = item["id"] in urgent_ids
    # The board is an operational queue, not a chronological copy of Agenda.
    # Active, delayed and urgent patients must remain visible before routine visits.
    operational_appointments.sort(
        key=lambda item: (
            0 if item["status"] == "En consulta" else 1,
            {"Rojo": 0, "Naranja": 1, "Amarillo": 2, "Verde": 3, "Azul": 4}.get(item.get("triage_level"), 5),
            0 if item["is_delayed"] else 1,
            0 if item["is_urgent"] else 1,
            item["time"],
            item["id"],
        )
    )
    professional_load = []
    for professional in agenda_professionals:
        assigned = [item for item in veterinary_appointments if item.get("veterinarian_user_id") == professional["id"]]
        professional_load.append({
            "name": professional["full_name"],
            "scheduled": len(assigned),
            "active": sum(1 for item in assigned if item["status"] == "En consulta"),
            "waiting": sum(1 for item in assigned if item["status"] == "En espera"),
        })
    professional_load.sort(key=lambda item: (-item["active"], -item["waiting"], -item["scheduled"], item["name"]))
    if active_appointment and selected_day == date.today().isoformat():
        started_at = datetime.strptime(active_appointment["time"], "%H:%M")
        now = datetime.now()
        active_appointment["elapsed_minutes"] = max(
            0, int((now.replace(year=1900, month=1, day=1) - started_at).total_seconds() // 60)
        )

    return {
        "hero": {
            "title": "Centro de control clinico para inventario, agenda y registro",
            "description": (
                "Velmorax concentra lo urgente primero: vencimientos, pacientes en "
                "espera, tareas del dia, flujos clinicos por especialidad y un "
                "inventario transversal desde una sola web."
            ),
            "cta_primary": "Ir a agenda",
            "cta_secondary": "Abrir modulo clinico",
        },
        "kpis": [
            {
                "label": "Citas de hoy",
                "value": str(agenda_summary["total"]),
                "hint": f"{agenda_summary['pending']} pendientes en {scope['scope_label']}",
                "tone": "neutral",
            },
            {
                "label": "Alertas criticas",
                "value": str(summary["critical"]),
                "hint": "Productos vencidos o con vencimiento menor a 90 dias",
                "tone": "danger",
            },
            {
                "label": "Stock bajo",
                "value": str(summary["low_stock"]),
                "hint": "Items en o por debajo del stock minimo",
                "tone": "warning",
            },
            {
                "label": "Pacientes visibles",
                "value": str(clinical["patients_total"]),
                "hint": "Filtro aplicado por organizacion y sede",
                "tone": "safe",
            },
        ],
        "quick_actions": [
            {
                "title": "Registrar ingreso",
                "detail": "Carga rapida por lote, vencimiento y proveedor",
                "href": "/inventario",
            },
            {
                "title": "Abrir triaje",
                "detail": "Registrar llegada, motivo y prioridad",
                "href": "/agenda",
            },
            {
                "title": "Nueva historia",
                "detail": "Atajo para consulta humana o veterinaria",
                "href": "/clinica",
            },
            {
                "title": "Ver alertas",
                "detail": "Semaforos, cadena de frio y pendientes",
                "href": "/inventario",
            },
        ],
        "workflow_principles": [
            "Priorizar lo urgente y reducir la carga de documentacion",
            "Alinear pantallas al flujo real del equipo clinico",
            "Mantener inventario y bodega como capacidad comun para todas las sedes",
            "Usar plantillas estructuradas sin quitar flexibilidad narrativa",
            "Disenar con trazabilidad, seguridad y contexto visible",
        ],
        "appointments": appointments,
        "agenda_summary": agenda_summary,
        "agenda_day": selected_day,
        "agenda_previous_day": (selected_date - timedelta(days=1)).isoformat(),
        "agenda_next_day": (selected_date + timedelta(days=1)).isoformat(),
        "agenda_today": date.today().isoformat(),
        "agenda_emergency_time": datetime.now().strftime("%H:%M"),
        "agenda_professionals": agenda_professionals,
        "agenda_available_slots": agenda_available_slots,
        "inventory_alerts": inventory_items,
        "inventory_summary": summary,
        "inventory_categories": list_inventory_categories(
            organization_id=scope["organization_id"],
            location_id=scope["location_id"],
        ),
        "inventory_filters": {
            "search": search,
            "category": category,
            "status": status,
            "organization_id": scope["organization_id"],
            "location_id": scope["location_id"],
            "item_type": item_type,
            "storage_area": storage_area,
            "supplier": supplier,
            "expiry": expiry,
        },
        "inventory_products": list_inventory_products(scope["organization_id"]),
        "inventory_replenishments": list_inventory_replenishments(
            organization_id=scope["organization_id"], location_id=scope["location_id"]
        ),
        "inventory_network_summary": inventory_network_summary(scope["organization_id"]),
        "inventory_item_types": ["Medicamento", "Vacuna", "Instrumental", "Material médico", "Alimento", "Otro"],
        "inventory_units": ["unidades", "cajas", "frascos", "dosis", "ml", "g", "kg"],
        "inventory_item_options": get_inventory_item_options(
            organization_id=scope["organization_id"],
            location_id=scope["location_id"],
        ),
        "recent_movements": list_recent_movements(
            organization_id=scope["organization_id"],
            location_id=scope["location_id"],
        ),
        "patients": patients,
        "patient_options": patient_options(
            organization_id=scope["organization_id"],
            location_id=scope["location_id"],
        ),
        "clinical_records": records,
        "clinical_summary": clinical,
        "daily_financial_summary": daily_finance,
        "veterinary_snapshot": vet_data,
        "veterinary_dashboard": {
            "appointments": operational_appointments[:4],
            "next_appointment": next_appointment,
            "active_appointment": active_appointment,
            "agenda_summary": veterinary_agenda_summary,
            "inventory_alerts": veterinary_inventory_alerts[:4],
            "inventory_summary": veterinary_inventory_summary,
            "alerts": active_alerts[:4],
            "alerts_total": len(active_alerts),
            "critical_alerts_total": sum(1 for item in active_alerts if item["priority"] == "urgent"),
            "operations": {
                "completed": completed_appointments,
                "delayed": len(delayed_appointments),
                "urgent": len(urgent_appointments),
                "triage_red": sum(1 for item in urgent_appointments if item.get("triage_level") == "Rojo"),
                "professionals": len(agenda_professionals),
                "status": "Atención inmediata" if urgent_appointments else ("Revisar retrasos" if delayed_appointments else "Operación estable"),
                "tone": "critical" if urgent_appointments else ("attention" if delayed_appointments else "stable"),
            },
            "professional_load": professional_load[:4],
            "latest_handoff": latest_shift_handoff(scope["organization_id"], scope["location_id"]),
        },
        "dental_snapshot": dental_data,
        "scope": scope,
        "recent_activity": list_recent_activity(
            organization_id=scope["organization_id"],
            location_id=scope["location_id"],
        ),
        "patient_queue": [
            {
                "name": "Daniela Ortiz",
                "channel": "Presencial",
                "reason": "Dolor agudo molar",
                "priority": "Alta",
                "site_name": "Sede Norte Dental",
            },
            {
                "name": "Toby / Sara Gil",
                "channel": "Control",
                "reason": "Refuerzo vacuna anual",
                "priority": "Media",
                "site_name": "Sede Mascotas Centro",
            },
            {
                "name": "Jorge Salas",
                "channel": "Virtual",
                "reason": "Revision resultados",
                "priority": "Baja",
                "site_name": "Sede Integral Medellin",
            },
        ],
        "specialty_tabs": [
            {
                "id": "dental",
                "name": "Odontologia",
                "summary": "Odontograma, plan por pieza y consumo de insumos por procedimiento.",
                "flows": [
                    "Ingreso del paciente y motivo de consulta",
                    "Odontograma interactivo y hallazgos",
                    "Plan de tratamiento con presupuesto",
                    "Descuento automatico de resinas, anestesia e implantes",
                ],
                "focus": [
                    "Historial dental",
                    "Imagenes intraorales",
                    "Pendientes por aceptar",
                ],
            },
            {
                "id": "vet",
                "name": "Veterinaria",
                "summary": "Ficha del animal, propietario, vacunacion, SOAP y cadena de frio.",
                "flows": [
                    "Busqueda por mascota o propietario",
                    "Peso, especie, raza y antecedentes",
                    "Plan vacunal y recordatorios",
                    "Trazabilidad por lote y registro regulatorio",
                ],
                "focus": [
                    "Esquema de vacunas",
                    "Ultimo peso",
                    "Alertas de seguimiento",
                ],
            },
            {
                "id": "general",
                "name": "Consulta general",
                "summary": "Historia clinica flexible para medicina general y otras especialidades.",
                "flows": [
                    "Recepcion, triage y signos vitales",
                    "Nota clinica estructurada con narrativa",
                    "Ordenes, formulas y adjuntos",
                    "Cierre con recomendaciones y control",
                ],
                "focus": [
                    "Signos vitales",
                    "Diagnosticos",
                    "Controles pendientes",
                ],
            },
        ],
        "inventory_form_defaults": {
            "regulatory_agency": "INVIMA",
            "category": "Odontologia",
            "location": "Bodega principal",
        },
        "appointment_form_defaults": {
            "channel": "Presencial",
            "status": "Confirmada",
            "specialty": "Odontologia",
        },
        "patient_form_defaults": {
            "patient_type": "Humano",
            "specialty": "Odontologia",
            "vaccine_status": "No aplica",
        },
        "clinical_form_defaults": {
            "encounter_date": selected_day,
            "status": "Cerrada",
            "specialty": "Odontologia",
            "follow_up_date": "",
        },
        "network_principles": [
            "Separar organizacion y sede para operar varias ubicaciones sin mezclar datos",
            "Registrar actividad por usuario para trazabilidad y auditoria minima",
            "Mantener filtros globales por sede para reducir errores humanos",
            "Preparar el salto a PostgreSQL cuando la concurrencia crezca",
        ],
        "usability_gains": [
            "Menos clics para registrar ingreso y salida de inventario",
            "Vista unica de agenda, fila y alertas",
            "Paneles adaptados a odontologia, veterinaria y consulta general",
            "Inventario compartido como soporte transversal, no como especialidad aislada",
            "Alertas visibles sin abrir multiples pantallas",
            "Filtro compartido por organizacion y sede para equipos distribuidos",
        ],
        "sources": [
            {
                "label": "ASTP/ONC: Usabilidad y carga del proveedor",
                "url": "https://healthit.gov/usability-and-provider-burden/",
            },
            {
                "label": "Health IT Playbook: calidad y seguridad",
                "url": "https://playbook.healthit.gov/playbook/quality-and-patient-safety/",
            },
            {
                "label": "GS1: supply chain eficiente en salud",
                "url": "https://www.gs1.org/industries/healthcare/saving-money/more-efficient-supply-chain",
            },
            {
                "label": "HL7 FHIR: Organization, Location y PractitionerRole",
                "url": "https://www.hl7.org/fhir/practitionerrole.html",
            },
            {
                "label": "OWASP ASVS: verificacion de seguridad web",
                "url": "https://owasp.org/www-project-application-security-verification-standard/",
            },
            {
                "label": "FastAPI: despliegue con workers",
                "url": "https://fastapi.tiangolo.com/deployment/server-workers/",
            },
            {
                "label": "PostgreSQL: concurrencia y locking",
                "url": "https://www.postgresql.org/docs/current/explicit-locking.html",
            },
        ],
    }
