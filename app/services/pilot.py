from __future__ import annotations

REQUIRED_METRICS = ("task_success_percent", "critical_errors", "availability_percent", "user_satisfaction_5", "training_completion_percent")


def evaluate_pilot(report: dict) -> dict:
    missing = [key for key in REQUIRED_METRICS if key not in report]
    if missing:
        return {"approved": False, "missing": missing, "failures": ["Faltan métricas obligatorias."], "score": 0}
    checks = {
        "Éxito de tareas menor a 95%": float(report["task_success_percent"]) >= 95,
        "Existen errores críticos sin resolver": int(report["critical_errors"]) == 0,
        "Disponibilidad menor a 99,5%": float(report["availability_percent"]) >= 99.5,
        "Satisfacción menor a 4/5": float(report["user_satisfaction_5"]) >= 4,
        "Capacitación menor a 90%": float(report["training_completion_percent"]) >= 90,
    }
    failures = [message for message, passed in checks.items() if not passed]
    score = round(sum(checks.values()) / len(checks) * 100)
    return {"approved": not failures, "missing": [], "failures": failures, "score": score}
