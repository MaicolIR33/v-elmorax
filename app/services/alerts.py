from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta

from app.core.database import get_connection
from app.services.inventory import list_inventory_items


PRIORITY_ORDER = {"urgent": 0, "important": 1, "normal": 2}


def create_alert(payload: dict) -> None:
    with get_connection() as connection:
        connection.execute(
            """INSERT INTO alerts (
                organization_id, location_id, created_by, assigned_user_id,
                title, message, priority, status, due_at, recurrence,
                escalation_minutes, entity_type, entity_id, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, 'manual')""",
            (payload["organization_id"], payload["location_id"], payload.get("created_by"),
             payload.get("assigned_user_id") or None, payload["title"], payload.get("message", ""),
             payload.get("priority", "normal"), payload["due_at"], payload.get("recurrence", "once"),
             max(0, int(payload.get("escalation_minutes") or 0)), payload.get("entity_type", ""),
             payload.get("entity_id") or None),
        )
        connection.commit()


def alert_belongs_to_scope(alert_id: int, organization_id: int, location_id: int) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT 1 FROM alerts WHERE id = ? AND organization_id = ? AND location_id = ?",
            (alert_id, organization_id, location_id),
        ).fetchone()
    return row is not None


def list_manual_alerts(
    organization_id: str = "", location_id: str = "", *, resolved: bool = False
) -> list[dict]:
    query = """SELECT alerts.*, users.full_name AS assigned_name FROM alerts
               LEFT JOIN users ON users.id = alerts.assigned_user_id
               WHERE alerts.status {} 'resolved'""".format("=" if resolved else "!=")
    params: list = []
    if organization_id:
        query += " AND alerts.organization_id = ?"
        params.append(int(organization_id))
    if location_id:
        query += " AND alerts.location_id = ?"
        params.append(int(location_id))
    query += " ORDER BY " + ("alerts.resolved_at DESC, alerts.id DESC" if resolved else "alerts.due_at ASC")
    with get_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()
    return [_serialize_manual(dict(row)) for row in rows]


def list_automatic_alerts(organization_id: str = "", location_id: str = "") -> list[dict]:
    today = date.today()
    alerts: list[dict] = []
    for item in list_inventory_items(organization_id=organization_id, location_id=location_id):
        expiry = date.fromisoformat(item["expiry_date"])
        if expiry < today:
            alerts.append(_automatic(f"inventory-expired-{item['id']}", item["name"], f"Venció hace {(today - expiry).days} días", "urgent", "inventory", item["id"], item["expiry_date"]))
        elif (expiry - today).days <= 30:
            alerts.append(_automatic(f"inventory-expiry-{item['id']}", item["name"], f"Vence en {(expiry - today).days} días", "important", "inventory", item["id"], item["expiry_date"]))
        if item["quantity"] <= item["min_stock"]:
            priority = "urgent" if item["quantity"] == 0 else "important"
            alerts.append(_automatic(f"inventory-stock-{item['id']}", item["name"], f"Stock: {item['quantity']} · mínimo: {item['min_stock']}", priority, "inventory", item["id"], today.isoformat()))
        if item.get("cold_chain_incident"):
            alerts.append(_automatic(f"inventory-cold-{item['id']}", item["name"], "Temperatura fuera del rango de conservación 2–8 °C", "urgent", "inventory", item["id"], today.isoformat()))

    return alerts


def list_alerts(organization_id: str = "", location_id: str = "") -> list[dict]:
    automatic = list_automatic_alerts(organization_id, location_id)
    _purge_stale_automatic_acknowledgements(automatic, organization_id, location_id)
    items = list_manual_alerts(organization_id, location_id) + automatic
    acknowledged = _acknowledged_alerts(organization_id, location_id)
    for item in items:
        item["acknowledged"] = item["key"] in acknowledged
        item["acknowledged_by"] = acknowledged.get(item["key"], {}).get("user_name", "")
        item["acknowledged_at"] = acknowledged.get(item["key"], {}).get("acknowledged_at", "")
    return sorted(items, key=lambda item: (PRIORITY_ORDER.get(item["priority"], 9), item["due_at"]))


def list_resolved_alerts(organization_id: str = "", location_id: str = "", limit: int = 50) -> list[dict]:
    return list_manual_alerts(organization_id, location_id, resolved=True)[:limit]


def update_alert(alert_id: int, organization_id: int, location_id: int, payload: dict) -> bool:
    with get_connection() as connection:
        cursor = connection.execute(
            """UPDATE alerts SET title = ?, message = ?, priority = ?, due_at = ?,
                   recurrence = ?, assigned_user_id = ?, escalation_minutes = ?, status = 'active', resolved_at = ''
               WHERE id = ? AND organization_id = ? AND location_id = ? AND source = 'manual'""",
            (payload["title"].strip(), payload.get("message", "").strip(), payload["priority"],
             payload["due_at"], payload["recurrence"], payload.get("assigned_user_id") or None,
             max(0, int(payload.get("escalation_minutes") or 0)), alert_id, organization_id, location_id),
        )
        connection.execute(
            "DELETE FROM alert_acknowledgements WHERE alert_key = ? AND organization_id = ? AND location_id = ?",
            (f"manual-{alert_id}", organization_id, location_id),
        )
        connection.commit()
    return cursor.rowcount > 0


def list_notification_alerts(organization_id: str = "", location_id: str = "") -> list[dict]:
    now = datetime.now()
    return [
        item for item in list_alerts(organization_id, location_id)
        if not item.get("acknowledged") and (item["source"] == "automatic" or datetime.fromisoformat(item["due_at"]) <= now)
    ]


def acknowledge_alert(alert_key: str, organization_id: int, location_id: int, user_id: int) -> bool:
    valid = next(
        (item for item in list_alerts(str(organization_id), str(location_id)) if item["key"] == alert_key),
        None,
    )
    if valid is None:
        return False
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM alert_acknowledgements WHERE alert_key = ? AND organization_id = ? AND location_id = ?",
            (alert_key, organization_id, location_id),
        )
        connection.execute(
            """INSERT INTO alert_acknowledgements
               (alert_key, organization_id, location_id, user_id, acknowledged_at)
               VALUES (?, ?, ?, ?, ?)""",
            (alert_key, organization_id, location_id, user_id, datetime.now().isoformat(timespec="minutes")),
        )
        connection.commit()
    return True


def resolve_alert(alert_id: int, organization_id: int, location_id: int) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT due_at, recurrence FROM alerts WHERE id = ? AND organization_id = ? AND location_id = ? AND source = 'manual'",
            (alert_id, organization_id, location_id),
        ).fetchone()
        if not row:
            return None
        if row["recurrence"] == "once":
            connection.execute("UPDATE alerts SET status = 'resolved', resolved_at = ? WHERE id = ?", (datetime.now().isoformat(timespec="minutes"), alert_id))
            result = {"recurring": False, "next_due": ""}
        else:
            next_due = _next_occurrence(datetime.fromisoformat(row["due_at"]), row["recurrence"])
            while next_due <= datetime.now():
                next_due = _next_occurrence(next_due, row["recurrence"])
            connection.execute("UPDATE alerts SET status = 'active', due_at = ?, resolved_at = '' WHERE id = ?", (next_due.isoformat(timespec="minutes"), alert_id))
            result = {"recurring": True, "next_due": next_due.strftime("%Y-%m-%d %H:%M")}
            connection.execute(
                "DELETE FROM alert_acknowledgements WHERE alert_key = ? AND organization_id = ? AND location_id = ?",
                (f"manual-{alert_id}", organization_id, location_id),
            )
        connection.commit()
    return result


def snooze_alert(alert_id: int, organization_id: int, location_id: int, hours: int = 24) -> str:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT due_at FROM alerts WHERE id = ? AND organization_id = ? AND location_id = ? AND source = 'manual'",
            (alert_id, organization_id, location_id),
        ).fetchone()
        if not row:
            return ""
        due = datetime.now() + timedelta(hours=max(1, min(hours, 168)))
        connection.execute("UPDATE alerts SET status = 'snoozed', due_at = ? WHERE id = ?", (due.isoformat(timespec="minutes"), alert_id))
        connection.commit()
    return due.strftime("%Y-%m-%d %H:%M")


def delete_alert(alert_id: int, organization_id: int, location_id: int) -> bool:
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM alerts WHERE id = ? AND organization_id = ? AND location_id = ? AND source = 'manual'",
            (alert_id, organization_id, location_id),
        )
        connection.commit()
    return cursor.rowcount > 0


def _automatic(alert_id: str, title: str, message: str, priority: str, entity_type: str, entity_id: int, due_at: str) -> dict:
    return {"id": alert_id, "key": alert_id, "title": title, "message": message, "priority": priority, "priority_label": {"urgent": "Urgente", "important": "Importante", "normal": "Normal"}[priority], "status": "active", "status_label": "Activa", "is_due": True, "due_at": due_at, "recurrence": "automatic", "recurrence_label": "Automática", "source": "automatic", "assigned_name": "Sistema", "entity_type": entity_type, "entity_id": entity_id}


def _serialize_manual(row: dict) -> dict:
    row["key"] = f"manual-{row['id']}"
    row["priority_label"] = {"urgent": "Urgente", "important": "Importante", "normal": "Normal"}.get(row["priority"], "Normal")
    row["recurrence_label"] = {"once": "Una vez", "daily": "Diaria", "weekly": "Semanal", "monthly": "Mensual"}.get(row["recurrence"], row["recurrence"])
    due = datetime.fromisoformat(row["due_at"])
    escalation_minutes = max(0, int(row.get("escalation_minutes") or 0))
    row["escalated"] = bool(
        escalation_minutes
        and due + timedelta(minutes=escalation_minutes) <= datetime.now()
        and row["priority"] != "urgent"
    )
    if row["escalated"]:
        row["priority"] = "urgent"
        row["priority_label"] = "Escalada"
    row["escalation_label"] = (
        f"Escala tras {escalation_minutes} min" if escalation_minutes else "Sin escalamiento"
    )
    if row["status"] == "resolved":
        row["status_label"] = "Resuelta"
        row["is_due"] = False
        return row
    if row["status"] == "snoozed":
        row["status_label"] = "Pospuesta"
    elif due > datetime.now():
        row["status_label"] = "Programada"
    else:
        row["status_label"] = "Activa"
    row["is_due"] = due <= datetime.now()
    return row


def _purge_stale_automatic_acknowledgements(
    active_automatic: list[dict], organization_id: str, location_id: str
) -> None:
    if not organization_id or not location_id:
        return
    active_keys = {item["key"] for item in active_automatic}
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT alert_key FROM alert_acknowledgements
               WHERE organization_id = ? AND location_id = ? AND alert_key LIKE 'inventory-%'""",
            (int(organization_id), int(location_id)),
        ).fetchall()
        stale = [row["alert_key"] for row in rows if row["alert_key"] not in active_keys]
        for key in stale:
            connection.execute(
                "DELETE FROM alert_acknowledgements WHERE alert_key = ? AND organization_id = ? AND location_id = ?",
                (key, int(organization_id), int(location_id)),
            )
        if stale:
            connection.commit()


def _acknowledged_alerts(organization_id: str = "", location_id: str = "") -> dict[str, dict]:
    query = """SELECT alert_acknowledgements.alert_key, alert_acknowledgements.acknowledged_at,
                      users.full_name AS user_name
               FROM alert_acknowledgements
               LEFT JOIN users ON users.id = alert_acknowledgements.user_id WHERE 1=1"""
    params: list[int] = []
    if organization_id:
        query += " AND alert_acknowledgements.organization_id = ?"
        params.append(int(organization_id))
    if location_id:
        query += " AND alert_acknowledgements.location_id = ?"
        params.append(int(location_id))
    with get_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()
    return {row["alert_key"]: dict(row) for row in rows}


def _next_occurrence(value: datetime, recurrence: str) -> datetime:
    if recurrence == "daily":
        return value + timedelta(days=1)
    if recurrence == "weekly":
        return value + timedelta(days=7)
    month = 1 if value.month == 12 else value.month + 1
    year = value.year + 1 if value.month == 12 else value.year
    return value.replace(year=year, month=month, day=min(value.day, monthrange(year, month)[1]))
