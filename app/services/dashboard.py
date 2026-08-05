from __future__ import annotations

from datetime import date

from app.services.appointments import appointment_summary, list_appointments
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
    list_inventory_categories,
    list_inventory_items,
    list_recent_movements,
)
from app.services.network import list_recent_activity, resolve_scope


def get_dashboard_context(
    search: str = "",
    category: str = "",
    status: str = "",
    day: str = "",
    organization_id: str = "",
    location_id: str = "",
) -> dict:
    selected_day = day or date.today().isoformat()
    scope = resolve_scope(organization_id=organization_id, location_id=location_id)

    inventory_items = list_inventory_items(
        search=search,
        category=category,
        status=status,
        organization_id=scope["organization_id"],
        location_id=scope["location_id"],
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
        },
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
