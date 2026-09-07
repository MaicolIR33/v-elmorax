from __future__ import annotations

from app.core.database import get_connection


PLAN_CATALOG = {
    "essential": {
        "name": "Esencial",
        "audience": "Consultorio y veterinaria pequeña",
        "monthly_price_cop": 89000,
        "annual_price_cop": 890000,
        "locations": 2,
        "users": 5,
        "support": "Soporte en horario hábil",
        "features": ["Operación clínica completa", "Agenda, tablero, alertas e insumos", "Copias y auditoría"],
    },
    "clinic": {
        "name": "Clínica",
        "audience": "Veterinaria mediana o con varias áreas",
        "monthly_price_cop": 199000,
        "annual_price_cop": 1990000,
        "locations": 3,
        "users": 20,
        "support": "Soporte prioritario",
        "features": ["Todo lo del plan Esencial", "Hasta 3 sedes", "Operación de urgencias y trazabilidad avanzada"],
    },
    "hospital": {
        "name": "Hospital y red",
        "audience": "Hospital 24/7, cadena o despliegue dedicado",
        "monthly_price_cop": 549000,
        "annual_price_cop": None,
        "locations": None,
        "users": None,
        "support": "Acuerdo de servicio y acompañamiento dedicado",
        "features": ["Capacidad ajustada al contrato", "Alta disponibilidad y monitoreo dedicado", "Migración e integraciones acordadas"],
    },
}


def list_commercial_plans() -> list[dict]:
    return [{"code": code, **plan} for code, plan in PLAN_CATALOG.items()]


def organization_subscription(organization_id: int) -> dict:
    with get_connection() as connection:
        organization = connection.execute(
            "SELECT id, name, plan_code, plan_status, billing_cycle FROM organizations WHERE id = ?",
            (organization_id,),
        ).fetchone()
        if organization is None:
            raise ValueError("La organización no existe.")
        active_locations = connection.execute(
            "SELECT COUNT(*) AS total FROM locations WHERE organization_id = ? AND is_active = 1",
            (organization_id,),
        ).fetchone()["total"]
        active_users = connection.execute(
            "SELECT COUNT(*) AS total FROM users WHERE organization_id = ? AND is_active = 1",
            (organization_id,),
        ).fetchone()["total"]

    code = organization["plan_code"] if organization["plan_code"] in PLAN_CATALOG else "essential"
    plan = PLAN_CATALOG[code]
    usage = {
        "locations": _usage(active_locations, plan["locations"]),
        "users": _usage(active_users, plan["users"]),
    }
    return {
        "organization_id": organization["id"],
        "organization_name": organization["name"],
        "code": code,
        "status": organization["plan_status"],
        "billing_cycle": organization["billing_cycle"],
        "plan": plan,
        "usage": usage,
        "clinical_continuity": "La atención y las urgencias nunca se bloquean por el plan.",
    }


def assert_capacity(organization_id: int, resource: str) -> None:
    subscription = organization_subscription(organization_id)
    usage = subscription["usage"][resource]
    if usage["limit"] is not None and usage["used"] >= usage["limit"]:
        label = "usuarios activos" if resource == "users" else "sedes activas"
        raise ValueError(
            f"El plan {subscription['plan']['name']} llegó a su capacidad de {label}. "
            "Puedes desactivar uno existente o solicitar una ampliación."
        )


def _usage(used: int, limit: int | None) -> dict:
    percent = 0 if limit is None else min(100, round((used / max(limit, 1)) * 100))
    return {"used": used, "limit": limit, "percent": percent, "near_limit": limit is not None and percent >= 80}
