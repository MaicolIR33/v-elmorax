from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path

from app.core.config import get_settings

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional until PostgreSQL is configured
    psycopg = None
    dict_row = None


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DEMO_PASSWORD_HASH = "80cc05131542267f674881256d5e1ae0fa651b06c82fe72f0e995e52a16d51f2"


class CursorAdapter:
    def __init__(self, cursor, dialect: str):
        self.cursor = cursor
        self.dialect = dialect

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    @property
    def rowcount(self) -> int:
        return self.cursor.rowcount


class DatabaseConnection:
    def __init__(self, raw_connection, dialect: str):
        self.raw_connection = raw_connection
        self.dialect = dialect

    def __enter__(self) -> DatabaseConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            self.rollback()
        self.raw_connection.close()

    def execute(self, sql: str, params=None) -> CursorAdapter:
        statement, normalized = normalize_query(sql, params, self.dialect)
        cursor = self._cursor()
        if normalized is None:
            cursor.execute(statement)
        else:
            cursor.execute(statement, normalized)
        return CursorAdapter(cursor, self.dialect)

    def executemany(self, sql: str, seq_of_params) -> None:
        statement, _ = normalize_query(sql, None, self.dialect)
        cursor = self._cursor()
        normalized_params = [
            normalize_query(sql, params, self.dialect)[1] for params in seq_of_params
        ]
        cursor.executemany(statement, normalized_params)

    def executescript(self, sql: str) -> None:
        if self.dialect == "sqlite":
            self.raw_connection.executescript(sql)
            return
        for statement in split_sql_script(sql):
            self.execute(statement)

    def commit(self) -> None:
        self.raw_connection.commit()

    def rollback(self) -> None:
        self.raw_connection.rollback()

    def _cursor(self):
        if self.dialect == "sqlite":
            return self.raw_connection.cursor()
        return self.raw_connection.cursor(row_factory=dict_row)


def get_database_url() -> str:
    return get_settings().database_url


def get_database_dialect() -> str:
    return "postgres" if get_database_url().startswith(("postgres://", "postgresql://")) else "sqlite"


def sqlite_db_path() -> Path:
    raw = get_database_url()
    relative = raw.replace("sqlite:///", "", 1)
    path = Path(relative)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def get_connection() -> DatabaseConnection:
    dialect = get_database_dialect()
    if dialect == "sqlite":
        db_path = sqlite_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return DatabaseConnection(connection, dialect="sqlite")

    if psycopg is None:
        raise RuntimeError(
            "DATABASE_URL apunta a PostgreSQL, pero psycopg no esta instalado. "
            "Ejecuta `pip install psycopg[binary]`."
        )

    connection = psycopg.connect(get_database_url(), autocommit=False)
    return DatabaseConnection(connection, dialect="postgres")


def init_db() -> None:
    with get_connection() as connection:
        connection.executescript(build_schema_sql(connection.dialect))
        ensure_column(connection, "organizations", "contact_email", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "organizations", "contact_phone", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "organizations", "plan_code", "TEXT NOT NULL DEFAULT 'essential'")
        ensure_column(connection, "organizations", "plan_status", "TEXT NOT NULL DEFAULT 'active'")
        ensure_column(connection, "organizations", "billing_cycle", "TEXT NOT NULL DEFAULT 'monthly'")
        ensure_column(connection, "users", "organization_id", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(connection, "users", "location_id", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(connection, "users", "specialty", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "users", "working_days", "TEXT NOT NULL DEFAULT '0,1,2,3,4,5'")
        ensure_column(connection, "users", "work_start", "TEXT NOT NULL DEFAULT '08:00'")
        ensure_column(connection, "users", "work_end", "TEXT NOT NULL DEFAULT '18:00'")
        ensure_column(connection, "users", "break_start", "TEXT NOT NULL DEFAULT '12:00'")
        ensure_column(connection, "users", "break_end", "TEXT NOT NULL DEFAULT '13:00'")
        ensure_column(connection, "users", "unavailable_dates", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "users", "failed_login_attempts", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(connection, "users", "locked_until", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "users", "must_change_password", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(connection, "users", "password_changed_at", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "users", "permission_overrides", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "alerts", "escalation_minutes", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(connection, "inventory_items", "organization_id", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(connection, "inventory_items", "location_id", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(connection, "inventory_items", "barcode", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "inventory_items", "supplier", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "inventory_items", "unit_cost", "REAL NOT NULL DEFAULT 0")
        ensure_column(connection, "inventory_items", "sale_price", "REAL NOT NULL DEFAULT 0")
        ensure_column(connection, "inventory_items", "storage_condition", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "inventory_items", "requires_cold_chain", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(connection, "inventory_items", "last_counted_at", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "inventory_items", "product_id", "INTEGER")
        ensure_column(connection, "inventory_items", "item_type", "TEXT NOT NULL DEFAULT 'Medicamento'")
        ensure_column(connection, "inventory_items", "unit_measure", "TEXT NOT NULL DEFAULT 'unidades'")
        ensure_column(connection, "inventory_items", "lot_status", "TEXT NOT NULL DEFAULT 'active'")
        ensure_column(connection, "inventory_items", "retired_at", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "inventory_items", "retirement_reason", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "inventory_items", "cold_chain_incident", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(connection, "inventory_items", "manufacturer", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "inventory_items", "received_date", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "inventory_items", "document_number", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "inventory_items", "presentation", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "inventory_items", "concentration", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "inventory_items", "serial_number", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "inventory_items", "reception_temperature_c", "REAL")
        ensure_column(connection, "inventory_items", "reception_note", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "inventory_items", "received_by_user_id", "INTEGER")
        ensure_column(connection, "inventory_items", "is_test", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(connection, "inventory_items", "is_quarantined", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(connection, "inventory_items", "quarantine_reason", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "inventory_items", "replenishment_request_id", "INTEGER")
        ensure_column(connection, "inventory_items", "source_system", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "inventory_items", "external_id", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "inventory_products", "manufacturer", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "inventory_products", "presentation", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "inventory_products", "concentration", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "inventory_movements", "organization_id", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(connection, "inventory_movements", "location_id", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(connection, "inventory_movements", "user_id", "INTEGER")
        ensure_column(connection, "inventory_movements", "reason_type", "TEXT NOT NULL DEFAULT 'Movimiento'")
        ensure_column(connection, "inventory_movements", "stock_before", "REAL NOT NULL DEFAULT 0")
        ensure_column(connection, "inventory_movements", "stock_after", "REAL NOT NULL DEFAULT 0")
        ensure_column(connection, "inventory_movements", "temperature_c", "REAL")
        ensure_column(connection, "inventory_movements", "patient_id", "INTEGER")
        ensure_column(connection, "inventory_movements", "appointment_id", "INTEGER")
        ensure_column(connection, "inventory_movements", "priority", "TEXT NOT NULL DEFAULT 'Normal'")
        ensure_column(connection, "inventory_movements", "external_reference", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "inventory_movements", "counterparty_location_id", "INTEGER")
        ensure_column(connection, "inventory_movements", "transfer_reference", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "appointments", "organization_id", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(connection, "appointments", "location_id", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(connection, "appointments", "duration_minutes", "INTEGER NOT NULL DEFAULT 30")
        ensure_column(connection, "appointments", "veterinarian", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "appointments", "patient_id", "INTEGER")
        ensure_column(connection, "appointments", "veterinarian_user_id", "INTEGER")
        ensure_column(connection, "appointments", "cancellation_reason", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "appointments", "priority", "TEXT NOT NULL DEFAULT 'Normal'")
        ensure_column(connection, "appointments", "triage_level", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "appointments", "triage_note", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "appointments", "arrival_at", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "appointments", "source_system", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "appointments", "external_id", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "patients", "organization_id", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(connection, "patients", "location_id", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(connection, "patients", "document_number", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "patients", "birth_date", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "patients", "sex", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "patients", "insurance_name", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "clinical_records", "organization_id", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(connection, "clinical_records", "location_id", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(connection, "patients", "species", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "patients", "breed", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "patients", "weight_kg", "REAL NOT NULL DEFAULT 0")
        ensure_column(connection, "patients", "vaccine_status", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "patients", "source_system", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "patients", "external_id", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "patients", "color", "TEXT")
        ensure_column(connection, "patients", "microchip", "TEXT")
        ensure_column(connection,"patients", "tutor_email", "TEXT")
        ensure_column(connection,"patients", "tutor_address", "TEXT")
        ensure_column(connection,"patients", "emergency_contact_name", "TEXT")
        ensure_column(connection,"patients", "emergency_contact_phone", "TEXT")
        ensure_column(connection,"patients", "emergency_contact_relationship", "TEXT")
        ensure_column(connection,"patients", "reproductive_status", "TEXT")
        ensure_column(connection,"patients", "sterilized", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(connection,"patients", "sterilization_date", "TEXT")
        ensure_column(connection,"patients", "allergies", "TEXT")
        ensure_column(connection,"patients", "preexisting_conditions", "TEXT")
        ensure_column(connection,"patients", "medical_history", "TEXT")
        ensure_column(connection,"patients", "deworming_status", "TEXT")
        ensure_column(connection,"patients", "deworming_date", "TEXT")
        ensure_column(connection,"patients", "clinical_alert", "TEXT")
        ensure_column(connection,"patients","patient_status","TEXT NOT NULL DEFAULT 'active'")
        ensure_column(connection,"patients", "updated_at", "TEXT")
        ensure_column(connection,"patients", "updated_by_user_id", "INTEGER")
        ensure_column(connection, "clinical_records", "follow_up_date", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "clinical_records", "dental_chart", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "clinical_records", "current_weight_kg", "REAL NOT NULL DEFAULT 0")
        ensure_column(connection, "clinical_records", "payment_amount", "REAL NOT NULL DEFAULT 0")
        ensure_column(connection, "clinical_records", "payment_method", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "clinical_records", "diagnosis", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "clinical_records", "treatment_plan", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "clinical_records", "allergies", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "clinical_records", "vital_signs", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "clinical_records", "prescription", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "clinical_records", "discharge_notes", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "clinical_records", "service_performed", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "clinical_records", "next_vaccine_due", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "locations", "catalog_kind", "TEXT NOT NULL DEFAULT 'human'")
        ensure_column(connection, "locations", "external_code", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "locations", "search_text", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "locations", "sector", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "locations", "phone", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "locations", "opening_hours", "TEXT NOT NULL DEFAULT ''")
        ensure_indexes(connection)
        if get_settings().seed_demo_data:
            seed_network_catalog(connection)
            seed_app_settings(connection)
            backfill_location_catalog_kinds(connection)
            backfill_location_search_text(connection)
            assign_scope_defaults(connection)
        connection.commit()


def ensure_indexes(connection: DatabaseConnection) -> None:
    connection.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_organizations_name ON organizations(name);
        CREATE INDEX IF NOT EXISTS idx_locations_org_id ON locations(organization_id);
        CREATE INDEX IF NOT EXISTS idx_locations_name ON locations(name);
        CREATE INDEX IF NOT EXISTS idx_locations_city ON locations(city);
        CREATE INDEX IF NOT EXISTS idx_locations_active ON locations(is_active);
        CREATE INDEX IF NOT EXISTS idx_alert_ack_scope ON alert_acknowledgements(organization_id, location_id, alert_key);
        CREATE INDEX IF NOT EXISTS idx_locations_catalog_kind ON locations(catalog_kind);
        CREATE INDEX IF NOT EXISTS idx_locations_external_code ON locations(external_code);
        CREATE INDEX IF NOT EXISTS idx_locations_search_text ON locations(search_text);
        CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
        CREATE INDEX IF NOT EXISTS idx_users_locked_until ON users(locked_until);
        CREATE INDEX IF NOT EXISTS idx_password_reset_token_hash ON password_reset_tokens(token_hash);
        CREATE INDEX IF NOT EXISTS idx_alerts_scope_due ON alerts(organization_id, location_id, status, due_at);
        CREATE INDEX IF NOT EXISTS idx_inventory_items_scope_status ON inventory_items(organization_id, location_id, lot_status);
        CREATE INDEX IF NOT EXISTS idx_inventory_items_product_lot ON inventory_items(organization_id, product_id, lot);
        CREATE INDEX IF NOT EXISTS idx_inventory_movements_scope_created ON inventory_movements(organization_id, location_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_inventory_movements_transfer ON inventory_movements(transfer_reference);
        CREATE INDEX IF NOT EXISTS idx_inventory_replenishments_scope_status ON inventory_replenishments(organization_id, location_id, status);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_patients_external ON patients(organization_id, source_system, external_id) WHERE external_id <> '';
        CREATE UNIQUE INDEX IF NOT EXISTS idx_appointments_external ON appointments(organization_id, source_system, external_id) WHERE external_id <> '';
        CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_external ON inventory_items(organization_id, source_system, external_id) WHERE external_id <> '';
        CREATE UNIQUE INDEX IF NOT EXISTS idx_integration_outbox_event_key ON integration_outbox(organization_id, event_key);
        CREATE INDEX IF NOT EXISTS idx_integration_outbox_status ON integration_outbox(status, available_at);
        """
    )


def backfill_location_catalog_kinds(connection: DatabaseConnection) -> None:
    connection.execute("UPDATE locations SET catalog_kind = COALESCE(NULLIF(catalog_kind, ''), 'human')")
    connection.execute(
        """
        UPDATE locations
        SET catalog_kind = 'odontologia'
        WHERE LOWER(name || ' ' || address) LIKE '%odonto%'
           OR LOWER(name || ' ' || address) LIKE '%dent%'
           OR LOWER(name || ' ' || address) LIKE '%ortodon%'
           OR LOWER(name || ' ' || address) LIKE '%periodon%'
           OR LOWER(name || ' ' || address) LIKE '%endodon%'
           OR LOWER(name || ' ' || address) LIKE '%oral%'
           OR id IN (1, 5, 6, 7)
        """
    )
    connection.execute(
        """
        UPDATE locations
        SET catalog_kind = 'veterinaria'
        WHERE LOWER(name || ' ' || address) LIKE '%veter%'
           OR LOWER(name || ' ' || address) LIKE '%mascota%'
           OR LOWER(name || ' ' || address) LIKE '%canin%'
           OR LOWER(name || ' ' || address) LIKE '%felin%'
           OR LOWER(name || ' ' || address) LIKE '%pet%'
           OR id = 2
        """
    )
    connection.execute(
        """
        UPDATE locations
        SET catalog_kind = 'consulta-general'
        WHERE catalog_kind = 'human'
        """
    )


def backfill_location_search_text(connection: DatabaseConnection) -> None:
    rows = connection.execute(
        """
        SELECT
            locations.id,
            locations.name,
            locations.city,
            locations.address,
            organizations.name AS organization_name
        FROM locations
        INNER JOIN organizations ON organizations.id = locations.organization_id
        """
    ).fetchall()

    for row in rows:
        search_text = normalize_search_blob(
            " ".join(
                part
                for part in (
                    row["organization_name"],
                    row["name"],
                    row["city"],
                    row["address"],
                )
                if part
            )
        )
        connection.execute(
            """
            UPDATE locations
            SET search_text = ?
            WHERE id = ?
            """,
            (search_text, row["id"]),
        )


def build_schema_sql(dialect: str) -> str:
    if dialect == "postgres":
        id_column = "SERIAL PRIMARY KEY"
        created_at_type = "TIMESTAMP"
    else:
        id_column = "INTEGER PRIMARY KEY AUTOINCREMENT"
        created_at_type = "TEXT"

    return f"""
        CREATE TABLE IF NOT EXISTS organizations (
            id {id_column},
            name TEXT NOT NULL,
            country TEXT NOT NULL DEFAULT '',
            timezone TEXT NOT NULL DEFAULT 'America/Bogota',
            contact_email TEXT NOT NULL DEFAULT '',
            contact_phone TEXT NOT NULL DEFAULT '',
            plan_code TEXT NOT NULL DEFAULT 'essential',
            plan_status TEXT NOT NULL DEFAULT 'active',
            billing_cycle TEXT NOT NULL DEFAULT 'monthly',
            created_at {created_at_type} NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS locations (
            id {id_column},
            organization_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            city TEXT NOT NULL DEFAULT '',
            address TEXT NOT NULL DEFAULT '',
            sector TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '',
            opening_hours TEXT NOT NULL DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at {created_at_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (organization_id) REFERENCES organizations (id)
        );

        CREATE TABLE IF NOT EXISTS users (
            id {id_column},
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            organization_id INTEGER NOT NULL DEFAULT 1,
            location_id INTEGER NOT NULL DEFAULT 1,
            specialty TEXT NOT NULL DEFAULT '',
            permission_overrides TEXT NOT NULL DEFAULT '',
            failed_login_attempts INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT NOT NULL DEFAULT '',
            must_change_password INTEGER NOT NULL DEFAULT 0,
            password_changed_at {created_at_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at {created_at_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (organization_id) REFERENCES organizations (id),
            FOREIGN KEY (location_id) REFERENCES locations (id)
        );

        CREATE TABLE IF NOT EXISTS inventory_items (
            id {id_column},
            organization_id INTEGER NOT NULL DEFAULT 1,
            location_id INTEGER NOT NULL DEFAULT 1,
            name TEXT NOT NULL,
            barcode TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL,
            brand TEXT NOT NULL,
            regulatory_agency TEXT NOT NULL,
            regulatory_code TEXT NOT NULL,
            supplier TEXT NOT NULL DEFAULT '',
            lot TEXT NOT NULL,
            quantity REAL NOT NULL CHECK (quantity >= 0),
            min_stock REAL NOT NULL CHECK (min_stock >= 0),
            unit_cost REAL NOT NULL DEFAULT 0,
            sale_price REAL NOT NULL DEFAULT 0,
            storage_condition TEXT NOT NULL DEFAULT '',
            requires_cold_chain INTEGER NOT NULL DEFAULT 0,
            location TEXT NOT NULL,
            last_counted_at TEXT NOT NULL DEFAULT '',
            expiry_date TEXT NOT NULL,
            is_quarantined INTEGER NOT NULL DEFAULT 0,
            quarantine_reason TEXT NOT NULL DEFAULT '',
            replenishment_request_id INTEGER,
            source_system TEXT NOT NULL DEFAULT '',
            external_id TEXT NOT NULL DEFAULT '',
            created_at {created_at_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (organization_id) REFERENCES organizations (id),
            FOREIGN KEY (location_id) REFERENCES locations (id)
        );

        CREATE TABLE IF NOT EXISTS inventory_products (
            id {id_column}, organization_id INTEGER NOT NULL, name TEXT NOT NULL,
            brand TEXT NOT NULL DEFAULT '', barcode TEXT NOT NULL DEFAULT '',
            regulatory_agency TEXT NOT NULL DEFAULT '', regulatory_code TEXT NOT NULL DEFAULT '',
            item_type TEXT NOT NULL DEFAULT 'Medicamento', unit_measure TEXT NOT NULL DEFAULT 'unidades',
            storage_condition TEXT NOT NULL DEFAULT '', requires_cold_chain INTEGER NOT NULL DEFAULT 0,
            manufacturer TEXT NOT NULL DEFAULT '', presentation TEXT NOT NULL DEFAULT '', concentration TEXT NOT NULL DEFAULT '',
            created_at {created_at_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (organization_id) REFERENCES organizations (id)
        );

        CREATE TABLE IF NOT EXISTS cold_chain_logs (
            id {id_column}, item_id INTEGER NOT NULL, organization_id INTEGER NOT NULL,
            location_id INTEGER NOT NULL, user_id INTEGER, temperature_c REAL NOT NULL,
            has_incident INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '',
            created_at {created_at_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (item_id) REFERENCES inventory_items (id), FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS inventory_movements (
            id {id_column},
            item_id INTEGER NOT NULL,
            organization_id INTEGER NOT NULL DEFAULT 1,
            location_id INTEGER NOT NULL DEFAULT 1,
            user_id INTEGER,
            movement_type TEXT NOT NULL CHECK (movement_type IN ('in', 'out')),
            quantity REAL NOT NULL CHECK (quantity > 0),
            note TEXT NOT NULL,
            patient_id INTEGER,
            appointment_id INTEGER,
            priority TEXT NOT NULL DEFAULT 'Normal',
            external_reference TEXT NOT NULL DEFAULT '',
            counterparty_location_id INTEGER,
            transfer_reference TEXT NOT NULL DEFAULT '',
            created_at {created_at_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (item_id) REFERENCES inventory_items (id),
            FOREIGN KEY (organization_id) REFERENCES organizations (id),
            FOREIGN KEY (location_id) REFERENCES locations (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS inventory_replenishments (
            id {id_column},
            organization_id INTEGER NOT NULL,
            location_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            requested_by_user_id INTEGER,
            reviewed_by_user_id INTEGER,
            requested_quantity REAL NOT NULL CHECK (requested_quantity > 0),
            supplier TEXT NOT NULL DEFAULT '',
            priority TEXT NOT NULL DEFAULT 'Normal',
            note TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Pendiente',
            reviewed_at TEXT NOT NULL DEFAULT '',
            received_inventory_item_id INTEGER,
            created_at {created_at_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (organization_id) REFERENCES organizations (id),
            FOREIGN KEY (location_id) REFERENCES locations (id),
            FOREIGN KEY (item_id) REFERENCES inventory_items (id),
            FOREIGN KEY (requested_by_user_id) REFERENCES users (id),
            FOREIGN KEY (reviewed_by_user_id) REFERENCES users (id),
            FOREIGN KEY (received_inventory_item_id) REFERENCES inventory_items (id)
        );

        CREATE TABLE IF NOT EXISTS appointments (
            id {id_column},
            organization_id INTEGER NOT NULL DEFAULT 1,
            location_id INTEGER NOT NULL DEFAULT 1,
            appointment_date TEXT NOT NULL,
            appointment_time TEXT NOT NULL,
            patient_name TEXT NOT NULL,
            service TEXT NOT NULL,
            channel TEXT NOT NULL,
            status TEXT NOT NULL,
            specialty TEXT NOT NULL,
            note TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'Normal',
            triage_level TEXT NOT NULL DEFAULT '',
            triage_note TEXT NOT NULL DEFAULT '',
            arrival_at TEXT NOT NULL DEFAULT '',
            source_system TEXT NOT NULL DEFAULT '',
            external_id TEXT NOT NULL DEFAULT '',
            created_at {created_at_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (organization_id) REFERENCES organizations (id),
            FOREIGN KEY (location_id) REFERENCES locations (id)
        );

        CREATE TABLE IF NOT EXISTS patients (
            id {id_column},
            organization_id INTEGER NOT NULL DEFAULT 1,
            location_id INTEGER NOT NULL DEFAULT 1,
            display_name TEXT NOT NULL,
            patient_type TEXT NOT NULL,
            specialty TEXT NOT NULL,
            owner_name TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '',
            last_visit TEXT NOT NULL DEFAULT '',
            document_number TEXT NOT NULL DEFAULT '',
            birth_date TEXT NOT NULL DEFAULT '',
            sex TEXT NOT NULL DEFAULT '',
            insurance_name TEXT NOT NULL DEFAULT '',
            species TEXT NOT NULL DEFAULT '',
            breed TEXT NOT NULL DEFAULT '',
            weight_kg REAL NOT NULL DEFAULT 0,
            vaccine_status TEXT NOT NULL DEFAULT '',
            source_system TEXT NOT NULL DEFAULT '',
            external_id TEXT NOT NULL DEFAULT '',
            created_at {created_at_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (organization_id) REFERENCES organizations (id),
            FOREIGN KEY (location_id) REFERENCES locations (id)
        );

        CREATE TABLE IF NOT EXISTS clinical_records (
            id {id_column},
            patient_id INTEGER NOT NULL,
            organization_id INTEGER NOT NULL DEFAULT 1,
            location_id INTEGER NOT NULL DEFAULT 1,
            encounter_date TEXT NOT NULL,
            specialty TEXT NOT NULL,
            reason TEXT NOT NULL,
            note TEXT NOT NULL,
            status TEXT NOT NULL,
            professional TEXT NOT NULL,
            diagnosis TEXT NOT NULL DEFAULT '',
            treatment_plan TEXT NOT NULL DEFAULT '',
            allergies TEXT NOT NULL DEFAULT '',
            vital_signs TEXT NOT NULL DEFAULT '',
            prescription TEXT NOT NULL DEFAULT '',
            discharge_notes TEXT NOT NULL DEFAULT '',
            service_performed TEXT NOT NULL DEFAULT '',
            follow_up_date TEXT NOT NULL DEFAULT '',
            next_vaccine_due TEXT NOT NULL DEFAULT '',
            dental_chart TEXT NOT NULL DEFAULT '',
            current_weight_kg REAL NOT NULL DEFAULT 0,
            payment_amount REAL NOT NULL DEFAULT 0,
            payment_method TEXT NOT NULL DEFAULT '',
            created_at {created_at_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients (id),
            FOREIGN KEY (organization_id) REFERENCES organizations (id),
            FOREIGN KEY (location_id) REFERENCES locations (id)
        );

        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id {id_column},
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT NOT NULL DEFAULT '',
            created_at {created_at_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT '',
            created_at {created_at_type} NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS audit_events (
            id {id_column},
            user_id INTEGER,
            organization_id INTEGER,
            location_id INTEGER,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_label TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (organization_id) REFERENCES organizations (id),
            FOREIGN KEY (location_id) REFERENCES locations (id)
        );

        CREATE TABLE IF NOT EXISTS legal_acceptances (
            id {id_column},
            user_id INTEGER NOT NULL,
            organization_id INTEGER NOT NULL,
            privacy_version TEXT NOT NULL,
            terms_version TEXT NOT NULL,
            evidence_hash TEXT NOT NULL,
            accepted_at {created_at_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (organization_id) REFERENCES organizations (id)
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id {id_column},
            organization_id INTEGER NOT NULL,
            location_id INTEGER NOT NULL,
            created_by INTEGER,
            assigned_user_id INTEGER,
            title TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            priority TEXT NOT NULL DEFAULT 'normal',
            status TEXT NOT NULL DEFAULT 'active',
            due_at TEXT NOT NULL,
            recurrence TEXT NOT NULL DEFAULT 'once',
            escalation_minutes INTEGER NOT NULL DEFAULT 0,
            entity_type TEXT NOT NULL DEFAULT '',
            entity_id INTEGER,
            source TEXT NOT NULL DEFAULT 'manual',
            resolved_at TEXT NOT NULL DEFAULT '',
            created_at {created_at_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (organization_id) REFERENCES organizations (id),
            FOREIGN KEY (location_id) REFERENCES locations (id),
            FOREIGN KEY (created_by) REFERENCES users (id),
            FOREIGN KEY (assigned_user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS alert_acknowledgements (
            id {id_column},
            alert_key TEXT NOT NULL,
            organization_id INTEGER NOT NULL,
            location_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            acknowledged_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (alert_key, organization_id, location_id),
            FOREIGN KEY (organization_id) REFERENCES organizations (id),
            FOREIGN KEY (location_id) REFERENCES locations (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS shift_handoffs (
            id {id_column},
            organization_id INTEGER NOT NULL,
            location_id INTEGER NOT NULL,
            created_by INTEGER NOT NULL,
            summary TEXT NOT NULL,
            pending_actions TEXT NOT NULL DEFAULT '',
            shift_label TEXT NOT NULL DEFAULT '',
            created_at {created_at_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (organization_id) REFERENCES organizations (id),
            FOREIGN KEY (location_id) REFERENCES locations (id),
            FOREIGN KEY (created_by) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS integration_outbox (
            id {id_column}, organization_id INTEGER NOT NULL, location_id INTEGER,
            event_type TEXT NOT NULL, event_key TEXT NOT NULL,
            payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '',
            available_at {created_at_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at {created_at_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            processed_at TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (organization_id) REFERENCES organizations (id),
            FOREIGN KEY (location_id) REFERENCES locations (id)
        );
        
    """


def ensure_column(
    connection: DatabaseConnection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    if connection.dialect == "sqlite":
        columns = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        existing_names = {column["name"] for column in columns}
        if column_name in existing_names:
            return
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
        return

    columns = connection.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = %s
        """,
        (table_name,),
    ).fetchall()
    existing_names = {column["column_name"] for column in columns}
    if column_name in existing_names:
        return
    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {definition_to_postgres(column_name, definition)}")


def definition_to_postgres(column_name: str, definition: str) -> str:
    normalized = definition.replace("REAL", "DOUBLE PRECISION")
    return f"{column_name} {normalized}"


def seed_db() -> None:
    with get_connection() as connection:
        seed_network_catalog(connection)
        seed_app_settings(connection)
        assign_scope_defaults(connection)
        current_items = connection.execute("SELECT COUNT(*) AS total FROM inventory_items").fetchone()["total"]

        if current_items:
            current_appointments = connection.execute(
                "SELECT COUNT(*) AS total FROM appointments"
            ).fetchone()["total"]
            current_patients = connection.execute(
                "SELECT COUNT(*) AS total FROM patients"
            ).fetchone()["total"]
            current_records = connection.execute(
                "SELECT COUNT(*) AS total FROM clinical_records"
            ).fetchone()["total"]
            current_users = connection.execute(
                "SELECT COUNT(*) AS total FROM users"
            ).fetchone()["total"]
            ensure_demo_users(connection)
            if current_appointments and current_patients and current_records and current_users:
                return

        connection.executemany(
            """
            INSERT INTO inventory_items (
                organization_id, location_id, name, barcode, category, brand, regulatory_agency,
                regulatory_code, supplier, lot, quantity, min_stock, unit_cost, sale_price,
                storage_condition, requires_cold_chain, location, last_counted_at, expiry_date
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, 1, "Anestesico local 2%", "7701234500012", "Odontologia", "SeptaCare", "INVIMA", "INV-OD-2045", "Distribuciones Norte", "AL-2045", 18, 25, 16000, 26000, "Temperatura ambiente", 0, "Consultorio 2", "2026-04-15", "2026-05-31"),
                (1, 2, "Vacuna triple felina", "7701234500019", "Veterinaria", "PetBio", "ICA", "ICA-VF-8891", "Biologicos Andinos", "VF-8891", 9, 8, 42000, 62000, "Refrigerado 2C a 8C", 1, "Nevera A", "2026-04-15", "2026-06-28"),
                (2, 3, "Guantes nitrilo talla M", "7701234500026", "General", "SafeTouch", "INVIMA", "INV-GN-3210", "Suministros Clinicos SAS", "GN-3210", 40, 60, 900, 1600, "Temperatura ambiente", 0, "Bodega principal", "2026-04-15", "2027-01-15"),
                (2, 4, "Kit sutura 3-0", "7701234500033", "Procedimientos", "SurgiLine", "INVIMA", "INV-KS-4477", "SurgiLine Colombia", "KS-4477", 72, 20, 7800, 13000, "Temperatura ambiente", 0, "Cirugia menor", "2026-04-15", "2026-11-07"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO appointments (
                organization_id, location_id, appointment_date, appointment_time, patient_name,
                service, channel, status, specialty, note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, 1, "2026-04-16", "08:00", "Laura Mendoza", "Control odontologico", "Presencial", "Confirmada", "Odontologia", "Control semestral y limpieza"),
                (1, 2, "2026-04-16", "09:20", "Max / Ana Rojas", "Vacunacion veterinaria", "Presencial", "En espera", "Veterinaria", "Refuerzo anual"),
                (2, 3, "2026-04-16", "10:15", "Carlos Perez", "Valoracion general", "Virtual", "Llamar", "Consulta general", "Revision de resultados"),
                (2, 4, "2026-04-16", "11:40", "Mia / David Leon", "Revision postoperatoria", "Presencial", "Confirmada", "Veterinaria", "Control de herida"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO patients (
                organization_id, location_id, display_name, patient_type, specialty,
                owner_name, phone, last_visit, document_number, birth_date, sex, insurance_name,
                species, breed, weight_kg, vaccine_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, 1, "Laura Mendoza", "Humano", "Odontologia", "", "3001234567", "2026-04-10", "10203040", "1992-08-15", "Femenino", "Prepagada", "", "", 0, ""),
                (1, 2, "Max", "Animal", "Veterinaria", "Ana Rojas", "3109876543", "2026-03-18", "", "", "", "", "Canino", "Labrador", 28.4, "Al dia"),
                (2, 3, "Carlos Perez", "Humano", "Consulta general", "", "3154441122", "2026-04-12", "55667788", "1987-02-03", "Masculino", "EPS Centro", "", "", 0, ""),
            ],
        )
        connection.executemany(
            """
            INSERT INTO clinical_records (
                patient_id, organization_id, location_id, encounter_date, specialty, reason,
                note, status, professional, diagnosis, treatment_plan, allergies, vital_signs,
                prescription, discharge_notes, service_performed, follow_up_date, next_vaccine_due,
                dental_chart, current_weight_kg, payment_amount, payment_method
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, 1, 1, "2026-04-10", "Odontologia", "Control y profilaxis", "Odontograma sin hallazgos criticos. Reforzar higiene y control en seis meses.", "Cerrada", "Dra. Rios", "Gingivitis leve", "Profilaxis y control preventivo", "No refiere", "TA 110/70 | FC 72", "Cepillado + enjuague", "Control en casa y volver si hay dolor", "Profilaxis dental", "2026-10-10", "", "18 sano, 17 resina, 16 caries oclusal, 26 ausente", 0, 185000, "Transferencia"),
                (2, 1, 2, "2026-03-18", "Veterinaria", "Vacunacion anual", "Paciente estable, peso dentro del rango esperado. Aplicado refuerzo y recomendado control semestral.", "Seguimiento", "Dr. Molina", "Plan vacunal vigente", "Refuerzo anual y control semestral", "Sin alergias conocidas", "Peso 28.4 kg | FC normal", "Refuerzo vacunal", "Vigilar apetito y sitio de aplicacion", "Vacunacion anual", "2026-09-18", "2027-03-18", "", 28.4, 120000, "Tarjeta"),
                (3, 2, 3, "2026-04-12", "Consulta general", "Revision de resultados", "Se revisan examenes recientes, sin signos de alarma. Continuar manejo y control en un mes.", "Cerrada", "Dra. Vega", "Control de hipertension", "Ajuste leve de habitos y seguimiento", "Penicilina", "TA 128/82 | FC 76", "Losartan segun indicacion", "Continuar signos de alarma y control", "Consulta de control", "2026-05-12", "", "", 0, 95000, "Efectivo"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO users (
                full_name, email, password_hash, role, organization_id, location_id, specialty
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("Administrador Velmorax", "admin@velmorax.local", DEMO_PASSWORD_HASH, "admin", 1, 1, "Red completa"),
                ("Coordinacion Clinica", "clinica@velmorax.local", DEMO_PASSWORD_HASH, "clinical", 1, 1, "Odontologia"),
                ("Bodega Principal", "inventario@velmorax.local", DEMO_PASSWORD_HASH, "inventory", 1, 1, "Insumos"),
            ],
        )
                # Historial de peso
        connection.executemany("""
            CREATE TABLE IF NOT EXISTS patient_weight_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                weight_kg REAL NOT NULL,
                recorded_at TEXT NOT NULL,
                recorded_by_user_id INTEGER,
                notes TEXT,
                FOREIGN KEY (patient_id)
                    REFERENCES patients(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (recorded_by_user_id)
                    REFERENCES users(id)
            )
        """)

        # Vacunas
        connection.executemany("""
            CREATE TABLE IF NOT EXISTS patient_vaccines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                vaccine_name TEXT NOT NULL,
                application_date TEXT,
                next_date TEXT,
                lot_number TEXT,
                veterinarian TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                created_by_user_id INTEGER,
                FOREIGN KEY (patient_id)
                    REFERENCES patients(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (created_by_user_id)
                    REFERENCES users(id)
            )
        """)

        # Archivos adjuntos
        connection.executemany("""
            CREATE TABLE IF NOT EXISTS patient_attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_type TEXT,
                description TEXT,
                uploaded_at TEXT NOT NULL,
                uploaded_by_user_id INTEGER,
                FOREIGN KEY (patient_id)
                    REFERENCES patients(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (uploaded_by_user_id)
                    REFERENCES users(id)
            )
        """)
        connection.commit()


def ensure_demo_users(connection: DatabaseConnection) -> None:
    for email, organization_id, location_id, specialty in (
        ("admin@velmorax.local", 1, 1, "Red completa"),
        ("clinica@velmorax.local", 1, 1, "Odontologia"),
        ("inventario@velmorax.local", 1, 1, "Insumos"),
    ):
        connection.execute(
            """
            UPDATE users
            SET password_hash = ?, organization_id = ?, location_id = ?, specialty = ?, must_change_password = 0
            WHERE email = ?
            """,
            (DEMO_PASSWORD_HASH, organization_id, location_id, specialty, email),
        )


def seed_network_catalog(connection: DatabaseConnection) -> None:
    organization_catalog = [
        (1, "Velmorax Red Clinica", "Colombia", "America/Bogota", "operaciones@velmorax.local", "6015551000"),
        (2, "Aliados de Atencion Integral", "Colombia", "America/Bogota", "contacto@aliados.local", "6045552000"),
        (3, "Odontoclave", "Colombia", "America/Bogota", "sedes@odontoclave.local", "6045553000"),
    ]
    for organization_id, name, country, timezone, contact_email, contact_phone in organization_catalog:
        existing = connection.execute(
            "SELECT id FROM organizations WHERE LOWER(name) = LOWER(?)",
            (name,),
        ).fetchone()
        if existing:
            connection.execute(
                """
                UPDATE organizations
                SET country = ?, timezone = ?, contact_email = ?, contact_phone = ?
                WHERE id = ?
                """,
                (country, timezone, contact_email, contact_phone, existing["id"]),
            )
            continue
        connection.execute(
            """
            INSERT INTO organizations (id, name, country, timezone, contact_email, contact_phone)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (organization_id, name, country, timezone, contact_email, contact_phone),
        )

    location_catalog = [
        (1, 1, "Sede Norte Dental", "Bogota", "Calle 100 # 18A-20", "Norte", "6015551010", "Lun-Vie 7:00-18:00"),
        (2, 1, "Sede Mascotas Centro", "Bogota", "Carrera 13 # 42-15", "Centro", "6015551020", "Lun-Sab 8:00-19:00"),
        (3, 2, "Sede Integral Medellin", "Medellin", "Calle 10 # 40-12", "El Poblado", "6045552010", "Lun-Vie 7:00-17:00"),
        (4, 2, "Sede Ambulatoria Cali", "Cali", "Avenida 5N # 22-30", "Granada", "6025552020", "Lun-Vie 7:00-17:00"),
        (5, 3, "Odontoclave Punto Clave", "Medellin", "Centro Integral de Servicios Punto Clave | Calle 27 No. 46-70 interior 267", "Guayabal", "6045553010", "Lun-Sab 7:00-18:00"),
        (6, 3, "Odontoclave Parque Fabricato", "Bello", "Centro Comercial Parque Fabricato | Sotano 1 local 117A", "Fabricato", "6045553020", "Lun-Sab 8:00-19:00"),
        (7, 3, "Odontoclave Mayorca", "Sabaneta", "Centro Comercial Mayorca Torre Medica | Piso 12 consultorio 12-02", "Mayorca", "6045553030", "Lun-Sab 7:00-18:00"),
    ]
    for location_id, organization_id, name, city, address, sector, phone, opening_hours in location_catalog:
        existing_by_id = connection.execute(
            "SELECT id FROM locations WHERE id = ?",
            (location_id,),
        ).fetchone()
        if existing_by_id:
            connection.execute(
                """
                UPDATE locations
                SET organization_id = ?, name = ?, city = ?, address = ?, sector = ?, phone = ?, opening_hours = ?, is_active = 1
                WHERE id = ?
                """,
                (organization_id, name, city, address, sector, phone, opening_hours, location_id),
            )
            continue
        existing = connection.execute(
            """
            SELECT id
            FROM locations
            WHERE organization_id = ? AND LOWER(name) = LOWER(?)
            """,
            (organization_id, name),
        ).fetchone()
        if existing:
            connection.execute(
                """
                UPDATE locations
                SET city = ?, address = ?, sector = ?, phone = ?, opening_hours = ?, is_active = 1
                WHERE id = ?
                """,
                (city, address, sector, phone, opening_hours, existing["id"]),
            )
            continue
        connection.execute(
            """
            INSERT INTO locations (id, organization_id, name, city, address, sector, phone, opening_hours)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (location_id, organization_id, name, city, address, sector, phone, opening_hours),
        )

    official_odontoclave_names = {
        "Odontoclave Punto Clave",
        "Odontoclave Parque Fabricato",
        "Odontoclave Mayorca",
    }
    connection.execute(
        """
        UPDATE locations
        SET is_active = CASE
            WHEN name IN (?, ?, ?) THEN 1
            ELSE 0
        END
        WHERE organization_id = 3
        """,
        tuple(official_odontoclave_names),
    )


def assign_scope_defaults(connection: DatabaseConnection) -> None:
    default_org = connection.execute(
        "SELECT id FROM organizations ORDER BY id ASC LIMIT 1"
    ).fetchone()
    default_location = connection.execute(
        "SELECT id, organization_id FROM locations ORDER BY id ASC LIMIT 1"
    ).fetchone()

    if default_org is None or default_location is None:
        return

    for table_name in ("inventory_items", "appointments", "patients", "clinical_records", "users"):
        connection.execute(
            f"""
            UPDATE {table_name}
            SET organization_id = COALESCE(NULLIF(organization_id, 0), ?)
            WHERE organization_id IS NULL OR organization_id = 0
            """,
            (default_org["id"],),
        )
        connection.execute(
            f"""
            UPDATE {table_name}
            SET location_id = COALESCE(NULLIF(location_id, 0), ?)
            WHERE location_id IS NULL OR location_id = 0
            """,
            (default_location["id"],),
        )

    connection.execute(
        """
        UPDATE inventory_movements
        SET organization_id = COALESCE(
            NULLIF(organization_id, 0),
            (SELECT organization_id FROM inventory_items WHERE inventory_items.id = inventory_movements.item_id),
            ?
        )
        WHERE organization_id IS NULL OR organization_id = 0
        """,
        (default_org["id"],),
    )
    connection.execute(
        """
        UPDATE inventory_movements
        SET location_id = COALESCE(
            NULLIF(location_id, 0),
            (SELECT location_id FROM inventory_items WHERE inventory_items.id = inventory_movements.item_id),
            ?
        )
        WHERE location_id IS NULL OR location_id = 0
        """,
        (default_location["id"],),
    )


def seed_app_settings(connection: DatabaseConnection) -> None:
    defaults = {
        "support_email": "soporte@velmorax.local",
        "support_phone": "6015550000",
        "security_note": "Bloqueo temporal tras varios intentos fallidos y restablecimiento de clave por token.",
        "deployment_note": "Configura HTTPS, DATABASE_URL en PostgreSQL y copias de seguridad automaticas.",
    }
    for key, value in defaults.items():
        connection.execute(
            """
            INSERT INTO app_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO NOTHING
            """,
            (key, value),
        )


def normalize_query(sql: str, params, dialect: str) -> tuple[str, object]:
    if dialect == "sqlite":
        return sql, params

    converted = re.sub(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", r"%(\1)s", sql)
    converted = converted.replace("?", "%s")
    return converted, params


def normalize_search_blob(value: str) -> str:
    normalized = re.sub(r"\s+", " ", (value or "").strip()).lower()
    normalized = unicodedata.normalize("NFD", normalized)
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", normalized)


def split_sql_script(sql: str) -> list[str]:
    statements = []
    for piece in sql.split(";"):
        statement = piece.strip()
        if statement:
            statements.append(statement)
    return statements
