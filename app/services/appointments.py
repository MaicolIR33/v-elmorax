from __future__ import annotations

from datetime import date

from app.core.database import get_connection


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
            "organization_name": row["organization_name"] or "-",
            "site_name": row["site_name"] or "-",
            "site_city": row["site_city"] or "-",
        }
        for row in rows
    ]


def create_appointment(payload: dict) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO appointments (
                organization_id, location_id, appointment_date, appointment_time,
                patient_name, service, channel, status, specialty, note
            )
            VALUES (
                :organization_id, :location_id, :appointment_date, :appointment_time,
                :patient_name, :service, :channel, :status, :specialty, :note
            )
            """,
            payload,
        )
        connection.commit()


def update_appointment_status(appointment_id: int, status: str) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE appointments SET status = ? WHERE id = ?",
            (status.strip(), appointment_id),
        )
        connection.commit()


def delete_appointment(appointment_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM appointments WHERE id = ?",
            (appointment_id,),
        )
        connection.commit()


def appointment_summary(items: list[dict]) -> dict:
    confirmed = sum(1 for item in items if item["status"] == "Confirmada")
    pending = sum(1 for item in items if item["status"] in {"En espera", "Llamar"})
    virtual = sum(1 for item in items if item["channel"] == "Virtual")
    return {
        "total": len(items),
        "confirmed": confirmed,
        "pending": pending,
        "virtual": virtual,
    }
