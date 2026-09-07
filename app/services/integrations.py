from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from app.core.database import get_connection


INTEGRATION_CATALOG = (
    {"code": "billing", "name": "Facturación electrónica", "purpose": "Ventas y documentos tributarios", "env": "BILLING_API_URL"},
    {"code": "laboratory", "name": "Laboratorio", "purpose": "Órdenes y resultados clínicos", "env": "LAB_API_URL"},
    {"code": "whatsapp", "name": "WhatsApp", "purpose": "Recordatorios y avisos autorizados", "env": "WHATSAPP_API_URL"},
    {"code": "email", "name": "Correo", "purpose": "Mensajes transaccionales", "env": "SMTP_HOST"},
    {"code": "accounting", "name": "Contabilidad", "purpose": "Comprobantes y conciliación", "env": "ACCOUNTING_API_URL"},
)


def integration_readiness() -> list[dict]:
    return [{**item, "configured": bool(os.getenv(item["env"], "").strip())} for item in INTEGRATION_CATALOG]


def enqueue_integration_event(*, organization_id: int, location_id: int | None, event_type: str, event_key: str, payload: dict) -> bool:
    forbidden = {"password", "password_hash", "token", "secret", "authorization", "medical_notes"}
    safe_payload = {key: value for key, value in payload.items() if key.lower() not in forbidden}
    with get_connection() as connection:
        existing = connection.execute("SELECT id FROM integration_outbox WHERE organization_id=? AND event_key=?", (organization_id, event_key)).fetchone()
        if existing:
            return False
        connection.execute(
            """INSERT INTO integration_outbox
               (organization_id,location_id,event_type,event_key,payload,status,available_at)
               VALUES (?,?,?,?,?,'pending',?)""",
            (organization_id, location_id, event_type.strip(), event_key.strip(), json.dumps(safe_payload, ensure_ascii=False, sort_keys=True), datetime.now(UTC).isoformat()),
        )
        connection.commit()
    return True


def integration_outbox_summary(organization_id: int) -> dict:
    with get_connection() as connection:
        rows = connection.execute("SELECT status, COUNT(*) AS total FROM integration_outbox WHERE organization_id=? GROUP BY status", (organization_id,)).fetchall()
    counts = {row["status"]: row["total"] for row in rows}
    return {"pending": counts.get("pending", 0), "processed": counts.get("processed", 0), "failed": counts.get("failed", 0)}
