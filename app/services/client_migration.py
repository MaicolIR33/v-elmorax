from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from app.core.database import get_connection


FILES = {
    "patients.csv": ("patients", ("external_id", "name", "owner_name")),
    "inventory.csv": ("inventory", ("external_id", "name", "lot", "quantity", "expiry_date")),
    "appointments.csv": ("appointments", ("external_id", "date", "time", "patient_name", "service")),
}


def migrate_client_bundle(bundle_dir: Path, apply: bool = False) -> dict:
    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.exists():
        raise ValueError("Falta manifest.json.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    organization_id = int(manifest.get("organization_id") or 0)
    location_id = int(manifest.get("location_id") or 0)
    source = str(manifest.get("source_system") or "").strip()
    if not organization_id or not location_id or not source:
        raise ValueError("El manifiesto requiere organization_id, location_id y source_system.")

    rows: dict[str, list[dict]] = {}
    errors: list[str] = []
    for filename, (kind, required) in FILES.items():
        path = bundle_dir / filename
        if path.exists():
            with path.open(encoding="utf-8-sig", newline="") as source_file:
                rows[kind] = list(csv.DictReader(source_file))
        else:
            rows[kind] = []
        for number, row in enumerate(rows[kind], start=2):
            missing = [field for field in required if not str(row.get(field, "")).strip()]
            if missing:
                errors.append(f"{filename}:{number} campos vacíos: {', '.join(missing)}")
            _validate_row(kind, row, filename, number, errors)

    with get_connection() as connection:
        scope = connection.execute(
            "SELECT id FROM locations WHERE id = ? AND organization_id = ?",
            (location_id, organization_id),
        ).fetchone()
        if scope is None:
            errors.append("La sede no pertenece a la organización indicada.")
        duplicates = _count_duplicates(connection, organization_id, source, rows)
        if errors or not apply:
            return {"mode": "validation", "valid": not errors, "errors": errors, "rows": {k: len(v) for k, v in rows.items()}, "duplicates": duplicates, "imported": {}}

        imported = {"patients": 0, "inventory": 0, "appointments": 0}
        try:
            for row in rows["patients"]:
                if _exists(connection, "patients", organization_id, source, row["external_id"]): continue
                connection.execute(
                    """INSERT INTO patients (organization_id,location_id,display_name,patient_type,specialty,owner_name,phone,birth_date,sex,species,breed,weight_kg,vaccine_status,source_system,external_id)
                       VALUES (?,?,?,'Animal','Veterinaria',?,?,?,?,?,?,?,?,?,?)""",
                    (organization_id, location_id, row["name"].strip(), row.get("owner_name", "").strip(), row.get("phone", "").strip(), row.get("birth_date", "").strip(), row.get("sex", "").strip(), row.get("species", "").strip(), row.get("breed", "").strip(), float(row.get("weight_kg") or 0), row.get("vaccine_status", "").strip(), source, row["external_id"].strip()),
                )
                imported["patients"] += 1
            for row in rows["inventory"]:
                if _exists(connection, "inventory_items", organization_id, source, row["external_id"]): continue
                connection.execute(
                    """INSERT INTO inventory_items (organization_id,location_id,name,category,brand,regulatory_agency,regulatory_code,supplier,lot,quantity,min_stock,location,expiry_date,source_system,external_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (organization_id, location_id, row["name"].strip(), row.get("category", "Veterinaria").strip(), row.get("brand", "").strip(), row.get("regulatory_agency", "ICA").strip(), row.get("regulatory_code", "").strip(), row.get("supplier", "").strip(), row["lot"].strip(), float(row["quantity"]), float(row.get("min_stock") or 0), row.get("storage_location", "Bodega").strip(), row["expiry_date"].strip(), source, row["external_id"].strip()),
                )
                imported["inventory"] += 1
            for row in rows["appointments"]:
                if _exists(connection, "appointments", organization_id, source, row["external_id"]): continue
                connection.execute(
                    """INSERT INTO appointments (organization_id,location_id,appointment_date,appointment_time,patient_name,service,channel,status,specialty,note,priority,source_system,external_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (organization_id, location_id, row["date"].strip(), row["time"].strip(), row["patient_name"].strip(), row["service"].strip(), row.get("channel", "Presencial").strip(), row.get("status", "Confirmada").strip(), "Veterinaria", row.get("note", "").strip(), row.get("priority", "Normal").strip(), source, row["external_id"].strip()),
                )
                imported["appointments"] += 1
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {"mode": "import", "valid": True, "errors": [], "rows": {k: len(v) for k, v in rows.items()}, "duplicates": duplicates, "imported": imported}


def _validate_row(kind: str, row: dict, filename: str, number: int, errors: list[str]) -> None:
    try:
        if kind == "inventory":
            if float(row.get("quantity", "")) < 0: raise ValueError
            date.fromisoformat(row.get("expiry_date", ""))
        elif kind == "appointments":
            date.fromisoformat(row.get("date", ""))
            hours, minutes = map(int, row.get("time", "").split(":"))
            if not (0 <= hours <= 23 and 0 <= minutes <= 59): raise ValueError
        elif row.get("birth_date"):
            date.fromisoformat(row["birth_date"])
        if row.get("weight_kg") and float(row["weight_kg"]) < 0: raise ValueError
    except (ValueError, TypeError):
        errors.append(f"{filename}:{number} contiene una fecha, hora o cantidad inválida.")


def _exists(connection, table: str, organization_id: int, source: str, external_id: str) -> bool:
    return connection.execute(f"SELECT id FROM {table} WHERE organization_id=? AND source_system=? AND external_id=?", (organization_id, source, external_id.strip())).fetchone() is not None


def _count_duplicates(connection, organization_id: int, source: str, rows: dict) -> dict:
    table_map = {"patients": "patients", "inventory": "inventory_items", "appointments": "appointments"}
    return {kind: sum(_exists(connection, table, organization_id, source, row.get("external_id", "")) for row in data) for kind, data in rows.items() for table in [table_map[kind]]}
