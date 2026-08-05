from __future__ import annotations

import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe

from app.core.database import get_connection


PBKDF2_ITERATIONS = 390000
FAILED_LOGIN_LIMIT = 5
LOCKOUT_MINUTES = 15
PASSWORD_RESET_MINUTES = 30
PRIVILEGED_2FA_ROLES = {"admin", "owner"}


def legacy_sha256_hash(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False
    if stored_hash.startswith("pbkdf2_sha256$"):
        _scheme, iterations, salt, digest = stored_hash.split("$", 3)
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        ).hex()
        return hmac.compare_digest(candidate, digest)
    return hmac.compare_digest(legacy_sha256_hash(password), stored_hash)


def authenticate_user(email: str, password: str) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                users.id,
                users.full_name,
                users.email,
                users.role,
                users.is_active,
                users.password_hash,
                users.organization_id,
                users.location_id,
                users.specialty,
                users.failed_login_attempts,
                users.locked_until,
                users.must_change_password,
                users.password_changed_at
            FROM users
            WHERE lower(email) = lower(?)
            """,
            (email.strip(),),
        ).fetchone()

    if row is None or not row["is_active"]:
        return None
    if is_locked_until_active(row["locked_until"]):
        return None
    if not verify_password(password, row["password_hash"]):
        return None

    return serialize_user_row(row)


def get_user_by_id(user_id: int | None) -> dict | None:
    if not user_id:
        return None

    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                users.id,
                users.full_name,
                users.email,
                users.role,
                users.is_active,
                users.organization_id,
                users.location_id,
                users.specialty,
                users.failed_login_attempts,
                users.locked_until,
                users.must_change_password,
                users.password_changed_at,
                organizations.name AS organization_name,
                locations.name AS location_name
            FROM users
            LEFT JOIN organizations ON organizations.id = users.organization_id
            LEFT JOIN locations ON locations.id = users.location_id
            WHERE users.id = ?
            """,
            (user_id,),
        ).fetchone()

    if row is None or not row["is_active"]:
        return None

    return serialize_user_row(row)


def get_user_by_email(email: str) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                users.id,
                users.full_name,
                users.email,
                users.role,
                users.is_active,
                users.organization_id,
                users.location_id,
                users.specialty,
                users.failed_login_attempts,
                users.locked_until,
                users.must_change_password,
                users.password_changed_at,
                organizations.name AS organization_name,
                locations.name AS location_name
            FROM users
            LEFT JOIN organizations ON organizations.id = users.organization_id
            LEFT JOIN locations ON locations.id = users.location_id
            WHERE lower(users.email) = lower(?)
            """,
            (email.strip(),),
        ).fetchone()

    if row is None:
        return None
    return serialize_user_row(row)


def list_users() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                users.id,
                users.full_name,
                users.email,
                users.role,
                users.is_active,
                users.organization_id,
                users.location_id,
                users.specialty,
                users.failed_login_attempts,
                users.locked_until,
                users.must_change_password,
                users.password_changed_at,
                organizations.name AS organization_name,
                locations.name AS location_name
            FROM users
            LEFT JOIN organizations ON organizations.id = users.organization_id
            LEFT JOIN locations ON locations.id = users.location_id
            ORDER BY users.full_name ASC
            """
        ).fetchall()

    return [serialize_user_row(row) for row in rows]


def create_user(payload: dict) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO users (
                full_name, email, password_hash, role, organization_id, location_id, specialty,
                failed_login_attempts, locked_until, must_change_password, password_changed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, '', 1, CURRENT_TIMESTAMP)
            """,
            (
                payload["full_name"],
                payload["email"],
                hash_password(payload["password"]),
                payload["role"],
                payload["organization_id"],
                payload["location_id"],
                payload["specialty"],
            ),
        )
        connection.commit()


def update_user(user_id: int, payload: dict) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE users
            SET
                full_name = ?,
                email = ?,
                role = ?,
                organization_id = ?,
                location_id = ?,
                specialty = ?
            WHERE id = ?
            """,
            (
                payload["full_name"],
                payload["email"],
                payload["role"],
                payload["organization_id"],
                payload["location_id"],
                payload["specialty"],
                user_id,
            ),
        )
        if payload.get("password"):
            connection.execute(
                """
                UPDATE users
                SET password_hash = ?, password_changed_at = CURRENT_TIMESTAMP, must_change_password = 1
                WHERE id = ?
                """,
                (hash_password(payload["password"]), user_id),
            )
        connection.commit()


def set_user_active(user_id: int, is_active: bool) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE users SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, user_id),
        )
        connection.commit()


def set_user_password(user_id: int, password: str, *, must_change_password: bool = False) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE users
            SET
                password_hash = ?,
                password_changed_at = CURRENT_TIMESTAMP,
                must_change_password = ?,
                failed_login_attempts = 0,
                locked_until = ''
            WHERE id = ?
            """,
            (hash_password(password), 1 if must_change_password else 0, user_id),
        )
        connection.commit()


def mark_password_change_completed(user_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE users SET must_change_password = 0 WHERE id = ?",
            (user_id,),
        )
        connection.commit()


def register_failed_login(email: str) -> None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id, failed_login_attempts FROM users WHERE lower(email) = lower(?)",
            (email.strip(),),
        ).fetchone()
        if row is None:
            return
        attempts = int(row["failed_login_attempts"] or 0) + 1
        locked_until = ""
        if attempts >= FAILED_LOGIN_LIMIT:
            locked_until = format_timestamp(datetime.now(UTC) + timedelta(minutes=LOCKOUT_MINUTES))
            attempts = 0
        connection.execute(
            """
            UPDATE users
            SET failed_login_attempts = ?, locked_until = ?
            WHERE id = ?
            """,
            (attempts, locked_until, row["id"]),
        )
        connection.commit()


def reset_failed_login(user_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE users
            SET failed_login_attempts = 0, locked_until = ''
            WHERE id = ?
            """,
            (user_id,),
        )
        connection.commit()


def login_lock_message(email: str) -> str:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT locked_until
            FROM users
            WHERE lower(email) = lower(?)
            """,
            (email.strip(),),
        ).fetchone()
    if row and is_locked_until_active(row["locked_until"]):
        return "Tu acceso esta bloqueado temporalmente por varios intentos fallidos. Intenta mas tarde o restablece la clave."
    return ""


def create_password_reset_token(email: str) -> str | None:
    user = get_user_by_email(email)
    if user is None or not user["is_active"]:
        return None

    raw_token = token_urlsafe(32)
    token_hash = legacy_sha256_hash(raw_token)
    expires_at = format_timestamp(datetime.now(UTC) + timedelta(minutes=PASSWORD_RESET_MINUTES))

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO password_reset_tokens (user_id, token_hash, expires_at, used_at)
            VALUES (?, ?, ?, '')
            """,
            (user["id"], token_hash, expires_at),
        )
        connection.commit()
    return raw_token


def consume_password_reset_token(token: str, new_password: str) -> dict | None:
    token_hash = legacy_sha256_hash(token)
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT user_id, expires_at, used_at
            FROM password_reset_tokens
            WHERE token_hash = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (token_hash,),
        ).fetchone()
        if row is None:
            return None
        if row["used_at"]:
            return None
        if is_expired(row["expires_at"]):
            return None
        connection.execute(
            """
            UPDATE password_reset_tokens
            SET used_at = CURRENT_TIMESTAMP
            WHERE token_hash = ?
            """,
            (token_hash,),
        )
        connection.commit()

    set_user_password(int(row["user_id"]), new_password, must_change_password=False)
    return get_user_by_id(int(row["user_id"]))


def serialize_user_row(row: dict) -> dict:
    organization_name = row["organization_name"] if "organization_name" in row.keys() else ""
    location_name = row["location_name"] if "location_name" in row.keys() else ""
    role = row["role"]
    return {
        "id": row["id"],
        "full_name": row["full_name"],
        "email": row["email"],
        "role": role,
        "role_label": role_label(role),
        "is_active": bool(row["is_active"]),
        "organization_id": row["organization_id"],
        "location_id": row["location_id"],
        "specialty": row["specialty"],
        "organization_name": organization_name,
        "location_name": location_name,
        "failed_login_attempts": int(row["failed_login_attempts"] or 0) if "failed_login_attempts" in row.keys() else 0,
        "locked_until": row["locked_until"] if "locked_until" in row.keys() else "",
        "is_locked": is_locked_until_active(row["locked_until"]) if "locked_until" in row.keys() else False,
        "must_change_password": bool(row["must_change_password"]) if "must_change_password" in row.keys() else False,
        "password_changed_at": row["password_changed_at"] if "password_changed_at" in row.keys() else "",
    }


def role_label(role: str) -> str:
    labels = {
        "owner": "Owner",
        "admin": "Administrador",
        "clinical": "Equipo clinico",
        "inventory": "Inventario",
    }
    return labels.get(role, role.title())


def role_permissions(role: str) -> dict:
    matrix = {
        "owner": {
            "view_inventory": True,
            "manage_inventory": True,
            "view_agenda": True,
            "manage_agenda": True,
            "view_clinical": True,
            "manage_clinical": True,
            "manage_admin": True,
        },
        "admin": {
            "view_inventory": True,
            "manage_inventory": True,
            "view_agenda": True,
            "manage_agenda": True,
            "view_clinical": True,
            "manage_clinical": True,
            "manage_admin": True,
        },
        "clinical": {
            "view_inventory": True,
            "manage_inventory": False,
            "view_agenda": True,
            "manage_agenda": True,
            "view_clinical": True,
            "manage_clinical": True,
            "manage_admin": False,
        },
        "inventory": {
            "view_inventory": True,
            "manage_inventory": True,
            "view_agenda": False,
            "manage_agenda": False,
            "view_clinical": False,
            "manage_clinical": False,
            "manage_admin": False,
        },
    }
    return matrix.get(
        role,
        {
            "view_inventory": False,
            "manage_inventory": False,
            "view_agenda": False,
            "manage_agenda": False,
            "view_clinical": False,
            "manage_clinical": False,
            "manage_admin": False,
        },
    )


def is_locked_until_active(value: str) -> bool:
    if not value:
        return False
    try:
        locked_until = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=UTC)
    return locked_until > datetime.now(UTC)


def is_expired(value: str) -> bool:
    if not value:
        return True
    try:
        expires_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)


def format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def requires_push_approval(role: str) -> bool:
    return role in PRIVILEGED_2FA_ROLES
