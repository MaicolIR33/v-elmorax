from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from app.services.appointments import (
    appointment_summary,
    available_slots,
    list_appointments,
    list_appointments_between,
)
from app.services.auth import list_users
from app.services.alerts import list_alerts, list_notification_alerts
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


DASHBOARD_CARDS = ("operations", "signals", "agenda", "tasks", "analytics", "resources", "continuity")


def get_dashboard_preferences(user_id: int, role: str) -> dict:
    with get_connection() as connection:
        user_row = connection.execute(
            "SELECT selected_view, visible_cards FROM dashboard_preferences WHERE user_id = ?", (user_id,)
        ).fetchone()
        role_row = connection.execute(
            "SELECT visible_cards FROM dashboard_role_preferences WHERE role = ?", (role,)
        ).fetchone()
    def cards(value: str | None) -> set[str]:
        try:
            items = json.loads(value or "[]")
        except (TypeError, ValueError):
            items = []
        return {item for item in items if item in DASHBOARD_CARDS}
    role_cards = cards(role_row["visible_cards"] if role_row else "")
    user_cards = cards(user_row["visible_cards"] if user_row else "")
    visible = user_cards or role_cards or set(DASHBOARD_CARDS)
    selected_view = (user_row["selected_view"] if user_row else "operation") or "operation"
    view_available = {
        "operation": bool({"agenda", "tasks"} & visible),
        "analysis": "analytics" in visible,
        "resources": "resources" in visible,
        "continuity": "continuity" in visible,
    }
    if not view_available.get(selected_view, False):
        selected_view = next(
            (view for view, available in view_available.items() if available),
            "operation",
        )
    return {
        "selected_view": selected_view,
        "visible_cards": visible,
        "has_role_config": bool(role_cards),
    }


def save_dashboard_preferences(user_id: int, selected_view: str, visible_cards: list[str]) -> None:
    view = selected_view if selected_view in {"operation", "analysis", "resources", "continuity"} else "operation"
    cards = [item for item in visible_cards if item in DASHBOARD_CARDS]
    with get_connection() as connection:
        connection.execute(
            """INSERT INTO dashboard_preferences (user_id, selected_view, visible_cards, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id) DO UPDATE SET selected_view=excluded.selected_view,
               visible_cards=excluded.visible_cards, updated_at=CURRENT_TIMESTAMP""",
            (user_id, view, json.dumps(cards)),
        )
        connection.commit()


def save_dashboard_role_preferences(role: str, visible_cards: list[str]) -> None:
    cards = [item for item in visible_cards if item in DASHBOARD_CARDS]
    with get_connection() as connection:
        connection.execute(
            """INSERT INTO dashboard_role_preferences (role, visible_cards, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(role) DO UPDATE SET visible_cards=excluded.visible_cards,
               updated_at=CURRENT_TIMESTAMP""",
            (role, json.dumps(cards)),
        )
        connection.commit()


def record_dashboard_snapshot(organization_id: str, location_id: str, values: dict) -> None:
    """Persist one daily operational point per site for reliable trend charts."""
    with get_connection() as connection:
        connection.execute(
            """INSERT INTO dashboard_snapshots (
                organization_id, location_id, snapshot_date, appointments_total, attended_total,
                cancelled_total, alerts_total, consumption_total, followups_total
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(organization_id, location_id, snapshot_date) DO UPDATE SET
                appointments_total=excluded.appointments_total, attended_total=excluded.attended_total,
                cancelled_total=excluded.cancelled_total, alerts_total=excluded.alerts_total,
                consumption_total=excluded.consumption_total, followups_total=excluded.followups_total""",
            (int(organization_id), int(location_id), date.today().isoformat(), values["appointments"], values["attended"], values["cancelled"], values["alerts"], values["consumption"], values["followups"]),
        )
        connection.commit()


def dashboard_history_series(organization_id: str, location_id: str, days: int = 7) -> list[dict]:
    start = (date.today() - timedelta(days=max(1, days) - 1)).isoformat()
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT snapshot_date, appointments_total, attended_total, alerts_total, consumption_total
               FROM dashboard_snapshots WHERE organization_id=? AND location_id=? AND snapshot_date >= ?
               ORDER BY snapshot_date""", (int(organization_id), int(location_id), start)
        ).fetchall()
    by_day = {row["snapshot_date"]: dict(row) for row in rows}
    days_list = [date.today() - timedelta(days=offset) for offset in range(max(1, days) - 1, -1, -1)]
    maximum = max(1, max([int(row["appointments_total"]) for row in rows] or [0]))
    return [{
        "date": day.isoformat(), "label": day.strftime("%d/%m"),
        "appointments": int(by_day.get(day.isoformat(), {}).get("appointments_total", 0)),
        "attended": int(by_day.get(day.isoformat(), {}).get("attended_total", 0)),
        "alerts": int(by_day.get(day.isoformat(), {}).get("alerts_total", 0)),
        "consumption": float(by_day.get(day.isoformat(), {}).get("consumption_total", 0)),
        "height": max(10, round(int(by_day.get(day.isoformat(), {}).get("appointments_total", 0)) / maximum * 100)) if by_day.get(day.isoformat()) else 10,
    } for day in days_list]


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


def dashboard_date_window(
    period: str = "", day: str = "", date_from: str = "", date_to: str = ""
) -> dict:
    """Normalize the dashboard period and supply a comparable prior window."""
    today = date.today()

    def parse(value: str, fallback: date) -> date:
        try:
            return date.fromisoformat(value)
        except (TypeError, ValueError):
            return fallback

    period = period if period in {"today", "tomorrow", "week", "range"} else "today"
    if period == "tomorrow":
        start = end = today + timedelta(days=1)
        label = "Mañana"
    elif period == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        label = "Esta semana"
    elif period == "range":
        start = parse(date_from, parse(day, today))
        end = parse(date_to, start)
        if end < start:
            start, end = end, start
        # A two-month upper limit keeps the dashboard useful and fast.
        if (end - start).days > 62:
            end = start + timedelta(days=62)
        label = f"Del {start.strftime('%d %b')} al {end.strftime('%d %b')}"
    else:
        start = end = parse(day, today)
        label = "Hoy" if start == today else start.strftime("%d de %B")
    days = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    return {
        "id": period,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "previous_start": previous_start.isoformat(),
        "previous_end": previous_end.isoformat(),
        "label": label,
        "days": days,
    }


def _trend_metric(label: str, current: int | float, previous: int | float, *, inverse: bool = False) -> dict:
    difference = current - previous
    if difference == 0:
        direction, tone, copy = "equal", "neutral", "Sin variación"
    elif (difference > 0) != inverse:
        direction, tone, copy = "up", "positive", "Mejor que el periodo anterior"
    else:
        direction, tone, copy = "down", "attention", "Revisar frente al periodo anterior"
    sign = "+" if difference > 0 else ""
    return {
        "label": label,
        "value": current,
        "previous": previous,
        "difference": difference,
        "delta_label": f"{sign}{difference:g}",
        "direction": direction,
        "tone": tone,
        "copy": copy,
    }


def _movement_consumption(start: str, end: str, organization_id: str, location_id: str) -> float:
    query = """SELECT COALESCE(SUM(quantity), 0) AS total FROM inventory_movements
               WHERE movement_type = 'out' AND substr(created_at, 1, 10) BETWEEN ? AND ?
                 AND organization_id = ? AND location_id = ?"""
    with get_connection() as connection:
        row = connection.execute(query, (start, end, int(organization_id), int(location_id))).fetchone()
    return float(row["total"] or 0)


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
    period: str = "",
    date_from: str = "",
    date_to: str = "",
    user_role: str = "",
    user_id: int = 0,
    veterinarian_filter: str = "",
    priority_filter: str = "",
    appointment_status_filter: str = "",
    history_span: str = "week",
) -> dict:
    dashboard_period = dashboard_date_window(period, day, date_from, date_to)
    selected_day = dashboard_period["start"]
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
    appointments = list_appointments_between(
        dashboard_period["start"], dashboard_period["end"],
        organization_id=scope["organization_id"],
        location_id=scope["location_id"],
    )
    agenda_summary = appointment_summary(appointments)
    patients = list_patients(
        organization_id=scope["organization_id"],
        location_id=scope["location_id"],
    )
    records = list_clinical_records(
        limit=500,
        organization_id=scope["organization_id"],
        location_id=scope["location_id"],
    )
    previous_appointments = list_appointments_between(
        dashboard_period["previous_start"], dashboard_period["previous_end"],
        organization_id=scope["organization_id"], location_id=scope["location_id"],
    )
    previous_records = [
        item for item in records
        if dashboard_period["previous_start"] <= item["encounter_date"] <= dashboard_period["previous_end"]
    ]
    period_records = [
        item for item in records
        if dashboard_period["start"] <= item["encounter_date"] <= dashboard_period["end"]
    ]
    clinical = clinical_summary(records, patients)
    daily_finance = daily_financial_summary(records, selected_day)
    vet_data = veterinary_snapshot(patients, records)
    dental_data = dental_snapshot(records)
    veterinary_appointments = [
        item for item in appointments if item["specialty"] == "Veterinaria"
    ]
    dashboard_preferences = get_dashboard_preferences(user_id, user_role) if user_id else {
        "selected_view": "operation", "visible_cards": set(DASHBOARD_CARDS), "has_role_config": False,
    }
    previous_veterinary_appointments = [
        item for item in previous_appointments if item["specialty"] == "Veterinaria"
    ]
    veterinary_records = [item for item in period_records if item["specialty"] == "Veterinaria"]
    previous_veterinary_records = [item for item in previous_records if item["specialty"] == "Veterinaria"]
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
    all_alerts = list_alerts(
        organization_id=scope["organization_id"], location_id=scope["location_id"]
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
    if veterinarian_filter and veterinarian_filter.isdigit():
        operational_appointments = [item for item in operational_appointments if item.get("veterinarian_user_id") == int(veterinarian_filter)]
    if priority_filter:
        operational_appointments = [item for item in operational_appointments if item.get("priority", "").lower() == priority_filter.lower()]
    if appointment_status_filter:
        operational_appointments = [item for item in operational_appointments if item.get("status") == appointment_status_filter]
    next_appointment = next(iter(operational_appointments), None)
    active_appointment = next(
        (item for item in veterinary_appointments if item["status"] == "En consulta"), None
    )
    completed_appointments = sum(1 for item in veterinary_appointments if item["status"] == "Atendida")
    cancelled_appointments = sum(1 for item in veterinary_appointments if item["status"] == "Cancelada")
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

    def attended(items: list[dict]) -> int:
        return sum(1 for item in items if item["status"] == "Atendida")

    def cancelled(items: list[dict]) -> int:
        return sum(1 for item in items if item["status"] == "Cancelada")

    wait_minutes: list[float] = []
    for item in veterinary_appointments:
        if not item.get("arrival_at"):
            continue
        try:
            scheduled = datetime.fromisoformat(f"{item['date']}T{item['time']}")
            arrived = datetime.fromisoformat(item["arrival_at"])
            wait_minutes.append(max(0, (arrived - scheduled).total_seconds() / 60))
        except ValueError:
            continue
    average_wait = round(sum(wait_minutes) / len(wait_minutes)) if wait_minutes else 0
    followups = [
        item for item in records
        if item["specialty"] == "Veterinaria"
        and item.get("follow_up_date")
        and date.today().isoformat() <= item["follow_up_date"] <= (date.today() + timedelta(days=30)).isoformat()
    ]

    priority_rank = {"urgent": 0, "important": 1, "normal": 2}
    assigned_tasks = [
        {
            "id": item["id"],
            "title": item["title"],
            "message": item.get("message", ""),
            "assigned_user_id": item.get("assigned_user_id") or 0,
            "responsible": item.get("assigned_name") or "Sin asignar",
            "priority": item["priority"],
            "due_at": item["due_at"],
            "source": "Alerta",
            "href": f"/alertas?priority={item['priority']}",
            "is_mine": bool(user_id and item.get("assigned_user_id") == user_id),
            "editable": item.get("source") == "manual",
        }
        for item in all_alerts if not item.get("acknowledged")
    ]
    assigned_tasks.extend({
        "title": f"Revisar cita retrasada: {item['patient']}",
        "id": 0,
        "responsible": item.get("veterinarian") or "Sin asignar",
        "priority": "urgent" if item.get("is_urgent") else "important",
        "due_at": f"{item['date']} {item['time']}",
        "source": "Agenda",
        "href": f"/agenda?day={item['date']}&status=Pendiente",
        "is_mine": bool(user_id and item.get("veterinarian_user_id") == user_id),
        "editable": False,
    } for item in delayed_appointments)
    assigned_tasks.sort(key=lambda item: (
        0 if user_role == "clinical" and item["is_mine"] else 1,
        priority_rank.get(item["priority"], 9), item["due_at"], item["title"],
    ))

    role_focus = {
        "reception": {"title": "Recepción de hoy", "detail": "Llegadas, esperas y cancelaciones", "primary": "En espera", "show_inventory": False, "show_team": False, "show_handoff": False},
        "clinical": {"title": "Mi jornada clínica", "detail": "Consultas activas, pendientes propios y controles", "primary": "En consulta", "show_inventory": True, "show_team": False, "show_handoff": True},
        "admin": {"title": "Operación de la sede", "detail": "Capacidad, alertas y continuidad", "primary": "Pendientes", "show_inventory": True, "show_team": True, "show_handoff": True},
        "owner": {"title": "Operación de la sede", "detail": "Capacidad, alertas y continuidad", "primary": "Pendientes", "show_inventory": True, "show_team": True, "show_handoff": True},
    }.get(user_role, {"title": "Resumen clínico", "detail": "Actividad, prioridades y seguimiento", "primary": "Pendientes", "show_inventory": True, "show_team": True, "show_handoff": True})

    dashboard_trends = [
        _trend_metric("Citas", len(veterinary_appointments), len(previous_veterinary_appointments)),
        _trend_metric("Atenciones", attended(veterinary_appointments), attended(previous_veterinary_appointments)),
        _trend_metric("Alertas", len(active_alerts), sum(1 for item in all_alerts if item.get("due_at", "")[:10] >= dashboard_period["previous_start"] and item.get("due_at", "")[:10] <= dashboard_period["previous_end"]), inverse=True),
        _trend_metric("Consumo", _movement_consumption(dashboard_period["start"], dashboard_period["end"], scope["organization_id"], scope["location_id"]), _movement_consumption(dashboard_period["previous_start"], dashboard_period["previous_end"], scope["organization_id"], scope["location_id"])),
    ]
    consumption_total = _movement_consumption(
        dashboard_period["start"], dashboard_period["end"], scope["organization_id"], scope["location_id"]
    )
    today_start = date.today().isoformat()
    today_appointments = [
        item for item in list_appointments_between(today_start, today_start, organization_id=scope["organization_id"], location_id=scope["location_id"])
        if item["specialty"] == "Veterinaria"
    ]
    today_records = [item for item in records if item["specialty"] == "Veterinaria" and item["encounter_date"] == today_start]
    record_dashboard_snapshot(scope["organization_id"], scope["location_id"], {
        "appointments": len(today_appointments), "attended": attended(today_appointments),
        "cancelled": sum(1 for item in today_appointments if item["status"] == "Cancelada"), "alerts": len(active_alerts),
        "consumption": _movement_consumption(today_start, today_start, scope["organization_id"], scope["location_id"]),
        "followups": sum(1 for item in today_records if item.get("follow_up_date")),
    })
    history_days = 30 if history_span == "month" else 7
    history_series = dashboard_history_series(scope["organization_id"], scope["location_id"], history_days)

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
            "period": dashboard_period,
            "preferences": dashboard_preferences,
            "filters": {"veterinarian": veterinarian_filter, "priority": priority_filter, "status": appointment_status_filter},
            "history_series": history_series,
            "history_span": "month" if history_span == "month" else "week",
            "role_focus": role_focus,
            "appointments": operational_appointments[:4],
            "next_appointment": next_appointment,
            "active_appointment": active_appointment,
            "agenda_summary": veterinary_agenda_summary,
            "inventory_alerts": veterinary_inventory_alerts[:4],
            "inventory_summary": veterinary_inventory_summary,
            "alerts": active_alerts[:4],
            "alerts_total": len(active_alerts),
            "critical_alerts_total": sum(1 for item in active_alerts if item["priority"] == "urgent"),
            "trends": dashboard_trends,
            "clinical_indicators": [
                {"label": "Pacientes atendidos", "value": len({item["patient_id"] for item in veterinary_records}), "detail": "Con registro clínico"},
                {"label": "Cancelaciones", "value": cancelled_appointments, "detail": "En el periodo"},
                {"label": "Espera promedio", "value": f"{average_wait} min", "detail": "Desde la hora programada"},
                {"label": "Controles próximos", "value": len(followups), "detail": "Próximos 30 días"},
            ],
            "assigned_tasks": assigned_tasks[:5],
            "assigned_tasks_total": len(assigned_tasks),
            "my_tasks_total": sum(1 for item in assigned_tasks if item["is_mine"]),
            "cancelled_total": cancelled_appointments,
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
