from __future__ import annotations

from datetime import date, datetime, timedelta
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
            appointments.created_at,
            organizations.name AS organization_name,
            locations.name AS site_name,
            locations.city AS site_city
        FROM appointments
        LEFT JOIN organizations ON organizations.id = appointments.organization_id
        LEFT JOIN locations ON locations.id = appointments.location_id
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
            "organization_name": row["organization_name"] or "-",
            "site_name": row["site_name"] or "-",
            "site_city": row["site_city"] or "-",
        }
        for row in rows
    ]


def create_appointment(payload: dict) -> None:
    payload = _normalize_operational_fields(payload)
    with APPOINTMENT_WRITE_LOCK:
        validate_appointment_slot(payload)
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO appointments (
                    organization_id, location_id, appointment_date, appointment_time,
                    patient_name, service, channel, status, specialty, note,
                    duration_minutes, veterinarian, patient_id, veterinarian_user_id,
                    cancellation_reason, priority, triage_level, triage_note, arrival_at
                )
                VALUES (
                    :organization_id, :location_id, :appointment_date, :appointment_time,
                    :patient_name, :service, :channel, :status, :specialty, :note,
                    :duration_minutes, :veterinarian, :patient_id, :veterinarian_user_id,
                    :cancellation_reason, :priority, :triage_level, :triage_note, :arrival_at
                )
                """,
                payload,
            )
            connection.commit()


def update_appointment_status(appointment_id: int, status: str, cancellation_reason: str = "") -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE appointments SET status = ?, cancellation_reason = ? WHERE id = ?",
            (status.strip(), cancellation_reason.strip(), appointment_id),
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
                    triage_level = ?, triage_note = ?, arrival_at = ?
                WHERE id = ?
                """,
                (
                    payload["appointment_date"], payload["appointment_time"],
                    payload["patient_name"], payload["service"], payload["channel"],
                    payload["status"], payload["specialty"], payload["note"],
                    payload["duration_minutes"], payload["veterinarian"], payload["patient_id"],
                    payload["veterinarian_user_id"], payload.get("cancellation_reason", ""),
                    payload.get("priority", "Normal"), payload["triage_level"],
                    payload["triage_note"], payload["arrival_at"], appointment_id,
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
          AND veterinarian_user_id = ? AND status != 'Cancelada'
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
        if item.get("veterinarian_user_id") != provider["id"] or item["status"] == "Cancelada":
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
        "virtual": virtual,
        "urgent": sum(1 for item in items if item.get("priority") == "Urgente" and item["status"] not in {"Atendida", "Cancelada"}),
        "triage_red": sum(1 for item in items if item.get("triage_level") == "Rojo" and item["status"] not in {"Atendida", "Cancelada"}),
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
    }
