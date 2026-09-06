from __future__ import annotations

import csv
import json
import os
import re
import tempfile
import unicodedata
import urllib.parse
import urllib.request
from io import StringIO
from datetime import datetime

try:
    import pdfplumber
except ImportError:  # pragma: no cover - optional until veterinary sync is used
    pdfplumber = None

from app.core.database import get_connection


OFFICIAL_ODONTOLOGY_DATASET = "https://www.datos.gov.co/resource/c36g-9fc2.json"
OFFICIAL_ODONTOLOGY_SOURCE = "Registro Especial de Prestadores y Sedes de Servicios de Salud"
OFFICIAL_VETERINARY_DATASET = (
    "https://www.ica.gov.co/importacion-y-exportacion/otros-procedimientos/"
    "requisitos-para-importar-mascotas/listado-medicos-veterinarios/"
    "mv-y-mvz-registrados-junio-2023.aspx"
)
OFFICIAL_VETERINARY_SOURCE = "Listado de medicos veterinarios y MVZ inscritos ante el ICA"
ODONTOLOGY_KEYWORDS = (
    "ODONTO",
    "DENT",
    "ORTODON",
    "ENDODON",
    "PERIODON",
    "MAXILOFAC",
    "ORAL",
)
VETERINARY_KEYWORDS = (
    "VETER",
    "VET",
    "ANIMAL",
    "CANINO",
    "FELINO",
    "MASCOTA",
    "PET",
    "ZOOVET",
)


def list_organizations() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, name, country, timezone, contact_email, contact_phone
            FROM organizations
            ORDER BY name ASC
            """
        ).fetchall()

    return [
        {
            "id": row["id"],
            "name": row["name"],
            "country": row["country"],
            "timezone": row["timezone"],
            "contact_email": row["contact_email"],
            "contact_phone": row["contact_phone"],
        }
        for row in rows
    ]


def create_organization(payload: dict) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO organizations (name, country, timezone, contact_email, contact_phone)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                payload["name"],
                payload["country"],
                payload["timezone"],
                payload.get("contact_email", ""),
                payload.get("contact_phone", ""),
            ),
        )
        connection.commit()


def update_organization(organization_id: int, payload: dict) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE organizations
            SET name = ?, country = ?, timezone = ?, contact_email = ?, contact_phone = ?
            WHERE id = ?
            """,
            (
                payload["name"],
                payload["country"],
                payload["timezone"],
                payload.get("contact_email", ""),
                payload.get("contact_phone", ""),
                organization_id,
            ),
        )
        connection.commit()


def list_locations(organization_id: str = "", include_inactive: bool = False) -> list[dict]:
    query = """
        SELECT
            locations.id,
            locations.organization_id,
            locations.name,
            locations.city,
            locations.address,
            locations.sector,
            locations.phone,
            locations.opening_hours,
            locations.is_active,
            locations.catalog_kind,
            organizations.name AS organization_name
        FROM locations
        INNER JOIN organizations ON organizations.id = locations.organization_id
        WHERE 1 = 1
    """
    params: list[int] = []

    if not include_inactive:
        query += " AND locations.is_active = 1"

    if organization_id:
        query += " AND locations.organization_id = ?"
        params.append(int(organization_id))

    query += " ORDER BY organizations.name ASC, locations.name ASC"

    with get_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()

    return [
        {
            "id": row["id"],
            "organization_id": row["organization_id"],
            "name": row["name"],
            "city": row["city"],
            "address": row["address"],
            "sector": row["sector"],
            "phone": row["phone"],
            "opening_hours": row["opening_hours"],
            "organization_name": row["organization_name"],
            "catalog_kind": row["catalog_kind"],
            "is_active": bool(row["is_active"]),
        }
        for row in rows
    ]


def create_location(payload: dict) -> None:
    with get_connection() as connection:
        organization_row = connection.execute(
            "SELECT name FROM organizations WHERE id = ?",
            (payload["organization_id"],),
        ).fetchone()
        organization_name = organization_row["name"] if organization_row else ""
        search_text = build_location_search_text(
            organization_name=organization_name,
            location_name=payload["name"],
            city=payload["city"],
            address=" | ".join(part for part in (payload.get("sector", ""), payload["address"]) if part),
        )
        connection.execute(
            """
            INSERT INTO locations (organization_id, name, city, address, sector, phone, opening_hours, search_text, catalog_kind)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["organization_id"],
                payload["name"],
                payload["city"],
                payload["address"],
                payload.get("sector", ""),
                payload.get("phone", ""),
                payload.get("opening_hours", ""),
                search_text,
                payload.get("catalog_kind", "consulta-general"),
            ),
        )
        connection.commit()


def import_organization_location_catalog(csv_bytes: bytes) -> dict:
    text = csv_bytes.decode("utf-8-sig")
    reader = csv.DictReader(StringIO(text))
    required_fields = {
        "organization_name",
        "country",
        "timezone",
        "location_name",
        "city",
        "sector",
        "address",
        "is_active",
    }
    if not reader.fieldnames:
        raise ValueError("El archivo CSV no contiene encabezados.")
    missing = required_fields.difference({field.strip() for field in reader.fieldnames})
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Faltan columnas obligatorias en el CSV: {missing_list}.")

    rows = []
    for row in reader:
        rows.append(
            {
                "organization_name": row["organization_name"].strip(),
                "country": row["country"].strip() or "Colombia",
                "timezone": row["timezone"].strip() or "America/Bogota",
                "location_name": row["location_name"].strip(),
                "city": row["city"].strip(),
                "sector": row["sector"].strip(),
                "address": row["address"].strip(),
                "is_active": row["is_active"].strip(),
            }
        )
    return upsert_organization_location_rows(rows)


def upsert_organization_location_rows(rows: list[dict]) -> dict:
    organizations_created = 0
    organizations_updated = 0
    locations_created = 0
    locations_updated = 0

    with get_connection() as connection:
        organization_cache = {
            compact_spaces(row["name"]).lower(): row["id"]
            for row in connection.execute("SELECT id, name FROM organizations").fetchall()
        }
        location_cache = {
            (
                row["organization_id"],
                compact_spaces(row["name"]).lower(),
                compact_spaces(row["city"]).lower(),
                compact_spaces(row["address"]).lower(),
            ): row["id"]
            for row in connection.execute(
                "SELECT id, organization_id, name, city, address FROM locations"
            ).fetchall()
        }
        external_code_cache = {
            compact_spaces(row["external_code"]): row["id"]
            for row in connection.execute(
                "SELECT id, external_code FROM locations WHERE external_code <> ''"
            ).fetchall()
        }

        for row in rows:
            organization_name = row["organization_name"].strip()
            country = row["country"].strip() or "Colombia"
            timezone = row["timezone"].strip() or "America/Bogota"
            location_name = row["location_name"].strip()
            city = row["city"].strip()
            sector = row.get("sector", "").strip()
            address = row["address"].strip()
            catalog_kind = row.get("catalog_kind", "").strip() or "human"
            external_code = compact_spaces(str(row.get("external_code", "")).strip())
            raw_is_active = str(row.get("is_active", "1")).strip().lower()
            is_active = 0 if raw_is_active in {"0", "false", "no", "inactiva"} else 1

            if not organization_name or not location_name or not city:
                continue

            organization_key = compact_spaces(organization_name).lower()
            organization_id = organization_cache.get(organization_key)
            if organization_id:
                connection.execute(
                    """
                    UPDATE organizations
                    SET country = ?, timezone = ?
                    WHERE id = ?
                    """,
                    (country, timezone, organization_id),
                )
                organizations_updated += 1
            else:
                connection.execute(
                    """
                    INSERT INTO organizations (name, country, timezone)
                    VALUES (?, ?, ?)
                    """,
                    (organization_name, country, timezone),
                )
                organization_id = connection.execute(
                    "SELECT id FROM organizations WHERE LOWER(name) = LOWER(?)",
                    (organization_name,),
                ).fetchone()["id"]
                organization_cache[organization_key] = organization_id
                organizations_created += 1

            address_label = " | ".join(part for part in (sector, address) if part)
            search_text = build_location_search_text(
                organization_name=organization_name,
                location_name=location_name,
                city=city,
                address=address_label,
            )
            location_key = (
                organization_id,
                compact_spaces(location_name).lower(),
                compact_spaces(city).lower(),
                compact_spaces(address_label).lower(),
            )
            if external_code:
                location_id = external_code_cache.get(external_code)
            else:
                location_id = location_cache.get(location_key)
            if location_id:
                connection.execute(
                    """
                    UPDATE locations
                    SET city = ?, address = ?, is_active = ?, catalog_kind = ?, external_code = ?, search_text = ?
                    WHERE id = ?
                    """,
                    (city, address_label, is_active, catalog_kind, external_code, search_text, location_id),
                )
                location_cache[location_key] = location_id
                if external_code:
                    external_code_cache[external_code] = location_id
                locations_updated += 1
            else:
                connection.execute(
                    """
                    INSERT INTO locations (
                        organization_id, name, city, address, is_active, catalog_kind, external_code, search_text
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        organization_id,
                        location_name,
                        city,
                        address_label,
                        is_active,
                        catalog_kind,
                        external_code,
                        search_text,
                    ),
                )
                location_id = connection.execute(
                    """
                    SELECT id
                    FROM locations
                    WHERE organization_id = ? AND LOWER(name) = LOWER(?) AND LOWER(city) = LOWER(?) AND LOWER(address) = LOWER(?)
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (organization_id, location_name, city, address_label),
                ).fetchone()["id"]
                location_cache[location_key] = location_id
                if external_code:
                    external_code_cache[external_code] = location_id
                locations_created += 1

        connection.commit()

    return {
        "organizations_created": organizations_created,
        "organizations_updated": organizations_updated,
        "locations_created": locations_created,
        "locations_updated": locations_updated,
    }


def sync_official_odontology_catalog(limit: int | None = None) -> dict:
    where = " OR ".join(
        [
            f"upper(nombreprestador) like '%{keyword}%'"
            for keyword in ODONTOLOGY_KEYWORDS
        ]
        + [
            f"upper(nombresede) like '%{keyword}%'"
            for keyword in ODONTOLOGY_KEYWORDS
        ]
    )
    summary = sync_official_reps_catalog(where=where, limit=limit, catalog_kind="odontologia")
    summary["source"] = OFFICIAL_ODONTOLOGY_SOURCE
    summary["source_url"] = OFFICIAL_ODONTOLOGY_DATASET
    return summary


def sync_official_national_catalog(limit: int | None = None) -> dict:
    summary = sync_official_reps_catalog(where="", limit=limit, catalog_kind="consulta-general")
    summary["source"] = OFFICIAL_ODONTOLOGY_SOURCE
    summary["source_url"] = OFFICIAL_ODONTOLOGY_DATASET
    return summary


def sync_official_veterinary_catalog(limit: int | None = None) -> dict:
    rows = fetch_official_veterinary_rows(limit=limit)
    summary = upsert_organization_location_rows(rows)
    summary["rows_processed"] = len(rows)
    summary["source"] = OFFICIAL_VETERINARY_SOURCE
    summary["source_url"] = OFFICIAL_VETERINARY_DATASET
    return summary


def sync_official_reps_catalog(*, where: str = "", limit: int | None = None, catalog_kind: str = "human") -> dict:
    total = fetch_official_reps_count(where)
    if limit is not None:
        total = min(total, limit)

    collected: list[dict] = []
    batch_size = 1000
    offset = 0
    seen: set[tuple[str, str, str, str]] = set()

    while offset < total:
        remaining = total - offset
        rows = fetch_official_reps_batch(where=where, limit=min(batch_size, remaining), offset=offset)
        if not rows:
            break
        for row in rows:
            normalized = normalize_official_location_row(row, catalog_kind=catalog_kind)
            dedupe_key = (
                normalized["external_code"].lower()
                if normalized["external_code"]
                else "||".join(
                    [
                        normalized["organization_name"].lower(),
                        normalized["location_name"].lower(),
                        normalized["city"].lower(),
                        normalized["address"].lower(),
                    ]
                )
            )
            if (
                not normalized["organization_name"]
                or not normalized["location_name"]
                or not normalized["city"]
                or dedupe_key in seen
            ):
                continue
            seen.add(dedupe_key)
            collected.append(normalized)
        offset += len(rows)

    summary = upsert_organization_location_rows(collected)
    summary["rows_processed"] = len(collected)
    return summary


def normalize_official_location_row(row: dict, *, catalog_kind: str = "human") -> dict:
    organization_name = compact_spaces(row.get("nombreprestador", ""))
    location_name = compact_spaces(row.get("nombresede", "") or organization_name)
    municipality = title_case_text(row.get("municipiosededesc") or row.get("municipioprestadordesc") or "")
    department = title_case_text(row.get("departamentodededesc") or row.get("departamentoprestadordesc") or "")
    city_label = municipality
    if municipality and department:
        city_label = f"{municipality}, {department}"
    elif department:
        city_label = department

    address = compact_spaces(row.get("direcci_nsede") or row.get("direccionprestador") or "")
    return {
        "organization_name": organization_name,
        "country": "Colombia",
        "timezone": "America/Bogota",
        "location_name": location_name,
        "city": city_label,
        "sector": "",
        "address": address,
        "catalog_kind": catalog_kind,
        "external_code": compact_spaces(row.get("codigohabilitacionsede", "")),
        "is_active": "1",
    }


def fetch_official_veterinary_rows(limit: int | None = None) -> list[dict]:
    if pdfplumber is None:
        raise RuntimeError(
            "pdfplumber no esta instalado. Ejecuta `pip install -e .` para habilitar la sincronizacion veterinaria."
        )
    with urllib.request.urlopen(OFFICIAL_VETERINARY_DATASET, timeout=120) as response:
        pdf_bytes = response.read()

    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            temp_file.write(pdf_bytes)
            temp_path = temp_file.name

        rows: list[dict] = []
        seen: set[str] = set()
        current_department = ""
        current_city = ""
        known_city_lookup = load_known_city_lookup()

        with pdfplumber.open(temp_path) as pdf:
            for page in pdf.pages:
                table = page.extract_table()
                if not table:
                    continue
                for raw_row in table:
                    if not raw_row:
                        continue

                    columns = list(raw_row) + [""] * max(0, 7 - len(raw_row))
                    department = clean_veterinary_table_cell(columns[0])
                    city = clean_veterinary_table_cell(columns[1])
                    clinic = clean_veterinary_table_cell(columns[2])
                    professional_name = clean_veterinary_table_cell(columns[3])
                    professional_last_name = clean_veterinary_table_cell(columns[4])

                    if department.upper() == "DEPARTAMENTO":
                        continue

                    if department:
                        current_department = title_case_text(department)
                    if city and city.upper() != "CIUDAD":
                        current_city = normalize_known_city_name(city, known_city_lookup)

                    if not clinic:
                        continue
                    if is_probable_veterinary_person_entry(
                        clinic,
                        professional_name=professional_name,
                        professional_last_name=professional_last_name,
                    ):
                        continue

                    city_label = current_city
                    if current_city == "Bogotá" and current_department == "Cundinamarca/Capital":
                        city_label = "Bogotá, Bogotá D.C"
                    elif current_city and current_department:
                        city_label = f"{current_city}, {current_department}"
                    elif current_department:
                        city_label = current_department

                    if not city_label:
                        continue

                    external_code = build_veterinary_external_code(
                        clinic=clinic,
                        city=city_label,
                    )
                    if external_code in seen:
                        continue
                    seen.add(external_code)

                    rows.append(
                        {
                            "organization_name": clinic,
                            "country": "Colombia",
                            "timezone": "America/Bogota",
                            "location_name": clinic,
                            "city": city_label,
                            "sector": "",
                            "address": "",
                            "catalog_kind": "veterinaria",
                            "external_code": external_code,
                            "is_active": "1",
                        }
                    )
                    if limit is not None and len(rows) >= limit:
                        return rows
        return rows
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def fetch_official_reps_count(where: str = "") -> int:
    query = {"$select": "count(*)"}
    if where:
        query["$where"] = where
    params = urllib.parse.urlencode(query)
    with urllib.request.urlopen(f"{OFFICIAL_ODONTOLOGY_DATASET}?{params}", timeout=90) as response:
        payload = json.load(response)
    return int(payload[0]["count"])


def fetch_official_reps_batch(*, where: str = "", limit: int, offset: int) -> list[dict]:
    query = {
        "$select": ",".join(
            [
                    "nombreprestador",
                    "codigohabilitacionsede",
                    "nombresede",
                    "municipiosededesc",
                    "departamentodededesc",
                "direcci_nsede",
                "municipioprestadordesc",
                "departamentoprestadordesc",
                "direccionprestador",
            ]
        ),
        "$order": "nombreprestador ASC, nombresede ASC",
        "$limit": str(limit),
        "$offset": str(offset),
    }
    if where:
        query["$where"] = where
    params = urllib.parse.urlencode(query)
    with urllib.request.urlopen(f"{OFFICIAL_ODONTOLOGY_DATASET}?{params}", timeout=90) as response:
        return json.load(response)


def get_location_by_id(location_id: str, include_inactive: bool = False) -> dict | None:
    if not location_id.strip():
        return None

    query = """
        SELECT
            locations.id,
            locations.organization_id,
            locations.name,
            locations.city,
            locations.address,
            locations.is_active,
            locations.catalog_kind,
            organizations.name AS organization_name
        FROM locations
        INNER JOIN organizations ON organizations.id = locations.organization_id
        WHERE locations.id = ?
    """
    params: list[object] = [int(location_id)]
    if not include_inactive:
        query += " AND locations.is_active = 1"

    with get_connection() as connection:
        row = connection.execute(query, tuple(params)).fetchone()

    if not row:
        return None
    return {
        "id": row["id"],
        "organization_id": row["organization_id"],
        "name": row["name"],
        "city": row["city"],
        "address": row["address"],
        "organization_name": row["organization_name"],
        "catalog_kind": row["catalog_kind"],
        "is_active": bool(row["is_active"]),
        "label": build_location_search_label(
            {
                "organization_name": row["organization_name"],
                "name": row["name"],
                "city": row["city"],
                "address": row["address"],
                "catalog_kind": row["catalog_kind"],
            },
            duplicate_city_count_for_location(
                organization_name=row["organization_name"],
                city=row["city"],
            ),
        ),
    }


def search_location_candidates(query: str, limit: int = 12, intent: str = "") -> list[dict]:
    normalized_query = normalize_search_text(query)
    if not normalized_query:
        return []

    tokens = [token for token in normalized_query.split(" ") if token]
    if not tokens:
        return []

    search_sql = """
        SELECT
            locations.id,
            locations.organization_id,
            locations.name,
            locations.city,
            locations.address,
            locations.is_active,
            locations.catalog_kind,
            organizations.name AS organization_name,
            COUNT(*) OVER (
                PARTITION BY LOWER(organizations.name), LOWER(locations.city)
            ) AS duplicate_city_count
        FROM locations
        INNER JOIN organizations ON organizations.id = locations.organization_id
        WHERE locations.is_active = 1
    """
    params: list[object] = []
    catalog_clause, catalog_params = catalog_filter_for_intent(intent)
    if catalog_clause:
        search_sql += f"\n {catalog_clause}\n"
        params.extend(catalog_params)
    token_clauses = []
    for token in tokens:
        token_clauses.append(
            """
            locations.search_text LIKE ?
            """
        )
        params.append(f"%{token}%")

    if token_clauses:
        search_sql += "\n AND (\n"
        search_sql += " AND ".join(token_clauses)
        search_sql += "\n )\n"

    primary_token = tokens[0]
    search_sql += """
        ORDER BY
            CASE
                WHEN LOWER(locations.name) LIKE ? THEN 0
                WHEN LOWER(organizations.name) LIKE ? THEN 1
                WHEN LOWER(locations.city) LIKE ? THEN 2
                ELSE 3
            END,
            organizations.name ASC,
            locations.city ASC,
            locations.name ASC
        LIMIT ?
    """
    params.extend(
        [
            f"%{primary_token}%",
            f"%{primary_token}%",
            f"%{primary_token}%",
            max(limit * 40, 400),
        ]
    )

    with get_connection() as connection:
        rows = connection.execute(search_sql, tuple(params)).fetchall()

    results = []
    for row in rows:
        candidate = {
            "id": row["id"],
            "organization_id": row["organization_id"],
            "name": row["name"],
            "city": row["city"],
            "address": row["address"],
            "organization_name": row["organization_name"],
            "catalog_kind": row["catalog_kind"],
            "duplicate_city_count": row["duplicate_city_count"],
        }
        if not candidate_matches_intent(candidate, intent):
            continue
        label = build_location_search_label(candidate, row["duplicate_city_count"])
        haystack = normalize_search_text(
            f"{row['organization_name']} {row['name']} {row['city']} {row['address']} {label}"
        )
        if not all(token in haystack for token in tokens):
            continue
        score = candidate_match_score(candidate, label, haystack, normalized_query)
        results.append(
            {
                "id": row["id"],
                "organization_id": row["organization_id"],
                "name": row["name"],
                "city": row["city"],
                "address": row["address"],
                "organization_name": row["organization_name"],
                "label": label,
                "_score": score,
            }
        )

    results.sort(key=lambda item: (-item["_score"], item["label"]))
    return [{key: value for key, value in item.items() if key != "_score"} for item in results[:limit]]


def catalog_filter_for_intent(intent: str) -> tuple[str, list[str]]:
    normalized_intent = compact_spaces(intent).lower()
    if normalized_intent == "odontologia":
        return "AND locations.catalog_kind = ?", ["odontologia"]
    if normalized_intent == "consulta-general":
        return "AND locations.catalog_kind = ?", ["consulta-general"]
    if normalized_intent == "veterinaria":
        return "AND locations.catalog_kind = ?", ["veterinaria"]
    return "", []


def candidate_matches_intent(candidate: dict, intent: str) -> bool:
    normalized_intent = compact_spaces(intent).lower()
    if normalized_intent not in {"odontologia", "consulta-general", "veterinaria"}:
        return True

    catalog_kind = compact_spaces(candidate.get("catalog_kind", "")).lower()
    if normalized_intent == "odontologia":
        if catalog_kind in {"odontologia", "dental"}:
            return True
        if catalog_kind in {"consulta-general", "human"}:
            return False
    if normalized_intent == "consulta-general":
        if catalog_kind in {"consulta-general", "human"}:
            return True
        if catalog_kind in {"odontologia", "veterinaria"}:
            return False
    if normalized_intent == "veterinaria":
        return catalog_kind == "veterinaria"

    haystack = normalize_search_text(
        f"{candidate['organization_name']} {candidate['name']} {candidate['city']} {candidate['address']}"
    )
    tokens = [token.upper() for token in re.split(r"[^a-z0-9áéíóúñ]+", haystack) if token]
    if normalized_intent == "odontologia":
        return any(any(token.startswith(keyword) for token in tokens) for keyword in ODONTOLOGY_KEYWORDS)
    if normalized_intent == "veterinaria":
        return any(any(token.startswith(keyword) for token in tokens) for keyword in VETERINARY_KEYWORDS)
    return not any(any(token.startswith(keyword) for token in tokens) for keyword in VETERINARY_KEYWORDS)


def normalize_search_text(value: str) -> str:
    normalized = compact_spaces(value).lower()
    normalized = unicodedata.normalize("NFD", normalized)
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", normalized)


def build_location_search_text(*, organization_name: str, location_name: str, city: str, address: str) -> str:
    return normalize_search_text(
        " ".join(part for part in (organization_name, location_name, city, address) if part)
    )


def candidate_match_score(candidate: dict, label: str, haystack: str, query: str) -> int:
    organization_name = normalize_search_text(candidate["organization_name"])
    primary_name = normalize_search_text(build_location_primary_name(candidate))
    city = normalize_search_text(candidate["city"])
    name = normalize_search_text(candidate["name"])
    label_normalized = normalize_search_text(label)
    score = 0
    if label_normalized == query:
        score += 120
    if primary_name == query:
        score += 110
    if primary_name.startswith(query):
        score += 90
    if organization_name.startswith(query):
        score += 80
    if name.startswith(query):
        score += 70
    if city.startswith(query):
        score += 50
    if query in organization_name:
        score += 40
    if query in name:
        score += 30
    if query in haystack:
        score += 10
    return score


def duplicate_city_count_for_location(*, organization_name: str, city: str) -> int:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM locations
            INNER JOIN organizations ON organizations.id = locations.organization_id
            WHERE locations.is_active = 1
              AND LOWER(organizations.name) = LOWER(?)
              AND LOWER(locations.city) = LOWER(?)
            """,
            (organization_name, city),
        ).fetchone()
    return int(row["total"]) if row else 0


def build_location_search_label(location: dict, duplicate_city_count: int) -> str:
    primary_name = build_location_primary_name(location)
    location_name = compact_spaces(location.get("name", ""))
    organization_name = compact_spaces(location.get("organization_name", ""))
    if duplicate_city_count > 1 and location_name and normalize_search_text(location_name) != normalize_search_text(primary_name):
        primary_name = location_name

    parts = [primary_name]
    if location["city"]:
        parts.append(location["city"])
    if duplicate_city_count > 1:
        disambiguation = build_location_disambiguation_label(location["address"])
        if disambiguation:
            parts.append(disambiguation)
    return " | ".join(parts)


def build_location_primary_name(location: dict) -> str:
    organization_name = compact_spaces(location.get("organization_name", ""))
    location_name = compact_spaces(location.get("name", ""))
    if not location_name:
        return organization_name

    normalized_org = normalize_search_text(organization_name)
    normalized_location = normalize_search_text(location_name)

    if normalized_location == normalized_org:
        return location_name
    if normalized_org and normalized_location in normalized_org:
        return location_name
    if normalized_location and normalized_org in normalized_location:
        return location_name
    if normalized_location.startswith(normalized_org) and len(normalized_location) > len(normalized_org):
        return location_name
    if has_specific_branch_name(location_name):
        return location_name
    return location_name if len(location_name) >= max(6, int(len(organization_name) * 0.45)) else organization_name


def has_specific_branch_name(location_name: str) -> bool:
    normalized = normalize_search_text(location_name)
    branch_keywords = (
        "sede",
        "centro",
        "norte",
        "sur",
        "oriente",
        "occidente",
        "poblado",
        "laureles",
        "salitre",
        "unicentro",
        "fabricato",
        "mayorca",
        "punto",
        "local",
        "consultorio",
        "ips",
        "clinica",
    )
    return any(keyword in normalized for keyword in branch_keywords)


def build_location_disambiguation_label(address: str) -> str:
    raw_address = compact_spaces(address)
    if not raw_address:
        return ""
    prioritized = [part.strip() for part in raw_address.split("|") if part.strip()]
    return prioritized[0] if prioritized else raw_address


def clean_veterinary_table_cell(value: str | None) -> str:
    normalized = compact_spaces(value or "")
    if not normalized:
        return ""
    if re.fullmatch(r"(?:[A-ZÁÉÍÓÚÑ]\s+){2,}[A-ZÁÉÍÓÚÑ]", normalized):
        normalized = normalized.replace(" ", "")
    return normalized


def is_probable_veterinary_person_entry(
    clinic: str,
    *,
    professional_name: str = "",
    professional_last_name: str = "",
) -> bool:
    clinic_normalized = normalize_search_text(clinic)
    professional_full_name = normalize_search_text(f"{professional_name} {professional_last_name}")
    if not clinic_normalized:
        return True
    if clinic_normalized == professional_full_name:
        return True

    business_keywords = (
        "veter",
        "clinica",
        "consultorio",
        "centro",
        "hospital",
        "pet",
        "animal",
        "mascota",
        "zoo",
        "spa",
        "universidad",
        "servicio",
        "mundo",
    )
    if any(keyword in clinic_normalized for keyword in business_keywords):
        return False

    clinic_tokens = clinic.split()
    return 2 <= len(clinic_tokens) <= 6


def build_veterinary_external_code(*, clinic: str, city: str) -> str:
    clinic_key = normalize_search_text(clinic).replace(" ", "-")
    city_key = normalize_search_text(city).replace(" ", "-")
    return f"ICA-VET::{city_key}::{clinic_key}"


def load_known_city_lookup() -> dict[str, str]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT city
            FROM locations
            WHERE city <> ''
            """
        ).fetchall()

    lookup: dict[str, str] = {}
    for row in rows:
        city_value = compact_spaces(row["city"])
        municipality = city_value.split(",", 1)[0].strip()
        if not municipality:
            continue
        primary_key = normalize_city_lookup_key(municipality)
        if primary_key:
            lookup[primary_key] = municipality
    return lookup


def normalize_known_city_name(raw_city: str, lookup: dict[str, str]) -> str:
    city_value = clean_veterinary_table_cell(raw_city)
    if not city_value:
        return ""
    compressed_key = normalize_city_lookup_key(city_value)
    if compressed_key in lookup:
        return lookup[compressed_key]
    for key, city_name in lookup.items():
        if compressed_key.startswith(key) or key.startswith(compressed_key):
            if abs(len(compressed_key) - len(key)) <= 4:
                return city_name
    return title_case_text("".join(city_value.split()) if should_join_fragmented_city(city_value) else city_value)


def should_join_fragmented_city(city_value: str) -> bool:
    tokens = city_value.split()
    if len(tokens) < 3:
        return False
    average_length = sum(len(token) for token in tokens) / len(tokens)
    return average_length <= 2.2


def normalize_city_lookup_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", normalize_search_text(value))


def compact_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def title_case_text(value: str) -> str:
    normalized = compact_spaces(value)
    if not normalized:
        return ""
    return normalized.title()


def update_location(location_id: int, payload: dict) -> None:
    with get_connection() as connection:
        organization_row = connection.execute(
            "SELECT name FROM organizations WHERE id = ?",
            (payload["organization_id"],),
        ).fetchone()
        organization_name = organization_row["name"] if organization_row else ""
        search_text = build_location_search_text(
            organization_name=organization_name,
            location_name=payload["name"],
            city=payload["city"],
            address=" | ".join(part for part in (payload.get("sector", ""), payload["address"]) if part),
        )
        connection.execute(
            """
            UPDATE locations
            SET organization_id = ?, name = ?, city = ?, address = ?, sector = ?, phone = ?, opening_hours = ?, search_text = ?
            WHERE id = ?
            """,
            (
                payload["organization_id"],
                payload["name"],
                payload["city"],
                payload["address"],
                payload.get("sector", ""),
                payload.get("phone", ""),
                payload.get("opening_hours", ""),
                search_text,
                location_id,
            ),
        )
        connection.commit()


def get_app_settings() -> dict[str, str]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT key, value
            FROM app_settings
            ORDER BY key ASC
            """
        ).fetchall()
    return {row["key"]: row["value"] for row in rows}


def save_app_settings(payload: dict[str, str]) -> None:
    with get_connection() as connection:
        for key, value in payload.items():
            connection.execute(
                """
                INSERT INTO app_settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value.strip()),
            )
        connection.commit()


def set_location_active(location_id: int, is_active: bool) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE locations SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, location_id),
        )
        connection.commit()


def resolve_scope(organization_id: str = "", location_id: str = "") -> dict:
    organizations = list_organizations()
    normalized_org = organization_id.strip()
    normalized_location = location_id.strip()

    available_locations = list_locations(normalized_org)
    selected_org = next(
        (item for item in organizations if str(item["id"]) == normalized_org),
        None,
    )
    selected_location = next(
        (item for item in available_locations if str(item["id"]) == normalized_location),
        None,
    )

    return {
        "organization_id": normalized_org if selected_org else "",
        "location_id": normalized_location if selected_location else "",
        "selected_organization": selected_org,
        "selected_location": selected_location,
        "organizations": organizations,
        "locations": available_locations,
        "scope_label": build_scope_label(selected_org, selected_location),
    }


def build_scope_label(organization: dict | None, location: dict | None) -> str:
    if organization and location:
        return f"{organization['name']} | {location['name']}"
    if organization:
        return organization["name"]
    return "Toda la red"


def entry_flows() -> list[dict]:
    return [
        {
            "id": "odontologia",
            "title": "Odontologia",
            "description": "Agenda odontologica, odontograma y procedimientos. Inventario y bodega siguen disponibles como modulo comun.",
            "target": "/login?intent=odontologia",
        },
        {
            "id": "veterinaria",
            "title": "Veterinaria",
            "description": "Mascotas, propietarios, vacunacion y seguimiento. Inventario y bodega siguen disponibles para toda la operacion.",
            "target": "/login?intent=veterinaria",
        },
        {
            "id": "consulta-general",
            "title": "Consulta general",
            "description": "Historia flexible, triage, controles y seguimiento clinico. Inventario y bodega quedan como soporte transversal.",
            "target": "/login?intent=consulta-general",
        },
    ]


def module_path_for_intent(intent: str, permissions: dict) -> str:
    normalized = (intent or "").strip().lower()
    if normalized in {"odontologia", "veterinaria", "consulta-general"} and permissions["view_clinical"]:
        return "/clinica"
    if normalized in {"agenda", "triaje"} and permissions["view_agenda"]:
        return "/agenda"
    if permissions["manage_admin"]:
        return "/admin"
    if permissions["view_agenda"]:
        return "/agenda"
    if permissions["view_inventory"]:
        return "/inventario"
    if permissions["view_clinical"]:
        return "/clinica"
    return "/"


def log_audit_event(
    *,
    user_id: int | None,
    organization_id: int | None,
    location_id: int | None,
    action: str,
    entity_type: str,
    entity_label: str,
    detail: str = "",
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO audit_events (
                user_id, organization_id, location_id, action, entity_type,
                entity_label, detail
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                organization_id,
                location_id,
                action,
                entity_type,
                entity_label,
                detail.strip(),
            ),
        )
        connection.commit()


def list_recent_activity(
    limit: int = 8,
    organization_id: str = "",
    location_id: str = "",
) -> list[dict]:
    query = """
        SELECT
            audit_events.id,
            audit_events.action,
            audit_events.entity_type,
            audit_events.entity_label,
            audit_events.detail,
            audit_events.created_at,
            users.full_name AS user_name,
            organizations.name AS organization_name,
            locations.name AS location_name
        FROM audit_events
        LEFT JOIN users ON users.id = audit_events.user_id
        LEFT JOIN organizations ON organizations.id = audit_events.organization_id
        LEFT JOIN locations ON locations.id = audit_events.location_id
        WHERE 1 = 1
    """
    params: list[int] = []

    if organization_id:
        query += " AND audit_events.organization_id = ?"
        params.append(int(organization_id))
    if location_id:
        query += " AND audit_events.location_id = ?"
        params.append(int(location_id))

    query += " ORDER BY audit_events.created_at DESC, audit_events.id DESC LIMIT ?"
    params.append(limit)

    with get_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()

    return [
        {
            "action": row["action"],
            "entity_type": row["entity_type"],
            "entity_label": row["entity_label"],
            "detail": row["detail"],
            "created_at": format_timestamp(row["created_at"]),
            "user_name": row["user_name"] or "Sistema",
            "organization_name": row["organization_name"] or "-",
            "location_name": row["location_name"] or "-",
        }
        for row in rows
    ]


def format_timestamp(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value).replace("T", " ")[:16]
