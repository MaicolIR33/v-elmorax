from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.database import get_connection


PRIVACY_VERSION = "2026-09-07"
TERMS_VERSION = "2026-09-07"


def legal_context() -> dict:
    settings = get_settings()
    return {
        "company_name": settings.legal_company_name or "Velmorax",
        "tax_id": settings.legal_tax_id or "Pendiente de configuración",
        "contact_email": settings.legal_contact_email or "Pendiente de configuración",
        "contact_address": settings.legal_contact_address or "Pendiente de configuración",
        "privacy_version": PRIVACY_VERSION,
        "terms_version": TERMS_VERSION,
    }


def record_legal_acceptance(
    *, user_id: int, organization_id: int, remote_address: str, user_agent: str
) -> None:
    settings = get_settings()
    evidence = "|".join(
        (
            str(user_id),
            str(organization_id),
            PRIVACY_VERSION,
            TERMS_VERSION,
            remote_address,
            user_agent,
            datetime.now(UTC).date().isoformat(),
        )
    )
    evidence_hash = hmac.new(
        settings.session_secret.encode("utf-8"), evidence.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    with get_connection() as connection:
        existing = connection.execute(
            """
            SELECT id FROM legal_acceptances
            WHERE user_id = ? AND privacy_version = ? AND terms_version = ?
            """,
            (user_id, PRIVACY_VERSION, TERMS_VERSION),
        ).fetchone()
        if existing is None:
            connection.execute(
                """
                INSERT INTO legal_acceptances (
                    user_id, organization_id, privacy_version, terms_version, evidence_hash
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, organization_id, PRIVACY_VERSION, TERMS_VERSION, evidence_hash),
            )
            connection.commit()
