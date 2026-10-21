from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import uuid4
from threading import RLock

from app.core.database import get_connection


APPOINTMENT_WRITE_LOCK = RLock()


def list_appointments(
    day: str | None = None,
    organization_id: str = "",
    location_id: str = "",
) -> list[dict]:
    selected_day = day or date.today().isoformat()
    query = """
        SELECT
            appointments.id,
            appointments.organization_id,
            appointments.location_id,
            appointments.appointment_date,
            appointments.appointment_time,
            appointments.patient_name,
            appointments.service,
            appointments.channel,
            appointments.status,
            appointments.specialty,
            appointments.note,
            appointments.priority,
            appointments.triage_level,
            appointments.triage_note,
            appointments.arrival_at,
            appointments.duration_minutes,
            appointments.veterinarian,
            appointments.patient_id,
            appointments.veterinarian_user_id,
            appointments.cancellation_reason,
            appointments.resource_id, appointments.resource_name, appointments.recurrence_group,
            appointments.reminder_channel, appointments.reminder_status, appointments.no_show_reason,
            appointments.created_at,
            patients.allergies AS patient_allergies, patients.clinical_alert AS patient_alert,
            patients.preexisting_conditions AS patient_conditions,
            (SELECT encounter_date FROM clinical_records cr WHERE cr.patient_id = appointments.patient_id ORDER BY encounter_date DESC, id DESC LIMIT 1) AS last_clinical_date,
            (SELECT diagnosis FROM clinical_records cr WHERE cr.patient_id = appointments.patient_id ORDER BY encounter_date DESC, id DESC LIMIT 1) AS last_diagnosis,
            organizations.name AS organization_name,
            locations.name AS site_name,
            locations.city AS site_city
        FROM appointments
        LEFT JOIN organizations ON organizations.id = appointments.organization_id
        LEFT JOIN locations ON locations.id = appointments.location_id
        LEFT JOIN patients ON patients.id = appointments.patient_id
        WHERE appointment_date = ?
    """
    params: list[str | int] = [selected_day]
    if organization_id:
        query += " AND appointments.organization_id = ?"
        params.append(int(organization_id))
    if location_id:
        query += " AND appointments.location_id = ?"
        params.append(int(location_id))
    query += " ORDER BY appointment_time ASC, appointments.id ASC"
    with get_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()

    return [
        {
            "id": row["id"],
            "organization_id": row["organization_id"],
            "location_id": row["location_id"],
            "time": row["appointment_time"],
            "date": row["appointment_date"],
            "patient": row["patient_name"],
            "service": row["service"],
            "channel": row["channel"],
            "status": row["status"],
            "specialty": row["specialty"],
            "note": row["note"],
            "priority": row["priority"] or "Normal",
            "triage_level": row["triage_level"] or "",
            "triage_note": row["triage_note"] or "",
            "arrival_at": row["arrival_at"] or "",
            "duration_minutes": row["duration_minutes"],
            "veterinarian": row["veterinarian"],
            "patient_id": row["patient_id"],
            "veterinarian_user_id": row["veterinarian_user_id"],
            "cancellation_reason": row["cancellation_reason"],
            "resource_id": row["resource_id"] or 0,
            "resource_name": row["resource_name"] or "",
            "recurrence_group": row["recurrence_group"] or "",
            "reminder_channel": row["reminder_channel"] or "",
            "reminder_status": row["reminder_status"] or "",
            "no_show_reason": row["no_show_reason"] or "",
            "patient_allergies": row["patient_allergies"] or "",
            "patient_alert": row["patient_alert"] or "",
            "patient_conditions": row["patient_conditions"] or "",
            "last_clinical_date": row["last_clinical_date"] or "",
            "last_diagnosis": row["last_diagnosis"] or "",
            "wait_minutes": _wait_minutes(row["appointment_date"], row["appointment_time"], row["arrival_at"] or ""),
            "organization_name": row["organization_name"] or "-",
            "site_name": row["site_name"] or "-",
            "site_city": row["site_city"] or "-",
        }
        for row in rows
    ]


def list_appointments_between(
    start_day: str,
    end_day: str,
    organization_id: str = "",
    location_id: str = "",
) -> list[dict]:
    """Return appointments for an inclusive date range using the same shape as Agenda."""
    start = date.fromisoformat(start_day)
    end = date.fromisoformat(end_day)
    if end < start:
        start, end = end, start
    # Keep a dashboard range bounded even when a malformed URL is supplied.
    if (end - start).days > 62:
        end = start + timedelta(days=62)

    items: list[dict] = []
    cursor = start
    while cursor <= end:
        items.extend(list_appointments(cursor.isoformat(), organization_id, location_id))
        cursor += timedelta(days=1)
    return items


def create_appointment(payload: dict) -> int:
    payload = _normalize_operational_fields(payload)
    with APPOINTMENT_WRITE_LOCK:
        validate_appointment_slot(payload)
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO appointments (
                    organization_id, location_id, appointment_date, appointment_time,
                    patient_name, service, channel, status, specialty, note,
                    duration_minutes, veterinarian, patient_id, veterinarian_user_id,
                    cancellation_reason, priority, triage_level, triage_note, arrival_at,
                    resource_id, resource_name, recurrence_group, reminder_channel, reminder_status
                )
                VALUES (
                    :organization_id, :location_id, :appointment_date, :appointment_time,
                    :patient_name, :service, :channel, :status, :specialty, :note,
                    :duration_minutes, :veterinarian, :patient_id, :veterinarian_user_id,
                    :cancellation_reason, :priority, :triage_level, :triage_note, :arrival_at,
                    :resource_id, :resource_name, :recurrence_group, :reminder_channel, :reminder_status
                )
                """,
                payload,
            )
            inserted = connection.execute(
                "SELECT id FROM appointments WHERE organization_id=? AND location_id=? AND patient_id=? AND appointment_date=? AND appointment_time=? ORDER BY id DESC LIMIT 1",
                (payload["organization_id"], payload["location_id"], payload["patient_id"], payload["appointment_date"], payload["appointment_time"]),
            ).fetchone()
            appointment_id = int(inserted["id"] if inserted else 0)
            if payload.get("reminder_channel"):
                connection.execute(
                    "INSERT INTO appointment_notifications (appointment_id, organization_id, location_id, channel, kind, status, scheduled_at, detail) VALUES (?, ?, ?, ?, 'Confirmación', 'Pendiente', ?, ?)",
                    (appointment_id, payload["organization_id"], payload["location_id"], payload["reminder_channel"], f"{payload['appointment_date']}T{payload['appointment_time']}", "Confirmación y recordatorio programado"),
                )
            connection.commit()
    return appointment_id


def update_appointment_status(appointment_id: int, status: str, cancellation_reason: str = "") -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE appointments SET status = ?, cancellation_reason = ?, arrival_at = CASE WHEN ? = 'En espera' AND arrival_at = '' THEN ? ELSE arrival_at END, no_show_reason = CASE WHEN ? = 'No asistió' THEN ? ELSE no_show_reason END WHERE id = ?",
            (status.strip(), cancellation_reason.strip(), status.strip(), datetime.now().isoformat(timespec="minutes"), status.strip(), cancellation_reason.strip(), appointment_id),
        )
        connection.commit()


def update_appointment(appointment_id: int, payload: dict) -> None:
    payload = _normalize_operational_fields(payload)
    with APPOINTMENT_WRITE_LOCK:
        validate_appointment_slot(payload, exclude_id=appointment_id)
        with get_connection() as connection:
            connection.execute(
                """
                UPDATE appointments
                SET appointment_date = ?, appointment_time = ?, patient_name = ?,
                    service = ?, channel = ?, status = ?, specialty = ?, note = ?,
                    duration_minutes = ?, veterinarian = ?, patient_id = ?,
                    veterinarian_user_id = ?, cancellation_reason = ?, priority = ?,
                    triage_level = ?, triage_note = ?, arrival_at = ?, resource_id = ?, resource_name = ?, reminder_channel = ?
                WHERE id = ?
                """,
                (
                    payload["appointment_date"], payload["appointment_time"],
                    payload["patient_name"], payload["service"], payload["channel"],
                    payload["status"], payload["specialty"], payload["note"],
                    payload["duration_minutes"], payload["veterinarian"], payload["patient_id"],
                    payload["veterinarian_user_id"], payload.get("cancellation_reason", ""),
                    payload.get("priority", "Normal"), payload["triage_level"],
                    payload["triage_note"], payload["arrival_at"], payload.get("resource_id") or None,
                    payload.get("resource_name", ""), payload.get("reminder_channel", ""), appointment_id,
                ),
            )
            connection.commit()


def validate_appointment_slot(payload: dict, exclude_id: int | None = None) -> None:
    """Prevent overlapping appointments for the same veterinarian and location."""
    veterinarian = payload.get("veterinarian", "").strip()
    if not veterinarian:
        raise ValueError("Selecciona el veterinario responsable.")
    start = datetime.strptime(
        f"{payload['appointment_date']} {payload['appointment_time']}", "%Y-%m-%d %H:%M"
    )
    duration = max(10, int(payload.get("duration_minutes", 30)))
    end = start + timedelta(minutes=duration)
    is_emergency = payload.get("priority", "Normal").strip() == "Urgente"
    if start.date() < date.today():
        raise ValueError("No se pueden programar citas en una fecha anterior a hoy.")
    veterinarian_user_id = int(payload.get("veterinarian_user_id") or 0)
    with get_connection() as connection:
        provider = connection.execute(
            "SELECT working_days, work_start, work_end, break_start, break_end, unavailable_dates FROM users WHERE id = ? AND is_active = 1",
            (veterinarian_user_id,),
        ).fetchone()
    if provider is None:
        raise ValueError("Selecciona un veterinario activo de la sede.")
    working_days = {int(value) for value in (provider["working_days"] or "").split(",") if value.strip().isdigit()}
    unavailable = {value.strip() for value in (provider["unavailable_dates"] or "").split(",") if value.strip()}
    if not is_emergency and (start.weekday() not in working_days or payload["appointment_date"] in unavailable):
        raise ValueError("El veterinario no está disponible en la fecha seleccionada.")
    work_start = datetime.strptime(f"{payload['appointment_date']} {provider['work_start']}", "%Y-%m-%d %H:%M")
    work_end = datetime.strptime(f"{payload['appointment_date']} {provider['work_end']}", "%Y-%m-%d %H:%M")
    if not is_emergency and (start < work_start or end > work_end):
        raise ValueError(f"El horario disponible es de {provider['work_start']} a {provider['work_end']}.")
    if not is_emergency and provider["break_start"] and provider["break_end"]:
        break_start = datetime.strptime(f"{payload['appointment_date']} {provider['break_start']}", "%Y-%m-%d %H:%M")
        break_end = datetime.strptime(f"{payload['appointment_date']} {provider['break_end']}", "%Y-%m-%d %H:%M")
        if start < break_end and end > break_start:
            raise ValueError("Ese horario coincide con el descanso del veterinario.")
    query = """
        SELECT id, appointment_time, duration_minutes FROM appointments
        WHERE appointment_date = ? AND location_id = ?
          AND veterinarian_user_id = ? AND status NOT IN ('Cancelada', 'No asistió')
    """
    params: list[str | int] = [payload["appointment_date"], payload["location_id"], veterinarian_user_id]
    if exclude_id is not None:
        query += " AND id != ?"
        params.append(exclude_id)
    with get_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()
    for row in rows:
        other_start = datetime.strptime(
            f"{payload['appointment_date']} {row['appointment_time']}", "%Y-%m-%d %H:%M"
        )
        other_end = other_start + timedelta(minutes=max(10, row["duration_minutes"] or 30))
        if not is_emergency and start < other_end and end > other_start:
            raise ValueError(
                f"{veterinarian} ya tiene una cita entre {other_start:%H:%M} y {other_end:%H:%M}."
            )
    resource_id = int(payload.get("resource_id") or 0)
    if resource_id and not is_emergency:
        with get_connection() as connection:
            resource = connection.execute("SELECT name FROM appointment_resources WHERE id=? AND organization_id=? AND location_id=? AND is_active=1", (resource_id, payload["organization_id"], payload["location_id"])).fetchone()
            resource_rows = connection.execute("SELECT appointment_time, duration_minutes FROM appointments WHERE appointment_date=? AND location_id=? AND resource_id=? AND status NOT IN ('Cancelada','No asistió')" + (" AND id != ?" if exclude_id else ""), tuple([payload["appointment_date"], payload["location_id"], resource_id] + ([exclude_id] if exclude_id else []))).fetchall()
        if resource is None:
            raise ValueError("Selecciona un consultorio o recurso activo de la sede.")
        payload["resource_name"] = resource["name"]
        for row in resource_rows:
            other_start = datetime.strptime(f"{payload['appointment_date']} {row['appointment_time']}", "%Y-%m-%d %H:%M")
            if start < other_start + timedelta(minutes=max(10, row["duration_minutes"] or 30)) and end > other_start:
                raise ValueError(f"{resource['name']} ya está reservado en ese horario.")
    with get_connection() as connection:
        blocks = connection.execute(
            """SELECT start_time, end_time, block_type FROM appointment_blocks
               WHERE organization_id=? AND location_id=? AND block_date=?
                 AND (veterinarian_user_id IS NULL OR veterinarian_user_id=?)""",
            (payload["organization_id"], payload["location_id"], payload["appointment_date"], veterinarian_user_id),
        ).fetchall()
    for block in blocks:
        # A block without an hour applies to the entire day (holidays and absences).
        if not block["start_time"] or not block["end_time"]:
            raise ValueError(f"La agenda está bloqueada por: {block['block_type']}.")
        block_start = datetime.strptime(f"{payload['appointment_date']} {block['start_time']}", "%Y-%m-%d %H:%M")
        block_end = datetime.strptime(f"{payload['appointment_date']} {block['end_time']}", "%Y-%m-%d %H:%M")
        if start < block_end and end > block_start:
            raise ValueError(f"El horario coincide con un bloqueo: {block['block_type']}.")
    patient_id = int(payload.get("patient_id") or 0)
    with get_connection() as connection:
        duplicate = connection.execute(
            """SELECT appointment_time FROM appointments WHERE appointment_date = ?
               AND patient_id = ? AND status != 'Cancelada' AND (? IS NULL OR id != ?)""",
            (payload["appointment_date"], patient_id, exclude_id, exclude_id or 0),
        ).fetchone()
    if duplicate and not is_emergency:
        other = datetime.strptime(f"{payload['appointment_date']} {duplicate['appointment_time']}", "%Y-%m-%d %H:%M")
        if abs((start - other).total_seconds()) < 7200:
            raise ValueError("Este paciente ya tiene otra cita cercana. Revisa la agenda antes de continuar.")


def appointment_belongs_to_scope(appointment_id: int, organization_id: int, location_id: int) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id FROM appointments WHERE id=? AND organization_id=? AND location_id=?",
            (appointment_id, organization_id, location_id),
        ).fetchone()
    return row is not None


def available_slots(day: str, provider: dict, appointments: list[dict], duration: int = 30) -> list[str]:
    selected = date.fromisoformat(day)
    days = {int(value) for value in provider.get("working_days", "").split(",") if value.strip().isdigit()}
    unavailable = {value.strip() for value in provider.get("unavailable_dates", "").split(",") if value.strip()}
    if selected.weekday() not in days or day in unavailable:
        return []
    cursor = datetime.strptime(f"{day} {provider['work_start']}", "%Y-%m-%d %H:%M")
    finish = datetime.strptime(f"{day} {provider['work_end']}", "%Y-%m-%d %H:%M")
    break_start = datetime.strptime(f"{day} {provider['break_start']}", "%Y-%m-%d %H:%M") if provider.get("break_start") else None
    break_end = datetime.strptime(f"{day} {provider['break_end']}", "%Y-%m-%d %H:%M") if provider.get("break_end") else None
    busy = []
    for item in appointments:
        if item.get("veterinarian_user_id") != provider["id"] or item["status"] in {"Cancelada", "No asistió"}:
            continue
        busy_start = datetime.strptime(f"{day} {item['time']}", "%Y-%m-%d %H:%M")
        busy.append((busy_start, busy_start + timedelta(minutes=item["duration_minutes"])))
    slots = []
    while cursor + timedelta(minutes=duration) <= finish:
        slot_end = cursor + timedelta(minutes=duration)
        in_break = break_start and break_end and cursor < break_end and slot_end > break_start
        if not in_break and not any(cursor < busy_end and slot_end > busy_start for busy_start, busy_end in busy):
            slots.append(cursor.strftime("%H:%M"))
        cursor += timedelta(minutes=30)
    return slots


def delete_appointment(appointment_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM appointments WHERE id = ?",
            (appointment_id,),
        )
        connection.commit()


def _wait_minutes(day: str, time: str, arrival_at: str) -> int:
    if not arrival_at:
        return 0
    try:
        return max(0, round((datetime.fromisoformat(arrival_at) - datetime.fromisoformat(f"{day}T{time}")).total_seconds() / 60))
    except ValueError:
        return 0


def reschedule_appointment(appointment_id: int, appointment_date: str, appointment_time: str) -> None:
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone()
    if row is None:
        raise ValueError("No se encontró la cita.")
    payload = dict(row)
    payload.update({"appointment_date": appointment_date, "appointment_time": appointment_time})
    update_appointment(appointment_id, payload)


def create_recurring_appointments(payload: dict, interval_days: int, occurrences: int) -> int:
    group = str(uuid4())
    created = 0
    for step in range(max(1, min(24, occurrences))):
        copied = {**payload, "appointment_date": (date.fromisoformat(payload["appointment_date"]) + timedelta(days=interval_days * step)).isoformat(), "recurrence_group": group}
        create_appointment(copied)
        created += 1
    return created


def list_appointment_resources(organization_id: str, location_id: str) -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute("SELECT id, name, resource_type FROM appointment_resources WHERE organization_id=? AND location_id=? AND is_active=1 ORDER BY resource_type, name", (int(organization_id), int(location_id))).fetchall()
    return [dict(row) for row in rows]


def create_appointment_resource(organization_id: int, location_id: int, name: str, resource_type: str) -> None:
    with get_connection() as connection:
        connection.execute("INSERT INTO appointment_resources (organization_id, location_id, name, resource_type) VALUES (?, ?, ?, ?)", (organization_id, location_id, name.strip(), resource_type.strip() or "Consultorio"))
        connection.commit()


def create_waitlist_entry(payload: dict) -> None:
    with get_connection() as connection:
        connection.execute("INSERT INTO appointment_waitlist (organization_id, location_id, patient_id, service, veterinarian_user_id, requested_date, preferred_time, priority, channel, note) VALUES (:organization_id,:location_id,:patient_id,:service,:veterinarian_user_id,:requested_date,:preferred_time,:priority,:channel,:note)", payload)
        connection.commit()


def list_waitlist(organization_id: str, location_id: str) -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute("SELECT w.*, p.display_name AS patient FROM appointment_waitlist w JOIN patients p ON p.id=w.patient_id WHERE w.organization_id=? AND w.location_id=? AND w.status IN ('En espera','Avisado') ORDER BY CASE w.status WHEN 'En espera' THEN 0 ELSE 1 END, CASE w.priority WHEN 'Urgente' THEN 0 ELSE 1 END, w.created_at", (int(organization_id), int(location_id))).fetchall()
    return [dict(row) for row in rows]


def notify_waitlist_of_opening(organization_id: int, location_id: int, day: str, veterinarian_user_id: int | None = None) -> dict | None:
    """Offer the first matching waiting-list request when a slot is released.

    Delivery is represented in the notification outbox, allowing the configured
    mail/SMS/WhatsApp integration to process it without losing clinical traceability.
    """
    with get_connection() as connection:
        query = """SELECT * FROM appointment_waitlist
                   WHERE organization_id=? AND location_id=? AND status='En espera'
                     AND (requested_date='' OR requested_date=? )"""
        params: list[object] = [organization_id, location_id, day]
        if veterinarian_user_id:
            query += " AND (veterinarian_user_id IS NULL OR veterinarian_user_id=?)"
            params.append(veterinarian_user_id)
        query += " ORDER BY CASE priority WHEN 'Urgente' THEN 0 ELSE 1 END, created_at LIMIT 1"
        entry = connection.execute(query, tuple(params)).fetchone()
        if entry is None:
            return None
        notified_at = datetime.now().isoformat(timespec="minutes")
        connection.execute(
            "UPDATE appointment_waitlist SET status='Avisado', notified_at=? WHERE id=?",
            (notified_at, entry["id"]),
        )
        connection.execute(
            """INSERT INTO appointment_notifications
               (appointment_id, organization_id, location_id, channel, kind, status, scheduled_at, detail)
               VALUES (NULL, ?, ?, ?, 'Cupo disponible', 'Pendiente', ?, ?)""",
            (organization_id, location_id, entry["channel"], notified_at,
             f"Cupo liberado para {entry['service']} el {day}; paciente #{entry['patient_id']}"),
        )
        connection.commit()
    return dict(entry)


def create_appointment_block(payload: dict) -> None:
    with get_connection() as connection:
        connection.execute("INSERT INTO appointment_blocks (organization_id,location_id,veterinarian_user_id,block_date,start_time,end_time,block_type,note) VALUES (:organization_id,:location_id,:veterinarian_user_id,:block_date,:start_time,:end_time,:block_type,:note)", payload)
        connection.commit()


def appointment_summary(items: list[dict]) -> dict:
    confirmed = sum(1 for item in items if item["status"] == "Confirmada")
    pending = sum(1 for item in items if item["status"] in {"Pendiente", "En espera", "Llamar"})
    virtual = sum(1 for item in items if item["channel"] == "Virtual")
    return {
        "total": len(items),
        "confirmed": confirmed,
        "pending": pending,
        "waiting": sum(1 for item in items if item["status"] == "En espera"),
        "in_consultation": sum(1 for item in items if item["status"] == "En consulta"),
        "cancelled": sum(1 for item in items if item["status"] == "Cancelada"),
        "no_show": sum(1 for item in items if item["status"] == "No asistió"),
        "virtual": virtual,
        "urgent": sum(1 for item in items if item.get("priority") == "Urgente" and item["status"] not in {"Atendida", "Cancelada", "No asistió"}),
        "triage_red": sum(1 for item in items if item.get("triage_level") == "Rojo" and item["status"] not in {"Atendida", "Cancelada", "No asistió"}),
    }


def _normalize_operational_fields(payload: dict) -> dict:
    priority = "Urgente" if payload.get("priority") == "Urgente" else "Normal"
    triage_level = payload.get("triage_level", "").strip()
    if priority != "Urgente":
        triage_level = ""
    elif triage_level not in {"Rojo", "Naranja", "Amarillo", "Verde", "Azul"}:
        triage_level = "Amarillo"
    return {
        **payload,
        "priority": priority,
        "triage_level": triage_level,
        "triage_note": payload.get("triage_note", "").strip() if priority == "Urgente" else "",
        "arrival_at": payload.get("arrival_at", "").strip() if priority == "Urgente" else "",
        "resource_id": int(payload.get("resource_id") or 0) or None,
        "resource_name": payload.get("resource_name", "").strip(),
        "recurrence_group": payload.get("recurrence_group", "").strip(),
        "reminder_channel": payload.get("reminder_channel", "").strip(),
        "reminder_status": payload.get("reminder_status", "Pendiente").strip(),
    }
