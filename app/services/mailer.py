from __future__ import annotations

import smtplib
from email.message import EmailMessage
import httpx

from app.core.config import get_settings


def smtp_is_configured() -> bool:
    settings = get_settings()
    return bool(settings.smtp_host and settings.smtp_from_email)


def sms_is_configured() -> bool:
    settings = get_settings()
    return bool(settings.sms_webhook_url)


def send_password_reset_email(*, to_email: str, reset_url: str) -> bool:
    settings = get_settings()
    if not smtp_is_configured():
        return False

    message = EmailMessage()
    message["Subject"] = "Velmorax | Restablecer clave"
    message["From"] = (
        f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
        if settings.smtp_from_name
        else settings.smtp_from_email
    )
    message["To"] = to_email
    message.set_content(
        "\n".join(
            [
                "Hola,",
                "",
                "Recibimos una solicitud para restablecer tu clave en Velmorax.",
                f"Usa este enlace: {reset_url}",
                "",
                "Si no solicitaste este cambio, puedes ignorar este mensaje.",
            ]
        )
    )

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)
    return True


def send_password_reset_sms(*, phone_number: str, reset_url: str) -> bool:
    settings = get_settings()
    if not sms_is_configured():
        return False

    payload = {
        "to": phone_number,
        "sender": settings.sms_sender_id,
        "message": (
            "Velmorax: recibimos una solicitud para restablecer tu clave. "
            f"Usa este enlace seguro: {reset_url}"
        ),
    }
    headers = {"Content-Type": "application/json"}
    if settings.sms_api_key:
        headers["Authorization"] = f"Bearer {settings.sms_api_key}"

    response = httpx.post(settings.sms_webhook_url, json=payload, headers=headers, timeout=30.0)
    response.raise_for_status()
    return True
