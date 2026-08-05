import os
from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "Velmorax"
    app_description: str = (
        "Sistema web para inventario inteligente, agenda y registro clinico "
        "adaptable a odontologia, veterinaria y otras especialidades."
    )
    app_version: str = "0.1.0"
    app_env: str = "development"
    session_secret: str = "velmorax-dev-secret"
    session_max_age_seconds: int = 60 * 60 * 24 * 30
    session_idle_timeout_minutes: int = 90
    session_remember_idle_days: int = 14
    session_https_only: bool = False
    show_demo_access: bool = True
    database_url: str = "sqlite:///data/velmorax.db"
    default_entry_flow: str = "general"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_from_email: str = ""
    smtp_from_name: str = "Velmorax"
    sms_webhook_url: str = ""
    sms_api_key: str = ""
    sms_sender_id: str = "Velmorax"
    public_base_url: str = "http://127.0.0.1:8000"


@lru_cache
def get_settings() -> Settings:
    app_env = os.getenv("APP_ENV", "development")
    show_demo_default = "0" if app_env.lower() == "production" else "1"
    https_default = "1" if app_env.lower() == "production" else "0"
    return Settings(
        app_env=app_env,
        session_secret=os.getenv("SESSION_SECRET", "velmorax-dev-secret"),
        session_max_age_seconds=int(os.getenv("SESSION_MAX_AGE_SECONDS", str(60 * 60 * 24 * 30))),
        session_idle_timeout_minutes=int(os.getenv("SESSION_IDLE_TIMEOUT_MINUTES", "90")),
        session_remember_idle_days=int(os.getenv("SESSION_REMEMBER_IDLE_DAYS", "14")),
        session_https_only=os.getenv("SESSION_HTTPS_ONLY", https_default) in {"1", "true", "True"},
        show_demo_access=os.getenv("SHOW_DEMO_ACCESS", show_demo_default) in {"1", "true", "True"},
        database_url=os.getenv("DATABASE_URL", "sqlite:///data/velmorax.db"),
        default_entry_flow=os.getenv("DEFAULT_ENTRY_FLOW", "general"),
        smtp_host=os.getenv("SMTP_HOST", ""),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_username=os.getenv("SMTP_USERNAME", ""),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_use_tls=os.getenv("SMTP_USE_TLS", "1") in {"1", "true", "True"},
        smtp_from_email=os.getenv("SMTP_FROM_EMAIL", ""),
        smtp_from_name=os.getenv("SMTP_FROM_NAME", "Velmorax"),
        sms_webhook_url=os.getenv("SMS_WEBHOOK_URL", "").strip(),
        sms_api_key=os.getenv("SMS_API_KEY", "").strip(),
        sms_sender_id=os.getenv("SMS_SENDER_ID", "Velmorax").strip() or "Velmorax",
        public_base_url=os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
    )
