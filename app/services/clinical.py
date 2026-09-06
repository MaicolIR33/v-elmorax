from __future__ import annotations

from datetime import date

from app.core.database import get_connection


def list_patients(
    organization_id: str = "",
    location_id: str = "",
) -> list[dict]:
    query = """
        SELECT
            patients.id,
            patients.organization_id,
            patients.location_id,
            patients.display_name,
            patients.patient_type,
            patients.specialty,
            patients.owner_name,
            patients.phone,
            patients.last_visit,
            patients.document_number,
            patients.birth_date,
            patients.sex,
            patients.insurance_name,
            patients.species,
            patients.breed,
            patients.weight_kg,
            patients.vaccine_status,
            patients.created_at,
            organizations.name AS organization_name,
            locations.name AS site_name,
            locations.city AS site_city
        FROM patients
        LEFT JOIN organizations ON organizations.id = patients.organization_id
        LEFT JOIN locations ON locations.id = patients.location_id
        WHERE 1 = 1
    """
    params: list[int] = []
    if organization_id:
        query += " AND patients.organization_id = ?"
        params.append(int(organization_id))
    if location_id:
        query += " AND patients.location_id = ?"
        params.append(int(location_id))
    query += " ORDER BY patients.display_name ASC"
    with get_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()

    return [
        {
            "id": row["id"],
            "organization_id": row["organization_id"],
            "location_id": row["location_id"],
            "display_name": row["display_name"],
            "patient_type": row["patient_type"],
            "specialty": row["specialty"],
            "owner_name": row["owner_name"],
            "phone": row["phone"],
            "last_visit": row["last_visit"] or "-",
            "document_number": row["document_number"],
            "birth_date": row["birth_date"],
            "sex": row["sex"],
            "insurance_name": row["insurance_name"],
            "species": row["species"],
            "breed": row["breed"],
            "weight_kg": row["weight_kg"],
            "vaccine_status": row["vaccine_status"],
            "organization_name": row["organization_name"] or "-",
            "site_name": row["site_name"] or "-",
            "site_city": row["site_city"] or "-",
        }
        for row in rows
    ]


def patient_options(organization_id: str = "", location_id: str = "") -> list[dict]:
    items = list_patients(organization_id=organization_id, location_id=location_id)
    return [
        {
            "id": item["id"],
            "label": (
                f"{item['display_name']} | {item['patient_type']} | {item['specialty']}"
                + (f" | {item['site_name']}" if item["site_name"] else "")
                + (f" | responsable {item['owner_name']}" if item["owner_name"] else "")
            ),
        }
        for item in items
    ]


def create_patient(payload: dict) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO patients (
                organization_id, location_id, display_name, patient_type, specialty,
                owner_name, phone, last_visit, document_number, birth_date, sex, insurance_name,
                species, breed, weight_kg, vaccine_status
            )
            VALUES (
                :organization_id, :location_id, :display_name, :patient_type, :specialty,
                :owner_name, :phone, :last_visit, :document_number, :birth_date, :sex, :insurance_name,
                :species, :breed, :weight_kg, :vaccine_status
            )
            """,
            payload,
        )
        connection.commit()


def delete_patient(patient_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM clinical_records WHERE patient_id = ?",
            (patient_id,),
        )
        connection.execute(
            "DELETE FROM patients WHERE id = ?",
            (patient_id,),
        )
        connection.commit()


def list_clinical_records(
    limit: int = 8,
    organization_id: str = "",
    location_id: str = "",
) -> list[dict]:
    query = """
        SELECT
            r.id,
            r.organization_id,
            r.location_id,
            r.encounter_date,
            r.specialty,
            r.reason,
            r.note,
            r.status,
            r.professional,
            r.diagnosis,
            r.treatment_plan,
            r.allergies,
            r.vital_signs,
            r.prescription,
            r.discharge_notes,
            r.service_performed,
            r.follow_up_date,
            r.next_vaccine_due,
            r.dental_chart,
            r.current_weight_kg,
            r.payment_amount,
            r.payment_method,
            p.display_name,
            p.patient_type,
            p.owner_name,
            p.document_number,
            p.birth_date,
            p.sex,
            p.insurance_name,
            p.species,
            p.breed,
            p.vaccine_status,
            organizations.name AS organization_name,
            locations.name AS site_name,
            locations.city AS site_city
        FROM clinical_records AS r
        INNER JOIN patients AS p ON p.id = r.patient_id
        LEFT JOIN organizations ON organizations.id = r.organization_id
        LEFT JOIN locations ON locations.id = r.location_id
        WHERE 1 = 1
    """
    params: list[int] = []
    if organization_id:
        query += " AND r.organization_id = ?"
        params.append(int(organization_id))
    if location_id:
        query += " AND r.location_id = ?"
        params.append(int(location_id))
    query += " ORDER BY r.encounter_date DESC, r.id DESC LIMIT ?"
    params.append(limit)
    with get_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()

    return [
        {
            "id": row["id"],
            "organization_id": row["organization_id"],
            "location_id": row["location_id"],
            "encounter_date": row["encounter_date"],
            "specialty": row["specialty"],
            "reason": row["reason"],
            "note": row["note"],
            "status": row["status"],
            "professional": row["professional"],
            "diagnosis": row["diagnosis"],
            "treatment_plan": row["treatment_plan"],
            "allergies": row["allergies"],
            "vital_signs": row["vital_signs"],
            "prescription": row["prescription"],
            "discharge_notes": row["discharge_notes"],
            "service_performed": row["service_performed"],
            "follow_up_date": row["follow_up_date"],
            "next_vaccine_due": row["next_vaccine_due"],
            "dental_chart": row["dental_chart"],
            "current_weight_kg": row["current_weight_kg"],
            "payment_amount": row["payment_amount"],
            "payment_method": row["payment_method"],
            "display_name": row["display_name"],
            "patient_type": row["patient_type"],
            "owner_name": row["owner_name"],
            "document_number": row["document_number"],
            "birth_date": row["birth_date"],
            "sex": row["sex"],
            "insurance_name": row["insurance_name"],
            "species": row["species"],
            "breed": row["breed"],
            "vaccine_status": row["vaccine_status"],
            "organization_name": row["organization_name"] or "-",
            "site_name": row["site_name"] or "-",
            "site_city": row["site_city"] or "-",
        }
        for row in rows
    ]


def create_clinical_record(payload: dict) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO clinical_records (
                patient_id, organization_id, location_id, encounter_date, specialty, reason,
                note, status, professional, diagnosis, treatment_plan, allergies, vital_signs,
                prescription, discharge_notes, service_performed, follow_up_date, next_vaccine_due,
                dental_chart, current_weight_kg, payment_amount, payment_method
            )
            VALUES (
                :patient_id, :organization_id, :location_id, :encounter_date, :specialty, :reason,
                :note, :status, :professional, :diagnosis, :treatment_plan, :allergies, :vital_signs,
                :prescription, :discharge_notes, :service_performed, :follow_up_date, :next_vaccine_due,
                :dental_chart, :current_weight_kg, :payment_amount, :payment_method
            )
            """,
            payload,
        )
        connection.execute(
            """
            UPDATE patients
            SET
                last_visit = :encounter_date,
                weight_kg = CASE
                    WHEN :current_weight_kg > 0 THEN :current_weight_kg
                    ELSE weight_kg
                END
            WHERE id = :patient_id
            """,
            payload,
        )
        connection.commit()


def update_clinical_record_status(record_id: int, status: str) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE clinical_records SET status = ? WHERE id = ?",
            (status.strip(), record_id),
        )
        connection.commit()


def delete_clinical_record(record_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM clinical_records WHERE id = ?",
            (record_id,),
        )
        connection.commit()


def clinical_summary(records: list[dict], patients: list[dict]) -> dict:
    follow_up = sum(1 for item in records if item["status"] == "Seguimiento")
    open_cases = sum(1 for item in records if item["status"] == "Abierta")
    return {
        "patients_total": len(patients),
        "records_total": len(records),
        "follow_up": follow_up,
        "open_cases": open_cases,
        "today": date.today().isoformat(),
    }


def daily_financial_summary(records: list[dict], selected_day: str) -> dict:
    specialties = [
        ("Odontologia", "Odontologia"),
        ("Veterinaria", "Veterinaria"),
        ("Consulta general", "Consulta general"),
    ]
    daily_records = [item for item in records if item["encounter_date"] == selected_day]
    specialties_summary = []
    payment_methods: dict[str, dict] = {}
    professionals: dict[str, dict] = {}

    for specialty_key, specialty_label in specialties:
        specialty_records = [
            item for item in daily_records if item["specialty"] == specialty_key
        ]
        total_collected = round(
            sum(float(item["payment_amount"] or 0) for item in specialty_records), 2
        )
        paying_patients = sum(
            1 for item in specialty_records if float(item["payment_amount"] or 0) > 0
        )
        specialties_summary.append(
            {
                "key": specialty_key,
                "label": specialty_label,
                "patients_total": len(specialty_records),
                "paying_patients": paying_patients,
                "total_collected": total_collected,
            }
        )

    for item in daily_records:
        payment_method = item["payment_method"] or "Sin definir"
        professional = item["professional"] or "Sin profesional"
        amount = round(float(item["payment_amount"] or 0), 2)
        payment_bucket = payment_methods.setdefault(
            payment_method,
            {"label": payment_method, "count": 0, "total_collected": 0.0},
        )
        payment_bucket["count"] += 1
        payment_bucket["total_collected"] = round(payment_bucket["total_collected"] + amount, 2)

        professional_bucket = professionals.setdefault(
            professional,
            {"label": professional, "count": 0, "total_collected": 0.0},
        )
        professional_bucket["count"] += 1
        professional_bucket["total_collected"] = round(professional_bucket["total_collected"] + amount, 2)

    return {
        "date": selected_day,
        "specialties": specialties_summary,
        "patients_total": sum(item["patients_total"] for item in specialties_summary),
        "paying_patients": sum(item["paying_patients"] for item in specialties_summary),
        "total_collected": round(
            sum(item["total_collected"] for item in specialties_summary), 2
        ),
        "by_payment_method": sorted(
            payment_methods.values(),
            key=lambda item: (-item["total_collected"], item["label"]),
        ),
        "by_professional": sorted(
            professionals.values(),
            key=lambda item: (-item["total_collected"], item["label"]),
        ),
    }


def veterinary_snapshot(
    patients: list[dict],
    records: list[dict],
) -> dict:
    vet_patients = [item for item in patients if item["specialty"] == "Veterinaria"]
    vet_records = [item for item in records if item["specialty"] == "Veterinaria"]
    latest_vet_record = next(
        iter(vet_records),
        None,
    )
    vaccines_pending = sum(
        1
        for item in vet_patients
        if (item.get("vaccine_status") or "").strip().lower()
        not in {"al dia", "al día", "vigente", "completo", "completa"}
    )
    return {
        "patients": vet_patients[:4],
        "patients_total": len(vet_patients),
        "vaccines_pending": vaccines_pending,
        "follow_ups": sum(1 for item in vet_records if item["status"] == "Seguimiento"),
        "latest_record": latest_vet_record,
    }


def dental_snapshot(records: list[dict]) -> dict:
    latest_dental_record = next(
        (item for item in records if item["specialty"] == "Odontologia"),
        None,
    )
    odontogram_cells = [
        {"tooth": "18", "state": "Sano", "tone": "green"},
        {"tooth": "17", "state": "Resina", "tone": "blue"},
        {"tooth": "16", "state": "Caries", "tone": "red"},
        {"tooth": "15", "state": "Sano", "tone": "green"},
        {"tooth": "14", "state": "Control", "tone": "yellow"},
        {"tooth": "13", "state": "Sano", "tone": "green"},
        {"tooth": "12", "state": "Sano", "tone": "green"},
        {"tooth": "11", "state": "Sano", "tone": "green"},
    ]
    return {
        "latest_record": latest_dental_record,
        "cells": odontogram_cells,
    }
