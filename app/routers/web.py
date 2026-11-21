import csv
import json
import re
import sqlite3
import tempfile
from io import StringIO
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.core.database import get_connection, get_database_dialect, get_database_url, sqlite_db_path
from app.services.appointments import (
    appointment_summary,
    appointment_belongs_to_scope,
    create_appointment,
    create_appointment_block,
    create_appointment_resource,
    create_recurring_appointments,
    create_waitlist_entry,
    delete_appointment,
    list_appointment_resources,
    list_appointments_between,
    list_waitlist,
    notify_waitlist_of_opening,
    reschedule_appointment,
    update_appointment as update_appointment_record,
    update_appointment_status,
)
from app.services.alerts import (
    acknowledge_alert, alert_belongs_to_scope, create_alert, delete_alert, list_alerts,
    list_resolved_alerts, resolve_alert, snooze_alert, update_alert,
)
from app.services.auth import (
    authenticate_user,
    consume_password_reset_token,
    create_user,
    create_password_reset_token,
    get_user_by_id,
    get_user_by_email,
    legacy_sha256_hash,
    login_lock_message,
    list_users,
    mark_password_change_completed,
    register_failed_login,
    requires_push_approval,
    reset_failed_login,
    role_label,
    role_permissions,
    effective_permissions,
    set_user_active,
    update_user,
    update_user_permissions,
    update_user_schedule,
)
from app.services.clinical import (
    create_clinical_record,
    create_patient,
    delete_clinical_record,
    delete_patient_history,
    delete_patient,
    find_patient_duplicate,
    get_clinical_record,
    get_patient,
    list_clinical_records,
    list_patients,
    patient_preventive_dates,
    update_patient,
    update_clinical_record_status,
)
from app.services.clinical_pdf import build_patient_history_pdf
from app.services.commercial import assert_capacity, list_commercial_plans, organization_subscription
from app.services.dashboard import (
    create_shift_handoff, get_dashboard_context, get_dashboard_preferences, save_dashboard_preferences,
    save_dashboard_role_preferences,
)
from app.services.inventory import (
    count_inventory_item,
    create_inventory_replenishment,
    create_inventory_item,
    create_inventory_movement,
    delete_inventory_item,
    inventory_item_belongs_to_scope,
    list_inventory_items,
    list_recent_movements,
    record_cold_chain,
    review_inventory_replenishment,
    retire_inventory_lot,
    set_inventory_quarantine,
    transfer_inventory_item,
    update_inventory_item,
)
from app.services.integrations import enqueue_integration_event, integration_outbox_summary, integration_readiness
from app.services.legal import legal_context, record_legal_acceptance
from app.services.mailer import (
    send_password_reset_email,
    send_password_reset_sms,
    smtp_is_configured,
    sms_is_configured,
)
from app.services.network import (
    create_location,
    create_organization,
    entry_flows,
    get_app_settings,
    get_location_by_id,
    import_organization_location_catalog,
    list_locations,
    list_organizations,
    log_audit_event,
    module_path_for_intent,
    search_location_candidates,
    save_app_settings,
    set_location_active,
    list_recent_activity,
    sync_official_national_catalog,
    sync_official_odontology_catalog,
    sync_official_veterinary_catalog,
    update_location,
    update_organization,
)


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()
SESSION_IDLE_TIMEOUT = timedelta(minutes=settings.session_idle_timeout_minutes)
SESSION_REMEMBER_TIMEOUT = timedelta(days=settings.session_remember_idle_days)


def current_user_from_request(request: Request) -> dict | None:
    last_seen_raw = request.session.get("last_seen_at")
    if last_seen_raw:
        try:
            last_seen = datetime.fromisoformat(last_seen_raw)
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=UTC)
            idle_timeout = SESSION_REMEMBER_TIMEOUT if request.session.get("remember_me") else SESSION_IDLE_TIMEOUT
            if datetime.now(UTC) - last_seen > idle_timeout:
                request.session.clear()
                request.session["login_notice"] = "Tu sesion vencio por inactividad. Vuelve a ingresar."
                request.session["login_notice_type"] = "error"
                return None
        except ValueError:
            request.session.clear()
            request.session["login_notice"] = "Tu sesion ya no es valida. Ingresa de nuevo."
            request.session["login_notice_type"] = "error"
            return None
    user_id = request.session.get("user_id")
    user = get_user_by_id(user_id)
    if user:
        request.session["last_seen_at"] = datetime.now(UTC).isoformat()
    return user


def redirect_to_login(intent: str = "") -> RedirectResponse:
    suffix = f"?intent={intent}" if intent else ""
    return RedirectResponse(url=f"/login{suffix}", status_code=303)


def complete_login_session(
    request: Request,
    *,
    user: dict,
    selected_intent: str,
    effective_organization_id: str,
    effective_location_id: str,
    remember_me: bool,
    accepted_legal: bool = False,
) -> RedirectResponse:
    request.session["user_id"] = user["id"]
    request.session["entry_intent"] = selected_intent
    request.session["preferred_organization_id"] = effective_organization_id
    request.session["preferred_location_id"] = effective_location_id
    request.session["last_seen_at"] = datetime.now(UTC).isoformat()
    request.session["remember_me"] = remember_me

    if accepted_legal:
        record_legal_acceptance(
            user_id=user["id"],
            organization_id=user["organization_id"],
            remote_address=request.client.host if request.client else "unknown",
            user_agent=request.headers.get("user-agent", "unknown"),
        )

    if user.get("must_change_password"):
        token = create_password_reset_token(user["email"])
        if token:
            return RedirectResponse(
                url=f"/password-reset/confirm?token={token}&success={encoded_message('Debes definir una nueva clave antes de continuar.')}",
                status_code=303,
            )

    permissions = role_permissions(user["role"])
    destination = module_path_for_intent(selected_intent, permissions)
    scope_query = build_scope_query(
        organization_id=effective_organization_id,
        location_id=effective_location_id,
    )
    return RedirectResponse(
        url=f"{destination}?{scope_query}" if scope_query else destination,
        status_code=303,
    )


def redirect_to_module_with_error(path: str, message: str) -> RedirectResponse:
    return RedirectResponse(url=f"{path}?permission_error={message}", status_code=303)


def user_with_permissions(request: Request) -> dict | None:
    user = current_user_from_request(request)
    if user is None:
        return None
    return {**user, "permissions": effective_permissions(user)}


def inventory_scope_allowed(user: dict, organization_id: int, location_id: int) -> bool:
    if int(user.get("organization_id") or 0) != int(organization_id or 0):
        return False
    location = get_location_by_id(str(location_id)) if location_id else None
    return bool(location and int(location["organization_id"]) == int(organization_id))


def inventory_item_scope_allowed(user: dict, item_id: int, organization_id: int, location_id: int) -> bool:
    return inventory_scope_allowed(user, organization_id, location_id) and inventory_item_belongs_to_scope(
        item_id, organization_id, location_id
    )


def build_scope_query(organization_id: str = "", location_id: str = "", day: str = "") -> str:
    parts: list[str] = []
    if organization_id:
        parts.append(f"organization_id={organization_id}")
    if location_id:
        parts.append(f"location_id={location_id}")
    if day:
        parts.append(f"day={day}")
    return "&".join(parts)


def align_scope_to_entry_intent(
    intent: str,
    organization_id: str,
    location_id: str,
) -> tuple[str, str]:
    expected_catalog = {
        "odontologia": "odontologia",
        "veterinaria": "veterinaria",
        "consulta-general": "consulta-general",
    }.get(intent)
    if not expected_catalog:
        return organization_id, location_id

    selected_location = get_location_by_id(location_id) if location_id else None
    if selected_location and selected_location.get("catalog_kind") == expected_catalog:
        return str(selected_location["organization_id"]), str(selected_location["id"])

    candidates = list_locations(organization_id) if organization_id else list_locations()
    matching_location = next(
        (item for item in candidates if item.get("catalog_kind") == expected_catalog),
        None,
    )
    if matching_location is None and organization_id:
        matching_location = next(
            (
                item
                for item in list_locations()
                if item.get("catalog_kind") == expected_catalog
            ),
            None,
        )
    if matching_location:
        return str(matching_location["organization_id"]), str(matching_location["id"])
    return organization_id, ""


def encoded_message(value: str) -> str:
    return quote(value, safe="")


def minimum_password_length(organization_id: int, *, default: int = 10) -> int:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT settings_json FROM organization_preferences WHERE organization_id = ?",
            (organization_id,),
        ).fetchone()
    try:
        value = int(json.loads(row["settings_json"]).get("password_min_length", default)) if row and row["settings_json"] else default
    except (TypeError, ValueError, AttributeError):
        value = default
    return value if value in {10, 12, 14} else default


def context_for_authenticated_user(
    request: Request,
    *,
    search: str = "",
    category: str = "",
    status: str = "",
    day: str = "",
    organization_id: str = "",
    location_id: str = "",
    item_type: str = "",
    storage_area: str = "",
    supplier: str = "",
    expiry: str = "",
    period: str = "",
    date_from: str = "",
    date_to: str = "",
    agenda_status: str = "",
    veterinarian_filter: str = "",
    priority_filter: str = "",
    appointment_status_filter: str = "",
    agenda_view: str = "day",
    agenda_veterinarian: str = "",
    agenda_priority: str = "",
    agenda_channel: str = "",
    history_span: str = "week",
    active_path: str = "/",
) -> tuple[dict, dict] | tuple[None, None]:
    user = user_with_permissions(request)
    if user is None:
        return None, None

    session_organization_id = request.session.get("preferred_organization_id", "")
    session_location_id = request.session.get("preferred_location_id", "")
    effective_organization_id = organization_id or session_organization_id
    effective_location_id = location_id or session_location_id
    entry_intent = request.session.get("entry_intent", "")
    effective_organization_id, effective_location_id = align_scope_to_entry_intent(
        entry_intent,
        effective_organization_id,
        effective_location_id,
    )

    context = get_dashboard_context(
        search=search,
        category=category,
        status=status,
        day=day,
        organization_id=effective_organization_id,
        location_id=effective_location_id,
        item_type=item_type,
        storage_area=storage_area,
        supplier=supplier,
        expiry=expiry,
        period=period,
        date_from=date_from,
        date_to=date_to,
        user_role=user["role"],
        user_id=user["id"],
        veterinarian_filter=veterinarian_filter,
        priority_filter=priority_filter,
        appointment_status_filter=appointment_status_filter,
        history_span=history_span,
    )
    request.session["preferred_organization_id"] = context["scope"]["organization_id"]
    request.session["preferred_location_id"] = context["scope"]["location_id"]
    context["request"] = request
    context["current_user"] = {**user, "role_label": role_label(user["role"])}
    context["permissions"] = user["permissions"]
    if agenda_status:
        context["appointments"] = [item for item in context["appointments"] if item["status"] == agenda_status]
    context["agenda_status_filter"] = agenda_status
    context["active_path"] = active_path
    context["entry_intent"] = entry_intent
    context["is_veterinary_flow"] = entry_intent == "veterinaria"
    context["is_veterinary_dashboard"] = (
        active_path == "/" and context["is_veterinary_flow"]
    )
    if context["is_veterinary_flow"]:
        veterinary_locations = [
            item for item in list_locations() if item.get("catalog_kind") == "veterinaria"
        ]
        veterinary_organization_ids = {
            item["organization_id"] for item in veterinary_locations
        }
        context["scope"]["organizations"] = [
            item
            for item in context["scope"]["organizations"]
            if item["id"] in veterinary_organization_ids
        ]
        context["scope"]["locations"] = [
            item
            for item in context["scope"]["locations"]
            if item.get("catalog_kind") == "veterinaria"
        ]
        context["inventory_transfer_locations"] = [
            item for item in context["scope"]["locations"]
            if str(item["organization_id"]) == str(context["scope"]["organization_id"])
            and str(item["id"]) != str(context["scope"]["location_id"])
        ]
        context["appointments"] = [
            item for item in context["appointments"] if item["specialty"] == "Veterinaria"
        ]
        context["patient_queue"] = [
            {
                "name": item["patient"],
                "channel": item["channel"],
                "reason": item["service"],
                "priority": "Alta" if item["status"] == "En espera" else "Media",
                "site_name": item["site_name"],
            }
            for item in context["appointments"] if item["status"] == "En consulta"
        ]
        context["specialty_tabs"] = [
            item for item in context["specialty_tabs"] if item["id"] == "vet"
        ]
        context["daily_financial_summary"]["specialties"] = [
            item
            for item in context["daily_financial_summary"]["specialties"]
            if item["key"] == "Veterinaria"
        ]
        context["appointment_form_defaults"]["specialty"] = "Veterinaria"
        context["appointment_form_defaults"]["status"] = "Pendiente"
        context["patient_form_defaults"].update(
            patient_type="Animal",
            specialty="Veterinaria",
            vaccine_status="Pendiente",
        )
        context["clinical_form_defaults"]["specialty"] = "Veterinaria"
        context["inventory_form_defaults"].update(
            regulatory_agency="ICA",
            category="Veterinaria",
            location="Nevera A",
        )
    if active_path == "/agenda":
        selected = datetime.fromisoformat(context["agenda_day"]).date()
        normalized_view = agenda_view if agenda_view in {"day", "week", "month"} else "day"
        if normalized_view == "week":
            range_start = selected - timedelta(days=selected.weekday())
            range_end = range_start + timedelta(days=6)
        elif normalized_view == "month":
            range_start = selected.replace(day=1)
            next_month = (range_start.replace(day=28) + timedelta(days=4)).replace(day=1)
            range_end = next_month - timedelta(days=1)
        else:
            range_start = range_end = selected
        agenda_items = list_appointments_between(range_start.isoformat(), range_end.isoformat(), context["scope"]["organization_id"], context["scope"]["location_id"])
        if context["is_veterinary_flow"]:
            agenda_items = [item for item in agenda_items if item["specialty"] == "Veterinaria"]
        if agenda_status:
            agenda_items = [item for item in agenda_items if item["status"] == agenda_status]
        if agenda_veterinarian.isdigit():
            agenda_items = [item for item in agenda_items if item.get("veterinarian_user_id") == int(agenda_veterinarian)]
        if agenda_priority:
            agenda_items = [item for item in agenda_items if item.get("priority") == agenda_priority]
        if agenda_channel:
            agenda_items = [item for item in agenda_items if item.get("channel") == agenda_channel]
        context["appointments"] = agenda_items
        context["agenda_summary"] = appointment_summary(agenda_items)
        context["agenda_view"] = normalized_view
        context["agenda_filters"] = {"veterinarian": agenda_veterinarian, "priority": agenda_priority, "channel": agenda_channel, "status": agenda_status}
        context["agenda_range"] = {"start": range_start.isoformat(), "end": range_end.isoformat()}
        context["agenda_days"] = [{"date": (range_start + timedelta(days=index)).isoformat(), "label": (range_start + timedelta(days=index)).strftime("%a %d"), "appointments": [item for item in agenda_items if item["date"] == (range_start + timedelta(days=index)).isoformat()]} for index in range((range_end - range_start).days + 1)]
        context["agenda_resources"] = list_appointment_resources(context["scope"]["organization_id"], context["scope"]["location_id"])
        context["agenda_waitlist"] = list_waitlist(context["scope"]["organization_id"], context["scope"]["location_id"])
    context["scope_query"] = build_scope_query(
        context["scope"]["organization_id"],
        context["scope"]["location_id"],
    )
    return context, user


def _patient_age_label(birth_date: str | None) -> str:
    if not birth_date:
        return "Edad sin registrar"
    try:
        born = date.fromisoformat(birth_date[:10])
        today = date.today()
    except (TypeError, ValueError):
        return "Edad sin registrar"
    if born > today:
        return "Fecha de nacimiento futura"
    months = (today.year - born.year) * 12 + today.month - born.month - (today.day < born.day)
    if months < 1:
        return "Menos de un mes"
    years, remaining_months = divmod(months, 12)
    if years and remaining_months:
        return f"{years} a, {remaining_months} m"
    if years:
        return f"{years} {('año' if years == 1 else 'años')}"
    return f"{remaining_months} {('mes' if remaining_months == 1 else 'meses')}"


def _has_actionable_clinical_value(value: str | None) -> bool:
    normalized = " ".join(str(value or "").casefold().strip().split())
    if not normalized:
        return False
    return not normalized.startswith(("sin ", "no ", "ninguna", "ninguno", "n/a", "na ", "no aplica")) and normalized not in {"-", "n/a", "na"}


def _build_patient_directory(
    patients: list[dict], preventive_dates: dict[int, str], *,
    search: str = "", status_filter: str = "", species_filter: str = "",
    prevention_filter: str = "", alerts_only: bool = False, page: int = 1,
) -> dict:
    today = date.today()
    species_options = sorted({str(item.get("species") or "").strip() for item in patients if str(item.get("species") or "").strip()}, key=str.casefold)
    query = search.strip().casefold()
    filtered = []
    for original in patients:
        patient = dict(original)
        due_raw = preventive_dates.get(int(patient["id"]), "")
        try:
            due = date.fromisoformat(due_raw[:10]) if due_raw else None
        except (TypeError, ValueError):
            due = None
        patient["next_vaccine_due"] = due_raw
        patient["age_label"] = _patient_age_label(patient.get("birth_date"))
        patient["vaccine_due_state"] = "overdue" if due and due <= today else "upcoming" if due and (due - today).days <= 30 else ""
        deworming = str(patient.get("deworming_status") or "").casefold()
        deworm_due_raw = str(patient.get("next_deworming_due") or "")
        try:
            deworm_due = date.fromisoformat(deworm_due_raw[:10]) if deworm_due_raw else None
        except (TypeError, ValueError):
            deworm_due = None
        patient["next_deworming_due"] = deworm_due_raw
        patient["deworming_due_state"] = "overdue" if deworm_due and deworm_due <= today else "upcoming" if deworm_due and (deworm_due - today).days <= 30 else ""
        vaccine_status = str(patient.get("vaccine_status") or "").casefold()
        patient["allergies_actionable"] = _has_actionable_clinical_value(patient.get("allergies"))
        patient["clinical_alert_actionable"] = _has_actionable_clinical_value(patient.get("clinical_alert"))
        patient["conditions_actionable"] = _has_actionable_clinical_value(patient.get("preexisting_conditions"))
        allergy_or_alert = patient["allergies_actionable"] or patient["clinical_alert_actionable"] or patient["conditions_actionable"]
        patient["has_clinical_alert"] = allergy_or_alert
        patient["deworming_pending"] = bool(patient["deworming_due_state"]) or any(word in deworming for word in ("pend", "venc", "atras"))
        patient["vaccine_pending"] = bool(patient["vaccine_due_state"]) or any(word in vaccine_status for word in ("pend", "venc", "seguimiento"))
        if query and not any(query in str(patient.get(key) or "").casefold() for key in ("display_name", "species", "breed", "owner_name", "phone", "microchip")):
            continue
        status = str(patient.get("patient_status") or "active").casefold()
        if status_filter and status != status_filter:
            continue
        if species_filter and str(patient.get("species") or "").casefold() != species_filter.casefold():
            continue
        if alerts_only and not allergy_or_alert:
            continue
        if prevention_filter == "vaccine" and not patient["vaccine_pending"]:
            continue
        if prevention_filter == "deworming" and not patient["deworming_pending"]:
            continue
        filtered.append(patient)

    per_page = 20
    total = len(filtered)
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(1, page), pages)
    # Keep active search facets in pager URLs; scope is appended by the template.
    params = [(key, value) for key, value in (("q", search.strip()), ("patient_status", status_filter), ("species", species_filter), ("prevention", prevention_filter), ("alerts", "1" if alerts_only else "")) if value]
    return {
        "items": filtered[(page - 1) * per_page:page * per_page],
        "total": total,
        "page": page,
        "pages": pages,
        "page_query": urlencode(params),
        "species_options": species_options,
        "filters": {"q": search.strip(), "status": status_filter, "species": species_filter, "prevention": prevention_filter, "alerts": alerts_only},
    }


def render_authenticated_page(
    request: Request,
    template_name: str,
    *,
    saved: int = 0,
    moved: int = 0,
    appointment_saved: int = 0,
    appointment_updated: int = 0,
    patient_saved: int = 0,
    record_saved: int = 0,
    movement_error: str = "",
    permission_error: str = "",
    agenda_error: str = "",
    search: str = "",
    category: str = "",
    status: str = "",
    day: str = "",
    organization_id: str = "",
    location_id: str = "",
    item_type: str = "",
    storage_area: str = "",
    supplier: str = "",
    expiry: str = "",
    period: str = "",
    date_from: str = "",
    date_to: str = "",
    agenda_status: str = "",
    veterinarian_filter: str = "",
    priority_filter: str = "",
    appointment_status_filter: str = "",
    agenda_view: str = "day",
    agenda_veterinarian: str = "",
    agenda_priority: str = "",
    agenda_channel: str = "",
    history_span: str = "week",
    active_path: str = "/",
    record_patient_id: int = 0,
    patient_history_view: bool = False,
    patient_search: str = "",
    patient_status_filter: str = "",
    patient_species_filter: str = "",
    patient_prevention_filter: str = "",
    patient_alerts_only: bool = False,
    patient_page: int = 1,
    extra_context: dict | None = None,
):
    context, user = context_for_authenticated_user(
        request,
        search=search,
        category=category,
        status=status,
        day=day,
        organization_id=organization_id,
        location_id=location_id,
        item_type=item_type,
        storage_area=storage_area,
        supplier=supplier,
        expiry=expiry,
        period=period,
        date_from=date_from,
        date_to=date_to,
        agenda_status=agenda_status,
        veterinarian_filter=veterinarian_filter,
        priority_filter=priority_filter,
        appointment_status_filter=appointment_status_filter,
        agenda_view=agenda_view,
        agenda_veterinarian=agenda_veterinarian,
        agenda_priority=agenda_priority,
        agenda_channel=agenda_channel,
        history_span=history_span,
        active_path=active_path,
    )
    if context is None:
        return None

    if template_name == "clinical.html":
        preventive_dates = patient_preventive_dates(
            context["scope"]["organization_id"], context["scope"]["location_id"]
        )
        directory = _build_patient_directory(
            context["patients"], preventive_dates,
            search=patient_search, status_filter=patient_status_filter,
            species_filter=patient_species_filter, prevention_filter=patient_prevention_filter,
            alerts_only=patient_alerts_only, page=patient_page,
        )
        context["patient_directory"] = directory["items"]
        context["patient_directory_total"] = directory["total"]
        context["patient_directory_page"] = directory["page"]
        context["patient_directory_pages"] = directory["pages"]
        context["patient_directory_query"] = directory["page_query"]
        context["patient_species_options"] = directory["species_options"]
        context["patient_filters"] = directory["filters"]

    context["saved"] = saved
    context["moved"] = moved
    context["appointment_saved"] = appointment_saved
    context["appointment_updated"] = appointment_updated
    context["patient_saved"] = patient_saved
    context["record_saved"] = record_saved
    context["movement_error"] = movement_error
    context["permission_error"] = permission_error
    context["agenda_error"] = agenda_error
    selected_patient = next(
        (
            item
            for item in context["patients"]
            if item["id"] == record_patient_id
        ),
        None,
    )
    if selected_patient is not None:
        context["clinical_records"] = list_clinical_records(
            limit=100,
            organization_id=context["scope"]["organization_id"],
            location_id=context["scope"]["location_id"],
            patient_id=record_patient_id,
        )
        context["selected_patient"] = selected_patient
        context["selected_patient_id"] = record_patient_id
        context["selected_patient_age"] = _patient_age_label(selected_patient.get("birth_date"))
        weighted_records = [item for item in context["clinical_records"] if item.get("current_weight_kg") and float(item["current_weight_kg"]) > 0]
        weighted_records = sorted(weighted_records, key=lambda item: str(item.get("encounter_date") or ""))[-12:]
        weights = [float(item["current_weight_kg"]) for item in weighted_records]
        low, high = (min(weights), max(weights)) if weights else (0, 0)
        span = high - low or 1
        chart_points = []
        for index, item in enumerate(weighted_records):
            x = 24 + (352 * index / max(1, len(weighted_records) - 1))
            y = 104 - ((float(item["current_weight_kg"]) - low) / span * 68)
            chart_points.append({"x": round(x, 1), "y": round(y, 1), "weight": item["current_weight_kg"], "date": item.get("encounter_date") or ""})
        context["patient_weight_points"] = chart_points
    else:
        context["selected_patient"] = None
        context["selected_patient_id"] = 0
        context["patient_weight_points"] = []
    context["patient_history_view"] = bool(patient_history_view and selected_patient)
    if extra_context:
        context.update(extra_context)
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=context,
    )


def build_daily_summary_csv(context: dict) -> str:
    output = StringIO()
    writer = csv.writer(output)
    summary = context["daily_financial_summary"]
    scope = context["scope"]

    writer.writerow(["Velmorax - Cierre diario"])
    writer.writerow(["Fecha", summary["date"]])
    writer.writerow(["Contexto", scope["scope_label"]])
    writer.writerow([])
    writer.writerow(["Resumen por especialidad"])
    writer.writerow(["Especialidad", "Pacientes", "Pagaron", "Total recogido"])
    for item in summary["specialties"]:
        writer.writerow(
            [
                item["label"],
                item["patients_total"],
                item["paying_patients"],
                f"{item['total_collected']:.0f}",
            ]
        )

    writer.writerow([])
    writer.writerow(
        [
            "Total general",
            summary["patients_total"],
            summary["paying_patients"],
            f"{summary['total_collected']:.0f}",
        ]
    )

    writer.writerow([])
    writer.writerow(["Resumen por medio de pago"])
    writer.writerow(["Medio", "Atenciones", "Total"])
    for item in summary["by_payment_method"]:
        writer.writerow([item["label"], item["count"], f"{item['total_collected']:.0f}"])

    writer.writerow([])
    writer.writerow(["Resumen por profesional"])
    writer.writerow(["Profesional", "Atenciones", "Total"])
    for item in summary["by_professional"]:
        writer.writerow([item["label"], item["count"], f"{item['total_collected']:.0f}"])
    writer.writerow([])
    writer.writerow(["Detalle de atenciones del dia"])
    writer.writerow(
        [
            "Fecha",
            "Especialidad",
            "Paciente",
            "Motivo",
            "Profesional",
            "Estado",
            "Pago",
            "Medio de pago",
            "Sede",
        ]
    )
    for record in context["clinical_records"]:
        if record["encounter_date"] != summary["date"]:
            continue
        writer.writerow(
            [
                record["encounter_date"],
                record["specialty"],
                record["display_name"],
                record["reason"],
                record["professional"],
                record["status"],
                f"{float(record['payment_amount'] or 0):.0f}",
                record["payment_method"],
                record["site_name"],
            ]
        )

    return output.getvalue()


def build_inventory_csv(items: list[dict]) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Producto",
            "Categoria",
            "Marca",
            "Proveedor",
            "Registro",
            "Lote",
            "Cantidad",
            "Stock minimo",
            "Costo",
            "Precio",
            "Cadena de frio",
            "Condicion",
            "Area",
            "Vencimiento",
            "Sede",
            "Estado del lote",
            "Cuarentena",
            "Solicitud de abastecimiento",
        ]
    )
    for item in items:
        writer.writerow(
            [
                item["name"],
                item["category"],
                item["brand"],
                item["supplier"],
                item["regulatory_code"],
                item["lot"],
                item["quantity"],
                item["min_stock"],
                f"{item['unit_cost']:.2f}",
                f"{item['sale_price']:.2f}",
                "Si" if item["requires_cold_chain"] else "No",
                item["storage_condition"],
                item["location"],
                item["expiry_date"],
                item["site_name"],
                item["lot_status"],
                item["quarantine_reason"] if item["is_quarantined"] else "No",
                item["replenishment_request_id"] or "",
            ]
        )
    return output.getvalue()


def build_inventory_movements_csv(movements: list[dict]) -> str:
    """Exportable audit trail for clinical and stock operations."""
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Fecha", "Producto", "Lote", "Operación", "Motivo", "Cantidad", "Antes", "Después",
        "Paciente", "Cita", "Prioridad", "Referencia externa", "Sede relacionada",
        "Referencia traslado", "Responsable", "Nota",
    ])
    for movement in movements:
        writer.writerow([
            movement["created_at"], movement["item_name"], movement["lot"], movement["direction"],
            movement["reason_type"], movement["quantity"], movement["stock_before"], movement["stock_after"],
            movement["patient_name"] or "", movement["appointment_label"] or "", movement["priority"],
            movement["external_reference"] or "", movement["counterparty_location_name"] or "",
            movement["transfer_reference"] or "", movement["responsible_name"], movement["note"],
        ])
    return output.getvalue()


def build_activity_csv(items: list[dict]) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Fecha", "Usuario", "Accion", "Entidad", "Etiqueta", "Detalle", "Organizacion", "Sede"])
    for item in items:
        writer.writerow(
            [
                item["created_at"],
                item["user_name"],
                item["action"],
                item["entity_type"],
                item["entity_label"],
                item["detail"],
                item["organization_name"],
                item["location_name"],
            ]
        )
    return output.getvalue()


def build_backup_snapshot() -> bytes:
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "database": get_database_dialect(),
        "files": {},
    }
    data_dir = Path("data")
    if data_dir.exists():
        for path in sorted(data_dir.glob("*.db")):
            payload["files"][path.name] = {"size": path.stat().st_size}
    return json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8")


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    error: str = "",
    success: str = "",
    intent: str = Query(default=""),
    organization_id: str = Query(default=""),
    location_id: str = Query(default=""),
) -> HTMLResponse:
    user = current_user_from_request(request)
    if user:
        return RedirectResponse(url="/", status_code=303)

    # La pantalla de acceso inicial es siempre la selección de flujo. El flujo
    # solo se conserva cuando viene explícitamente en la URL (por ejemplo,
    # desde la página pública de Veterinaria o después de un error de acceso).
    selected_intent = intent
    enabled_intents = {
        flow["id"] for flow in entry_flows() if flow.get("enabled", True)
    }
    if selected_intent not in enabled_intents:
        selected_intent = ""
    selected_organization_id = organization_id or request.session.get("preferred_organization_id", "")
    selected_location_id = location_id or request.session.get("preferred_location_id", "")
    if selected_intent:
        request.session["entry_intent"] = selected_intent
    if selected_organization_id:
        request.session["preferred_organization_id"] = selected_organization_id
    if selected_location_id:
        request.session["preferred_location_id"] = selected_location_id

    session_notice = request.session.pop("login_notice", "")
    session_notice_type = request.session.pop("login_notice_type", "")
    effective_error = error or (session_notice if session_notice_type == "error" else "")
    effective_success = success or (session_notice if session_notice_type == "success" else "")
    selected_location = get_location_by_id(selected_location_id) if selected_location_id else None

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "request": request,
            "error": effective_error,
            "success": effective_success,
            "selected_intent": selected_intent,
            "selected_organization_id": selected_organization_id,
            "selected_location_id": selected_location_id,
            "selected_location": selected_location,
            "show_demo_access": settings.show_demo_access,
            "entry_flows": entry_flows(),
            "demo_users": [
                {"email": "admin@velmorax.local", "role": "Administrador"},
                {"email": "clinica@velmorax.local", "role": "Equipo clinico"},
                {"email": "inventario@velmorax.local", "role": "Inventario"},
            ],
            "legal": legal_context(),
        },
    )


@router.get("/veterinaria", response_class=HTMLResponse)
async def veterinary_landing_page(request: Request) -> HTMLResponse:
    """Public entry page for the veterinary experience."""
    return templates.TemplateResponse(
        request=request,
        name="veterinary_landing.html",
        context={
            "request": request,
            "current_user": current_user_from_request(request),
        },
    )


@router.get("/privacidad", response_class=HTMLResponse)
async def privacy_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="legal.html",
        context={"request": request, "document": "privacy", "legal": legal_context()},
    )


@router.get("/planes", response_class=HTMLResponse)
async def plans_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="plans.html",
        context={"request": request, "plans": list_commercial_plans(), "legal": legal_context()},
    )


@router.get("/ayuda", response_class=HTMLResponse)
async def help_page(request: Request) -> HTMLResponse:
    context, user = context_for_authenticated_user(request, active_path="/ayuda")
    if context is None:
        return redirect_to_login("veterinaria")
    context.update({"support": get_app_settings(), "help_role": user["role"]})
    return templates.TemplateResponse(request=request, name="help.html", context=context)


@router.get("/tratamiento-de-datos", response_class=HTMLResponse)
async def data_policy_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="legal.html",
        context={"request": request, "document": "data", "legal": legal_context()},
    )


@router.get("/terminos", response_class=HTMLResponse)
async def terms_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="legal.html",
        context={"request": request, "document": "terms", "legal": legal_context()},
    )


@router.get("/password-reset", response_class=HTMLResponse)
async def password_reset_request_page(
    request: Request,
    error: str = "",
    success: str = "",
    intent: str = Query(default=""),
) -> HTMLResponse:
    enabled_intents = {flow["id"] for flow in entry_flows() if flow.get("enabled", True)}
    selected_intent = intent if intent in enabled_intents else ""
    login_url = f"/login?intent={selected_intent}" if selected_intent else "/login"
    return templates.TemplateResponse(
        request=request,
        name="password_reset_request.html",
        context={
            "request": request,
            "error": error,
            "success": success,
            "email_enabled": smtp_is_configured(),
            "sms_enabled": sms_is_configured(),
            "selected_intent": selected_intent,
            "login_url": login_url,
        },
    )


@router.post("/password-reset")
async def password_reset_request_action(
    request: Request,
    email: str = Form(...),
    method: str = Form("email"),
    phone: str = Form(""),
    intent: str = Query(default=""),
) -> RedirectResponse:
    enabled_intents = {flow["id"] for flow in entry_flows() if flow.get("enabled", True)}
    selected_intent = intent if intent in enabled_intents else ""
    intent_suffix = f"&intent={selected_intent}" if selected_intent else ""
    requested_user = get_user_by_email(email.strip())
    if requested_user is not None:
        with get_connection() as connection:
            preference_row = connection.execute(
                "SELECT settings_json FROM organization_preferences WHERE organization_id = ?",
                (int(requested_user["organization_id"]),),
            ).fetchone()
        try:
            recovery_channel = json.loads(preference_row["settings_json"]).get("recovery_channel", "email") if preference_row else "email"
        except (TypeError, ValueError):
            recovery_channel = "email"
        if recovery_channel == "admin":
            return RedirectResponse(
                url=f"/password-reset?success={encoded_message('Si la cuenta existe, un administrador autorizado podrá ayudar a restablecer el acceso.')}{intent_suffix}",
                status_code=303,
            )
    token = create_password_reset_token(email.strip())
    if token is None:
        return RedirectResponse(
            url=f"/password-reset?success={encoded_message('Si el correo existe, se genero un enlace de recuperacion.')}{intent_suffix}",
            status_code=303,
        )

    reset_url = f"{settings.public_base_url}/password-reset/confirm?token={token}"
    local_path = reset_url.replace(settings.public_base_url, "")
    smtp_ready = smtp_is_configured()
    sms_ready = sms_is_configured()
    if method == "local" and not smtp_ready:
        log_audit_event(
            user_id=None,
            organization_id=None,
            location_id=None,
            action="Recuperacion",
            entity_type="Credencial",
            entity_label=email.strip().lower(),
            detail="Token generado para cambio de clave mediante enlace local",
        )
        return RedirectResponse(
            url=f"/password-reset?success={encoded_message(f'Enlace local generado: {local_path}')}{intent_suffix}",
            status_code=303,
        )
    if method == "phone":
        normalized_phone = phone.strip()
        if not normalized_phone:
            return RedirectResponse(
                url=f"/password-reset?error={encoded_message('Debes escribir un telefono para enviar el enlace por SMS.')}{intent_suffix}",
                status_code=303,
            )
        sms_sent = False
        try:
            sms_sent = send_password_reset_sms(phone_number=normalized_phone, reset_url=reset_url)
        except Exception as exc:
            log_audit_event(
                user_id=None,
                organization_id=None,
                location_id=None,
                action="Error",
                entity_type="SMS",
                entity_label=normalized_phone,
                detail=f"Fallo envio reset SMS: {exc}",
            )
        log_audit_event(
            user_id=None,
            organization_id=None,
            location_id=None,
            action="Recuperacion",
            entity_type="Credencial",
            entity_label=email.strip().lower(),
            detail=f"Token generado para cambio de clave por SMS. SMS enviado: {'si' if sms_sent else 'no'} | telefono: {normalized_phone}",
        )
        success_message = "Si la cuenta existe, enviaremos instrucciones al telefono registrado."
        if not sms_ready or not sms_sent:
            success_message = (
                "Canal SMS no configurado por ahora. "
                f"Usa este enlace local temporal: {local_path}"
            )
        return RedirectResponse(
            url=f"/password-reset?success={encoded_message(success_message)}{intent_suffix}",
            status_code=303,
        )

    email_sent = False
    try:
        email_sent = send_password_reset_email(to_email=email.strip(), reset_url=reset_url)
    except Exception as exc:
        log_audit_event(
            user_id=None,
            organization_id=None,
            location_id=None,
            action="Error",
            entity_type="Correo",
            entity_label=email.strip().lower(),
            detail=f"Fallo envio reset: {exc}",
        )
    log_audit_event(
        user_id=None,
        organization_id=None,
        location_id=None,
        action="Recuperacion",
        entity_type="Credencial",
        entity_label=email.strip().lower(),
        detail=f"Token generado para cambio de clave. Email enviado: {'si' if email_sent else 'no'}",
    )
    success_message = "Si el correo existe, enviamos instrucciones para restablecer la clave."
    if not email_sent:
        success_message = f"Correo no configurado. Usa este enlace local: {local_path}"
    return RedirectResponse(
        url=f"/password-reset?success={encoded_message(success_message)}{intent_suffix}",
        status_code=303,
    )


@router.get("/password-reset/confirm", response_class=HTMLResponse)
async def password_reset_confirm_page(
    request: Request,
    token: str = Query(default=""),
    error: str = "",
    success: str = "",
) -> HTMLResponse:
    password_min_length = 10
    if token:
        with get_connection() as connection:
            row = connection.execute(
                "SELECT users.organization_id FROM password_reset_tokens JOIN users ON users.id = password_reset_tokens.user_id WHERE password_reset_tokens.token_hash = ? AND password_reset_tokens.used_at = '' ORDER BY password_reset_tokens.id DESC LIMIT 1",
                (legacy_sha256_hash(token),),
            ).fetchone()
        if row:
            password_min_length = minimum_password_length(int(row["organization_id"]))
    return templates.TemplateResponse(
        request=request,
        name="password_reset_form.html",
        context={
            "request": request,
            "error": error,
            "success": success,
            "token": token,
            "password_min_length": password_min_length,
        },
    )


@router.post("/password-reset/confirm")
async def password_reset_confirm_action(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
) -> RedirectResponse:
    password_min_length = 10
    with get_connection() as connection:
        row = connection.execute(
            "SELECT users.organization_id FROM password_reset_tokens JOIN users ON users.id = password_reset_tokens.user_id WHERE password_reset_tokens.token_hash = ? AND password_reset_tokens.used_at = '' ORDER BY password_reset_tokens.id DESC LIMIT 1",
            (legacy_sha256_hash(token),),
        ).fetchone()
    if row:
        password_min_length = minimum_password_length(int(row["organization_id"]))
    if len(password) < password_min_length:
        return RedirectResponse(
            url=f"/password-reset/confirm?token={token}&error={encoded_message(f'La clave debe tener al menos {password_min_length} caracteres.')}",
            status_code=303,
        )
    if password != password_confirm:
        return RedirectResponse(
            url=f"/password-reset/confirm?token={token}&error={encoded_message('La confirmacion de clave no coincide.')}",
            status_code=303,
        )

    user = consume_password_reset_token(token, password)
    if user is None:
        return RedirectResponse(
            url=f"/password-reset/confirm?error={encoded_message('El enlace ya no es valido o ya fue usado.')}",
            status_code=303,
        )

    mark_password_change_completed(user["id"])
    log_audit_event(
        user_id=user["id"],
        organization_id=user["organization_id"],
        location_id=user["location_id"],
        action="Actualizacion",
        entity_type="Credencial",
        entity_label=user["email"],
        detail="Clave actualizada por flujo de recuperacion",
    )
    return RedirectResponse(
        url=f"/login?success={encoded_message('Clave actualizada. Ya puedes iniciar sesion.')}",
        status_code=303,
    )


@router.get("/api/login/locations")
async def login_location_search(
    q: str = Query(default="", max_length=160),
    limit: int = Query(default=12, ge=1, le=20),
    intent: str = Query(default="", max_length=40),
) -> JSONResponse:
    results = search_location_candidates(q, limit=limit, intent=intent)
    return JSONResponse({"results": results})


@router.post("/login")
async def login_action(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    remember_me: str = Form("0"),
    intent: str = Form(""),
    organization_id: str = Form(""),
    location_id: str = Form(""),
    legal_acceptance: str = Form("0"),
) -> RedirectResponse:
    selected_intent = intent or request.session.get("entry_intent", "")
    if not selected_intent:
        return RedirectResponse(
            url="/login?error=Debes%20seleccionar%20un%20flujo%20clinico%20antes%20de%20iniciar%20sesion",
            status_code=303,
        )
    enabled_intents = {
        flow["id"] for flow in entry_flows() if flow.get("enabled", True)
    }
    if selected_intent not in enabled_intents:
        return RedirectResponse(
            url=f"/login?error={encoded_message('Este flujo todavía no está disponible. Ingresa por Veterinaria.')}",
            status_code=303,
        )
    accepted_legal = legal_acceptance in {"1", "true", "on", "yes"}
    if settings.is_production and not accepted_legal:
        return RedirectResponse(
            url=f"/login?intent={selected_intent}&error={encoded_message('Debes aceptar los términos y la política de tratamiento para continuar.')}",
            status_code=303,
        )

    user = authenticate_user(email=email, password=password)
    if user is None:
        register_failed_login(email)
        message = login_lock_message(email) or "Credenciales invalidas. Usa la clave demo 'velmorax123'"
        return RedirectResponse(
            url=(
                f"/login?intent={selected_intent}"
                f"&error={encoded_message(message)}"
            ),
            status_code=303,
        )

    reset_failed_login(user["id"])
    effective_organization_id = str(
        organization_id
        or request.session.get("preferred_organization_id", "")
        or user.get("organization_id", "")
        or ""
    )
    effective_location_id = str(
        location_id
        or request.session.get("preferred_location_id", "")
        or user.get("location_id", "")
        or ""
    )
    effective_organization_id, effective_location_id = align_scope_to_entry_intent(
        selected_intent,
        effective_organization_id,
        effective_location_id,
    )
    remember_me_value = remember_me in {"1", "true", "on", "yes"}

    if requires_push_approval(user["role"]):
        request.session["pending_login"] = {
            "user_id": user["id"],
            "entry_intent": selected_intent,
            "organization_id": effective_organization_id,
            "location_id": effective_location_id,
            "remember_me": remember_me_value,
            "accepted_legal": accepted_legal,
            "requested_at": datetime.now(UTC).isoformat(),
        }
        request.session.pop("user_id", None)
        return RedirectResponse(url="/login/push-approval", status_code=303)

    return complete_login_session(
        request,
        user=user,
        selected_intent=selected_intent,
        effective_organization_id=effective_organization_id,
        effective_location_id=effective_location_id,
        remember_me=remember_me_value,
        accepted_legal=accepted_legal,
    )


@router.get("/login/push-approval", response_class=HTMLResponse)
async def login_push_approval_page(request: Request, error: str = "") -> HTMLResponse:
    pending_login = request.session.get("pending_login")
    if not pending_login:
        return RedirectResponse(url="/login", status_code=303)

    user = get_user_by_id(pending_login.get("user_id"))
    if user is None:
        request.session.pop("pending_login", None)
        return RedirectResponse(url="/login?error=Tu%20solicitud%20de%20verificacion%20ya%20no%20es%20valida", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="push_approval.html",
        context={
            "request": request,
            "error": error,
            "user": user,
            "intent": pending_login.get("entry_intent", ""),
            "trusted_device_label": "Telefono confiable",
        },
    )


@router.post("/login/push-approval")
async def login_push_approval_action(request: Request, approve: str = Form("0")) -> RedirectResponse:
    pending_login = request.session.get("pending_login")
    if not pending_login:
        return RedirectResponse(url="/login", status_code=303)

    if approve not in {"1", "true", "yes", "on"}:
        request.session.pop("pending_login", None)
        request.session["login_notice"] = "Intento de ingreso rechazado desde la verificacion en dos pasos."
        request.session["login_notice_type"] = "error"
        return RedirectResponse(url="/login", status_code=303)

    user = get_user_by_id(pending_login.get("user_id"))
    if user is None:
        request.session.pop("pending_login", None)
        return RedirectResponse(url="/login?error=Tu%20verificacion%20ya%20no%20es%20valida", status_code=303)

    request.session.pop("pending_login", None)
    return complete_login_session(
        request,
        user=user,
        selected_intent=pending_login.get("entry_intent", ""),
        effective_organization_id=str(pending_login.get("organization_id", "")),
        effective_location_id=str(pending_login.get("location_id", "")),
        remember_me=bool(pending_login.get("remember_me")),
        accepted_legal=bool(pending_login.get("accepted_legal")),
    )


@router.post("/logout")
async def logout_action(request: Request) -> RedirectResponse:
    request.session.clear()
    request.session["login_notice"] = "Sesion cerrada correctamente."
    request.session["login_notice_type"] = "success"
    return RedirectResponse(url="/login", status_code=303)


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    saved: int = 0,
    moved: int = 0,
    appointment_saved: int = 0,
    patient_saved: int = 0,
    record_saved: int = 0,
    movement_error: str = "",
    permission_error: str = "",
    search: str = Query(default=""),
    category: str = Query(default=""),
    status: str = Query(default=""),
    day: str = Query(default=""),
    period: str = Query(default="today"),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    veterinarian_filter: str = Query(default=""),
    priority_filter: str = Query(default=""),
    appointment_status_filter: str = Query(default=""),
    history_span: str = Query(default="week"),
    organization_id: str = Query(default=""),
    location_id: str = Query(default=""),
):
    response = render_authenticated_page(
        request,
        "dashboard.html",
        saved=saved,
        moved=moved,
        appointment_saved=appointment_saved,
        patient_saved=patient_saved,
        record_saved=record_saved,
        movement_error=movement_error,
        permission_error=permission_error,
        search=search,
        category=category,
        status=status,
        day=day,
        period=period,
        date_from=date_from,
        date_to=date_to,
        veterinarian_filter=veterinarian_filter,
        priority_filter=priority_filter,
        appointment_status_filter=appointment_status_filter,
        history_span=history_span,
        organization_id=organization_id,
        location_id=location_id,
        active_path="/",
    )
    if response is None:
        return redirect_to_login(request.session.get("entry_intent", ""))
    return response


def _dashboard_summary_context(
    request: Request, *, day: str, period: str, date_from: str, date_to: str,
    organization_id: str, location_id: str,
) -> tuple[dict | None, dict | None]:
    return context_for_authenticated_user(
        request, day=day, period=period, date_from=date_from, date_to=date_to,
        organization_id=organization_id, location_id=location_id, active_path="/",
    )


@router.get("/dashboard/resumen/export")
async def export_dashboard_summary(
    request: Request,
    day: str = Query(default=""), period: str = Query(default="today"),
    date_from: str = Query(default=""), date_to: str = Query(default=""),
    organization_id: str = Query(default=""), location_id: str = Query(default=""),
):
    context, _user = _dashboard_summary_context(
        request, day=day, period=period, date_from=date_from, date_to=date_to,
        organization_id=organization_id, location_id=location_id,
    )
    if context is None:
        return redirect_to_login(request.session.get("entry_intent", ""))
    if not _user["permissions"].get("export_dashboard", False):
        return redirect_to_module_with_error("/", "Tu rol no puede exportar el resumen del tablero.")
    board = context["veterinary_dashboard"]
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Resumen diario Velmorax", board["period"]["label"]])
    writer.writerow(["Indicador", "Valor", "Comparación anterior"])
    for item in board["trends"]:
        writer.writerow([item["label"], item["value"], item["previous"]])
    writer.writerow([])
    writer.writerow(["Indicadores clínicos", "Valor", "Detalle"])
    for item in board["clinical_indicators"]:
        writer.writerow([item["label"], item["value"], item["detail"]])
    writer.writerow([])
    writer.writerow(["Pendiente", "Responsable", "Prioridad", "Fecha límite", "Origen"])
    for item in board["assigned_tasks"]:
        writer.writerow([item["title"], item["responsible"], item["priority"], item["due_at"], item["source"]])
    filename = f"resumen-velmorax-{board['period']['start']}-{board['period']['end']}.csv"
    log_audit_event(user_id=_user["id"], organization_id=int(context["scope"]["organization_id"]), location_id=int(context["scope"]["location_id"]), action="Exportó resumen", entity_type="Tablero", entity_label="Resumen operativo", detail=board["period"]["label"])
    return Response(
        content="\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/dashboard/resumen/imprimir", response_class=HTMLResponse)
async def print_dashboard_summary(
    request: Request,
    day: str = Query(default=""), period: str = Query(default="today"),
    date_from: str = Query(default=""), date_to: str = Query(default=""),
    organization_id: str = Query(default=""), location_id: str = Query(default=""),
):
    context, _user = _dashboard_summary_context(
        request, day=day, period=period, date_from=date_from, date_to=date_to,
        organization_id=organization_id, location_id=location_id,
    )
    if context is None:
        return redirect_to_login(request.session.get("entry_intent", ""))
    if not _user["permissions"].get("export_dashboard", False):
        return redirect_to_module_with_error("/", "Tu rol no puede imprimir el resumen del tablero.")
    log_audit_event(user_id=_user["id"], organization_id=int(context["scope"]["organization_id"]), location_id=int(context["scope"]["location_id"]), action="Imprimió resumen", entity_type="Tablero", entity_label="Resumen operativo", detail=context["veterinary_dashboard"]["period"]["label"])
    return templates.TemplateResponse(request=request, name="dashboard_summary_print.html", context=context)


@router.post("/dashboard/preferences")
async def update_dashboard_preferences(
    request: Request,
    selected_view: str = Form("operation"),
    visible_cards: list[str] = Form([]),
    apply_to_role: str = Form(""),
    view_only: int = Form(0),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if view_only:
        visible_cards = list(get_dashboard_preferences(user["id"], user["role"])["visible_cards"])
    if apply_to_role in {"owner", "admin", "clinical", "reception", "inventory"} and user["permissions"]["manage_admin"]:
        save_dashboard_role_preferences(apply_to_role, visible_cards)
        label = f"rol {apply_to_role}"
    else:
        save_dashboard_preferences(user["id"], selected_view, visible_cards)
        label = "preferencias personales"
    log_audit_event(user_id=user["id"], organization_id=user["organization_id"], location_id=user["location_id"], action="Actualizó tablero", entity_type="Preferencias", entity_label=label, detail=selected_view)
    return RedirectResponse(url="/", status_code=303)


@router.post("/dashboard/tasks")
async def create_dashboard_task(
    request: Request,
    organization_id: int = Form(...), location_id: int = Form(...), title: str = Form(...),
    assigned_user_id: int = Form(0), priority: str = Form("normal"), due_at: str = Form(...),
    message: str = Form(""),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"].get("manage_dashboard_tasks") or not inventory_scope_allowed(user, organization_id, location_id):
        return redirect_to_module_with_error("/", "Tu rol no puede crear acciones en el tablero.")
    if not title.strip() or priority not in {"urgent", "important", "normal"}:
        return redirect_to_module_with_error("/", "Completa el título y una prioridad válida.")
    create_alert({"organization_id": organization_id, "location_id": location_id, "created_by": user["id"], "assigned_user_id": assigned_user_id, "title": title.strip(), "message": message, "priority": priority, "due_at": due_at, "recurrence": "once", "escalation_minutes": 0, "entity_type": "dashboard_task"})
    log_audit_event(user_id=user["id"], organization_id=organization_id, location_id=location_id, action="Creó pendiente", entity_type="Tablero", entity_label=title.strip(), detail=priority)
    return RedirectResponse(url="/", status_code=303)


@router.post("/dashboard/tasks/{alert_id}")
async def update_dashboard_task(
    request: Request, alert_id: int, organization_id: int = Form(...), location_id: int = Form(...),
    title: str = Form(...), assigned_user_id: int = Form(0), priority: str = Form("normal"), due_at: str = Form(...), message: str = Form(""),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"].get("manage_dashboard_tasks") or not inventory_scope_allowed(user, organization_id, location_id) or not alert_belongs_to_scope(alert_id, organization_id, location_id):
        return redirect_to_module_with_error("/", "No puedes modificar esta acción.")
    update_alert(alert_id, organization_id, location_id, {"title": title, "message": message, "priority": priority, "due_at": due_at, "assigned_user_id": assigned_user_id, "recurrence": "once", "escalation_minutes": 0})
    log_audit_event(user_id=user["id"], organization_id=organization_id, location_id=location_id, action="Actualizó pendiente", entity_type="Tablero", entity_label=title.strip(), detail=priority)
    return RedirectResponse(url="/", status_code=303)


@router.post("/dashboard/tasks/{alert_id}/close")
async def close_dashboard_task(request: Request, alert_id: int, organization_id: int = Form(...), location_id: int = Form(...)) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"].get("manage_dashboard_tasks") or not inventory_scope_allowed(user, organization_id, location_id) or not alert_belongs_to_scope(alert_id, organization_id, location_id):
        return redirect_to_module_with_error("/", "No puedes cerrar esta acción.")
    resolved = resolve_alert(alert_id, organization_id, location_id)
    if resolved is None:
        return redirect_to_module_with_error("/", "Solo las acciones manuales pueden cerrarse desde el tablero.")
    log_audit_event(user_id=user["id"], organization_id=organization_id, location_id=location_id, action="Cerró pendiente", entity_type="Tablero", entity_label=str(alert_id))
    return RedirectResponse(url="/", status_code=303)


@router.get("/agenda", response_class=HTMLResponse)
async def agenda_page(
    request: Request,
    appointment_saved: int = 0,
    appointment_updated: int = 0,
    permission_error: str = "",
    agenda_error: str = "",
    new_appointment: int = Query(default=0, alias="new"),
    patient_id: int = Query(default=0),
    day: str = Query(default=""),
    status: str = Query(default=""),
    view: str = Query(default="day"),
    veterinarian: str = Query(default=""),
    priority: str = Query(default=""),
    channel: str = Query(default=""),
    organization_id: str = Query(default=""),
    location_id: str = Query(default=""),
):
    response = render_authenticated_page(
        request,
        "agenda.html",
        appointment_saved=appointment_saved,
        appointment_updated=appointment_updated,
        permission_error=permission_error,
        agenda_error=agenda_error,
        extra_context={"open_new_appointment": bool(new_appointment), "agenda_preselected_patient_id": patient_id},
        day=day,
        agenda_status=status,
        agenda_view=view,
        agenda_veterinarian=veterinarian,
        agenda_priority=priority,
        agenda_channel=channel,
        organization_id=organization_id,
        location_id=location_id,
        active_path="/agenda",
    )
    if response is None:
        return redirect_to_login(request.session.get("entry_intent", "agenda"))
    return response


@router.get("/inventario", response_class=HTMLResponse)
async def inventory_page(
    request: Request,
    saved: int = 0,
    moved: int = 0,
    movement_error: str = "",
    permission_error: str = "",
    notice: str = Query(default=""),
    search: str = Query(default=""),
    category: str = Query(default=""),
    status: str = Query(default=""),
    item_type: str = Query(default=""),
    storage_area: str = Query(default=""),
    supplier: str = Query(default=""),
    expiry: str = Query(default=""),
    organization_id: str = Query(default=""),
    location_id: str = Query(default=""),
):
    response = render_authenticated_page(
        request,
        "inventory.html",
        saved=saved,
        moved=moved,
        movement_error=movement_error,
        permission_error=permission_error,
        search=search,
        category=category,
        status=status,
        item_type=item_type,
        storage_area=storage_area,
        supplier=supplier,
        expiry=expiry,
        organization_id=organization_id,
        location_id=location_id,
        active_path="/inventario",
        extra_context={"inventory_notice": notice},
    )
    if response is None:
        return redirect_to_login("inventario")
    return response


@router.get("/alertas", response_class=HTMLResponse)
async def alerts_page(
    request: Request,
    saved: int = 0,
    updated: int = 0,
    notice: str = Query(default=""),
    priority: str = Query(default=""),
    organization_id: str = Query(default=""),
    location_id: str = Query(default=""),
):
    context, user = context_for_authenticated_user(
        request,
        organization_id=organization_id,
        location_id=location_id,
        active_path="/alertas",
    )
    if context is None:
        return redirect_to_login(request.session.get("entry_intent", ""))
    if not user["permissions"]["view_inventory"]:
        return redirect_to_module_with_error("/", "Tu rol no puede consultar alertas de insumos.")
    context["alert_saved"] = saved
    context["alert_updated"] = updated
    context["alert_notice"] = notice
    context["alerts"] = list_alerts(
        context["scope"]["organization_id"],
        context["scope"]["location_id"],
    )
    if priority in {"urgent", "important", "normal"}:
        context["alerts"] = [item for item in context["alerts"] if item["priority"] == priority]
        context["alert_priority_filter"] = priority
    context["resolved_alerts"] = list_resolved_alerts(
        context["scope"]["organization_id"], context["scope"]["location_id"]
    )
    context["due_alerts_total"] = sum(1 for item in context["alerts"] if item["is_due"])
    context["scheduled_alerts_total"] = sum(1 for item in context["alerts"] if not item["is_due"])
    context["urgent_alerts_total"] = sum(1 for item in context["alerts"] if item["is_due"] and item["priority"] == "urgent")
    context["automatic_alerts_total"] = sum(1 for item in context["alerts"] if item["source"] == "automatic")
    context["manual_alerts_total"] = sum(1 for item in context["alerts"] if item["source"] == "manual")
    context["alert_assignees"] = [
        item for item in list_users()
        if item["is_active"] and (
            not context["scope"]["organization_id"]
            or str(item["organization_id"]) == context["scope"]["organization_id"]
        ) and (item["role"] in {"owner", "admin"} or str(item["location_id"]) == context["scope"]["location_id"])
    ]
    context["alert_default_due"] = (
        datetime.now() + timedelta(hours=1)
    ).strftime("%Y-%m-%dT%H:%M")
    return templates.TemplateResponse(request=request, name="alerts.html", context=context)


@router.post("/dashboard/handoff")
async def save_shift_handoff(
    request: Request,
    organization_id: int = Form(...),
    location_id: int = Form(...),
    shift_label: str = Form(""),
    summary: str = Form(...),
    pending_actions: str = Form(""),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["view_agenda"] or not inventory_scope_allowed(user, organization_id, location_id):
        return redirect_to_module_with_error("/", "No puedes registrar entregas para esta sede.")
    if not summary.strip():
        return redirect_to_module_with_error("/", "Escribe un resumen del turno.")
    create_shift_handoff({
        "organization_id": organization_id,
        "location_id": location_id,
        "created_by": user["id"],
        "shift_label": shift_label,
        "summary": summary,
        "pending_actions": pending_actions,
    })
    log_audit_event(
        user_id=user["id"], organization_id=organization_id, location_id=location_id,
        action="Entrega de turno", entity_type="Operacion", entity_label=shift_label or "Turno",
        detail=summary.strip(),
    )
    suffix = build_scope_query(str(organization_id), str(location_id))
    return RedirectResponse(url=f"/?notice={encoded_message('Entrega de turno guardada.')}&{suffix}", status_code=303)


@router.get("/clinica", response_class=HTMLResponse)
async def clinical_page(
    request: Request,
    patient_saved: int = 0,
    record_saved: int = 0,
    permission_error: str = "",
    day: str = Query(default=""),
    organization_id: str = Query(default=""),
    location_id: str = Query(default=""),
    patient_id: int = Query(default=0),
    q: str = Query(default=""),
    patient_status: str = Query(default=""),
    species: str = Query(default=""),
    prevention: str = Query(default=""),
    alerts: int = Query(default=0),
    page: int = Query(default=1),
):
    response = render_authenticated_page(
        request,
        "clinical.html",
        patient_saved=patient_saved,
        record_saved=record_saved,
        permission_error=permission_error,
        day=day,
        organization_id=organization_id,
        location_id=location_id,
        active_path="/clinica",
        record_patient_id=patient_id,
        patient_search=q,
        patient_status_filter=patient_status,
        patient_species_filter=species,
        patient_prevention_filter=prevention,
        patient_alerts_only=bool(alerts),
        patient_page=page,
    )
    if response is None:
        return redirect_to_login(request.session.get("entry_intent", "odontologia"))
    return response


@router.get("/pacientes/{patient_id}/historial", response_class=HTMLResponse)
async def patient_history_page(
    request: Request,
    patient_id: int,
    organization_id: str = Query(default=""),
    location_id: str = Query(default=""),
):
    """Muestra el historial clínico de una mascota dentro de su sede actual."""
    response = render_authenticated_page(
        request,
        "clinical.html",
        organization_id=organization_id,
        location_id=location_id,
        active_path="/clinica",
        record_patient_id=patient_id,
        patient_history_view=True,
    )
    if response is None:
        return redirect_to_login(request.session.get("entry_intent", "odontologia"))
    return response


@router.get("/pacientes/{patient_id}/historial/descargar")
async def download_patient_history(
    request: Request,
    patient_id: int,
    organization_id: str = Query(default=""),
    location_id: str = Query(default=""),
):
    """Descarga el historial de una mascota sin salir de la sede seleccionada."""
    context, user = context_for_authenticated_user(
        request,
        organization_id=organization_id,
        location_id=location_id,
        active_path="/clinica",
    )
    if context is None or user is None:
        return redirect_to_login(request.session.get("entry_intent", "odontologia"))
    if not user["permissions"]["view_clinical"]:
        return redirect_to_module_with_error("/clinica", "Tu rol no puede descargar historiales clínicos.")

    patient = next(
        (item for item in context["patients"] if item["id"] == patient_id),
        None,
    )
    if patient is None:
        return redirect_to_module_with_error("/clinica", "La mascota no pertenece a la sede seleccionada.")

    records = list_clinical_records(
        limit=100,
        organization_id=str(context["scope"]["organization_id"]),
        location_id=str(context["scope"]["location_id"]),
        patient_id=patient_id,
    )
    filename_stub = re.sub(r"[^a-z0-9]+", "-", patient["display_name"].lower()).strip("-") or "paciente"
    return Response(
        content=build_patient_history_pdf(patient, records),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="historial-{filename_stub}.pdf"'},
    )


@router.get("/clinica/cierre-diario/export")
async def export_daily_closure(
    request: Request,
    day: str = Query(default=""),
    organization_id: str = Query(default=""),
    location_id: str = Query(default=""),
):
    context, user = context_for_authenticated_user(
        request,
        day=day,
        organization_id=organization_id,
        location_id=location_id,
        active_path="/clinica",
    )
    if context is None or user is None:
        return redirect_to_login(request.session.get("entry_intent", "odontologia"))
    if not user["permissions"]["view_clinical"]:
        return redirect_to_module_with_error("/clinica", "Tu rol no puede exportar el cierre diario.")

    csv_content = build_daily_summary_csv(context)
    filename = f"velmorax-cierre-diario-{context['daily_financial_summary']['date']}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/clinica/cierre-diario/imprimir", response_class=HTMLResponse)
async def print_daily_closure(
    request: Request,
    day: str = Query(default=""),
    organization_id: str = Query(default=""),
    location_id: str = Query(default=""),
):
    context, user = context_for_authenticated_user(
        request,
        day=day,
        organization_id=organization_id,
        location_id=location_id,
        active_path="/clinica",
    )
    if context is None or user is None:
        return redirect_to_login(request.session.get("entry_intent", "odontologia"))
    if not user["permissions"]["view_clinical"]:
        return redirect_to_module_with_error("/clinica", "Tu rol no puede imprimir el cierre diario.")

    context["daily_records_for_print"] = [
        item
        for item in context["clinical_records"]
        if item["encounter_date"] == context["daily_financial_summary"]["date"]
    ]
    return templates.TemplateResponse(
        request=request,
        name="daily_summary_print.html",
        context=context,
    )


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(
    request: Request,
    permission_error: str = "",
    organization_saved: int = 0,
    location_saved: int = 0,
    user_saved: int = 0,
    organization_updated: int = 0,
    location_updated: int = 0,
    user_updated: int = 0,
    catalog_imported: int = 0,
    catalog_synced: int = 0,
    catalog_veterinary_synced: int = 0,
    settings_saved: int = 0,
    catalog_error: str = "",
    settings_error: str = "",
    service_error: str = "",
    member_delete_error: str = "",
    organization_id: str = Query(default=""),
    location_id: str = Query(default=""),
):
    context, user = context_for_authenticated_user(
        request,
        organization_id=organization_id,
        location_id=location_id,
        active_path="/admin",
    )
    if context is None:
        return redirect_to_login("general")
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Tu rol no puede administrar la red.")

    organization_id = int(user["organization_id"])
    admin_organizations = [item for item in list_organizations() if int(item["id"]) == organization_id]
    admin_locations = list_locations(str(organization_id), include_inactive=True)
    admin_users = [item for item in list_users() if int(item.get("organization_id") or 0) == organization_id]
    if context["is_veterinary_flow"]:
        admin_locations = [item for item in admin_locations if item.get("catalog_kind") == "veterinaria"]
        veterinary_location_ids = {int(item["id"]) for item in admin_locations}
        admin_users = [item for item in admin_users if int(item.get("location_id") or 0) in veterinary_location_ids]
    admin_self_hidden = not any(int(item["id"]) == int(user["id"]) for item in admin_users)
    for item in admin_users:
        item["effective_permissions"] = effective_permissions(item)
    context["scope"]["organization_id"] = str(organization_id)
    context["scope"]["locations"] = admin_locations
    context["scope"]["location_id"] = str(user.get("location_id") or "")
    organization = admin_organizations[0] if admin_organizations else {}
    allowed_site_names = {item["name"] for item in admin_locations}
    admin_audit_events = [
        item for item in list_recent_activity(limit=100, organization_id=str(organization_id))
        if item.get("location_name") in allowed_site_names or item.get("location_name") == "-"
    ][:40]
    defaults = {
        "currency": "COP", "agenda_slot_minutes": 30, "appointment_reminder_hours": 24,
        "low_stock_threshold": 5, "password_min_length": 10, "recovery_channel": "email",
    }
    with get_connection() as connection:
        row = connection.execute(
            "SELECT settings_json FROM organization_preferences WHERE organization_id = ?",
            (organization_id,),
        ).fetchone()
        service_rows = connection.execute(
            "SELECT id, name, duration_minutes, is_active FROM clinic_services WHERE organization_id = ? ORDER BY name COLLATE NOCASE",
            (organization_id,),
        ).fetchall()
    try:
        defaults.update(json.loads(row["settings_json"]) if row and row["settings_json"] else {})
    except (TypeError, ValueError):
        pass

    context.update(
        {
            "permission_error": permission_error,
            "organization_saved": organization_saved,
            "location_saved": location_saved,
            "user_saved": user_saved,
            "organization_updated": organization_updated,
            "location_updated": location_updated,
            "user_updated": user_updated,
            "catalog_imported": catalog_imported,
            "catalog_synced": catalog_synced,
            "catalog_veterinary_synced": catalog_veterinary_synced,
            "settings_saved": settings_saved,
            "settings_error": settings_error,
            "service_error": service_error,
            "member_delete_error": member_delete_error,
            "catalog_error": catalog_error,
            "admin_users": admin_users,
            "admin_self_hidden": admin_self_hidden,
            "admin_organizations": admin_organizations,
            "admin_locations": admin_locations,
            "admin_active_locations": [item for item in admin_locations if item.get("is_active")],
            "active_site_count": sum(1 for item in admin_locations if item.get("is_active")),
            "app_settings": get_app_settings(),
            "clinic_settings": defaults,
            "admin_services": [dict(item) for item in service_rows],
            "audit_events": admin_audit_events,
        }
    )
    return templates.TemplateResponse(request=request, name="admin.html", context=context)


@router.post("/admin/settings")
async def update_admin_settings(
    request: Request,
    agenda_slot_minutes: str = Form(""),
    appointment_reminder_hours: str = Form(""),
    low_stock_threshold: str = Form(""),
    password_min_length: str = Form(""),
    recovery_channel: str = Form(""),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Tu rol no puede actualizar ajustes.")

    org_id = int(user["organization_id"])
    preference_defaults = {
        "agenda_slot_minutes": 30, "appointment_reminder_hours": 24,
        "low_stock_threshold": 5, "password_min_length": 10, "recovery_channel": "email",
    }
    with get_connection() as connection:
        row = connection.execute("SELECT settings_json FROM organization_preferences WHERE organization_id = ?", (org_id,)).fetchone()
    try:
        existing_settings = json.loads(row["settings_json"]) if row and row["settings_json"] else {}
    except (TypeError, ValueError):
        existing_settings = {}
    existing_settings = {**preference_defaults, **existing_settings}

    try:
        agenda_slot_minutes = int(agenda_slot_minutes.strip()) if agenda_slot_minutes.strip() else int(existing_settings["agenda_slot_minutes"])
        appointment_reminder_hours = int(appointment_reminder_hours.strip()) if appointment_reminder_hours.strip() else int(existing_settings["appointment_reminder_hours"])
        low_stock_threshold = int(low_stock_threshold.strip()) if low_stock_threshold.strip() else int(existing_settings["low_stock_threshold"])
        password_min_length = int(password_min_length.strip()) if password_min_length.strip() else int(existing_settings["password_min_length"])
    except (AttributeError, TypeError, ValueError):
        return RedirectResponse(url=f"/admin?settings_error={encoded_message('Escribe números válidos en los campos de preferencias.')}", status_code=303)
    if not 5 <= agenda_slot_minutes <= 240 or not 1 <= appointment_reminder_hours <= 720:
        return RedirectResponse(url=f"/admin?settings_error={encoded_message('El intervalo de agenda debe ser de 5 a 240 minutos y el aviso de 1 a 720 horas.')}", status_code=303)
    if not 1 <= low_stock_threshold <= 1000 or not 8 <= password_min_length <= 128:
        return RedirectResponse(url=f"/admin?settings_error={encoded_message('El inventario debe estar entre 1 y 1000 y la clave entre 8 y 128 caracteres.')}", status_code=303)
    recovery_value = recovery_channel.strip().casefold() or str(existing_settings["recovery_channel"]).casefold()
    recovery_aliases = {
        "email": "email", "correo": "email", "correo electrónico": "email", "correo electronico": "email", "correo de contacto": "email",
        "admin": "admin", "administrador": "admin", "administrador autorizado": "admin",
    }
    recovery_channel = recovery_aliases.get(recovery_value, "")
    if not recovery_channel:
        return RedirectResponse(url=f"/admin?settings_error={encoded_message('En canal de recuperación escribe Correo de contacto o Administrador autorizado.')}", status_code=303)
    values = {
        "agenda_slot_minutes": agenda_slot_minutes,
        "appointment_reminder_hours": appointment_reminder_hours,
        "low_stock_threshold": low_stock_threshold,
        "password_min_length": password_min_length,
        "recovery_channel": recovery_channel,
    }
    with get_connection() as connection:
        settings = dict(existing_settings)
        settings.update(values)
        connection.execute(
            "INSERT INTO organization_preferences (organization_id, settings_json) VALUES (?, ?) ON CONFLICT(organization_id) DO UPDATE SET settings_json=excluded.settings_json",
            (org_id, json.dumps(settings, ensure_ascii=False)),
        )
        connection.commit()
    log_audit_event(
        user_id=user["id"],
        organization_id=org_id,
        location_id=None,
        action="Actualizacion",
        entity_type="Configuracion",
        entity_label="Preferencias de la clínica",
        detail="Agenda, avisos, inventario y recuperación de acceso",
    )
    return RedirectResponse(url="/admin?settings_saved=1&panel=admin-operations", status_code=303)


@router.post("/admin/services")
async def create_admin_service(
    request: Request,
    name: str = Form(...),
    duration_minutes: int = Form(30),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Solo los administradores pueden gestionar servicios.")
    name = name.strip()
    if not name or len(name) > 100 or duration_minutes not in {15, 30, 45, 60, 90, 120}:
        return RedirectResponse(url="/admin?service_error=Revisa+el+nombre+y+la+duración.&panel=admin-services", status_code=303)
    org_id = int(user["organization_id"])
    with get_connection() as connection:
        duplicate = connection.execute("SELECT id FROM clinic_services WHERE organization_id = ? AND lower(name) = lower(?)", (org_id, name)).fetchone()
        if duplicate:
            return RedirectResponse(url="/admin?service_error=Ya+existe+un+servicio+con+ese+nombre.&panel=admin-services", status_code=303)
        connection.execute("INSERT INTO clinic_services (organization_id, name, duration_minutes) VALUES (?, ?, ?)", (org_id, name, duration_minutes))
        connection.commit()
    log_audit_event(user_id=user["id"], organization_id=org_id, location_id=None, action="Creación", entity_type="Servicio", entity_label=name, detail=f"Duración {duration_minutes} min")
    return RedirectResponse(url="/admin?service_saved=1&panel=admin-services", status_code=303)


@router.post("/admin/services/{service_id}")
async def update_admin_service(
    request: Request,
    service_id: int,
    name: str = Form(...),
    duration_minutes: int = Form(30),
    is_active: int = Form(0),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Solo los administradores pueden gestionar servicios.")
    org_id = int(user["organization_id"])
    name = name.strip()
    if not name or len(name) > 100 or duration_minutes not in {15, 30, 45, 60, 90, 120}:
        return RedirectResponse(url="/admin?service_error=Revisa+el+nombre+y+la+duración.&panel=admin-services", status_code=303)
    with get_connection() as connection:
        row = connection.execute("SELECT id FROM clinic_services WHERE id = ? AND organization_id = ?", (service_id, org_id)).fetchone()
        if row is None:
            return redirect_to_module_with_error("/admin", "Ese servicio no pertenece a tu organización.")
        connection.execute("UPDATE clinic_services SET name = ?, duration_minutes = ?, is_active = ? WHERE id = ? AND organization_id = ?", (name, duration_minutes, int(bool(is_active)), service_id, org_id))
        connection.commit()
    log_audit_event(user_id=user["id"], organization_id=org_id, location_id=None, action="Actualización", entity_type="Servicio", entity_label=name, detail=f"Duración {duration_minutes} min")
    return RedirectResponse(url="/admin?service_saved=1&panel=admin-services", status_code=303)


@router.post("/admin/services/{service_id}/delete")
async def delete_admin_service(request: Request, service_id: int) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Solo los administradores pueden eliminar servicios.")
    organization_id = int(user["organization_id"])
    with get_connection() as connection:
        service = connection.execute(
            "SELECT name FROM clinic_services WHERE id = ? AND organization_id = ?",
            (service_id, organization_id),
        ).fetchone()
        if service is None:
            return redirect_to_module_with_error("/admin?panel=admin-services", "Ese servicio no pertenece a tu organización.")
        connection.execute(
            "DELETE FROM clinic_services WHERE id = ? AND organization_id = ?",
            (service_id, organization_id),
        )
        connection.commit()
    log_audit_event(
        user_id=user["id"], organization_id=organization_id, location_id=None,
        action="Eliminacion", entity_type="Servicio", entity_label=service["name"],
        detail="Servicio eliminado definitivamente; citas e historiales conservados",
    )
    return RedirectResponse(url="/admin?service_deleted=1&panel=admin-services", status_code=303)


@router.get("/admin/auditoria/export")
async def export_audit_activity(request: Request):
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Tu rol no puede exportar auditoria.")
    events = list_recent_activity(limit=500, organization_id=str(user["organization_id"]))
    if request.session.get("entry_intent") == "veterinaria":
        veterinary_site_names = {
            item["name"] for item in list_locations(str(user["organization_id"]), include_inactive=True)
            if item.get("catalog_kind") == "veterinaria"
        }
        events = [item for item in events if item.get("location_name") in veterinary_site_names or item.get("location_name") == "-"]
    csv_content = build_activity_csv(events)
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="velmorax-auditoria.csv"'},
    )


@router.get("/admin/backup")
async def export_backup_snapshot(request: Request):
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Tu rol no puede descargar respaldos.")

    org_id = int(user["organization_id"])
    if user.get("role") not in {"admin", "owner"}:
        return redirect_to_module_with_error("/admin", "Solo los administradores autorizados pueden descargar respaldos.")
    # Create a tenant-scoped snapshot: never return the shared database file to an organization admin.
    tables = ["organizations", "locations", "users", "organization_preferences", "clinic_services",
              "patients", "appointments", "clinical_records", "inventory_items", "inventory_movements",
              "alerts", "audit_events"]
    snapshot: dict[str, list[dict]] = {}
    with get_connection() as connection:
        for table in tables:
            if get_database_dialect() == "sqlite":
                columns = [row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()]
            else:
                columns = [row["column_name"] for row in connection.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = ? AND table_schema = current_schema()",
                    (table,),
                ).fetchall()]
            if not columns:
                continue
            if "organization_id" in columns:
                rows = connection.execute(f"SELECT * FROM {table} WHERE organization_id = ?", (org_id,)).fetchall()
            elif table == "organizations":
                rows = connection.execute("SELECT * FROM organizations WHERE id = ?", (org_id,)).fetchall()
            elif table == "locations":
                rows = connection.execute("SELECT * FROM locations WHERE organization_id = ?", (org_id,)).fetchall()
            elif table == "users":
                rows = connection.execute("SELECT * FROM users WHERE organization_id = ?", (org_id,)).fetchall()
            elif table == "organization_preferences":
                rows = connection.execute("SELECT * FROM organization_preferences WHERE organization_id = ?", (org_id,)).fetchall()
            elif table == "clinic_services":
                rows = connection.execute("SELECT * FROM clinic_services WHERE organization_id = ?", (org_id,)).fetchall()
            elif table == "audit_events":
                rows = connection.execute("SELECT * FROM audit_events WHERE organization_id = ?", (org_id,)).fetchall()
            else:
                continue
            snapshot[table] = [
                {key: value for key, value in dict(item).items() if key not in {"password_hash", "failed_login_attempts", "locked_until"}}
                for item in rows
            ]
    data = json.dumps({"organization_id": org_id, "created_at": datetime.now(UTC).isoformat(), "data": snapshot}, ensure_ascii=False, default=str)
    return Response(content=data, media_type="application/json; charset=utf-8",
                     headers={"Content-Disposition": 'attachment; filename="velmorax-respaldo-organizacion.json"'})


@router.post("/admin/catalogs/import/odontology")
async def import_odontology_catalog(
    request: Request,
    catalog_file: UploadFile = File(...),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Tu rol no puede importar catalogos.")

    try:
        payload = await catalog_file.read()
        summary = import_organization_location_catalog(payload)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/admin?catalog_error={str(exc).replace(' ', '%20')}",
            status_code=303,
        )

    detail = (
        f"Organizaciones nuevas {summary['organizations_created']}, "
        f"organizaciones actualizadas {summary['organizations_updated']}, "
        f"sedes nuevas {summary['locations_created']}, "
        f"sedes actualizadas {summary['locations_updated']}"
    )
    log_audit_event(
        user_id=user["id"],
        organization_id=None,
        location_id=None,
        action="Importacion",
        entity_type="Catalogo odontologico",
        entity_label=catalog_file.filename or "catalogo.csv",
        detail=detail,
    )
    return RedirectResponse(url="/admin?catalog_imported=1", status_code=303)


@router.post("/admin/catalogs/sync/odontology")
async def sync_odontology_catalog_from_official_source(request: Request) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Tu rol no puede sincronizar catalogos.")

    try:
        summary = sync_official_odontology_catalog()
    except Exception as exc:
        return RedirectResponse(
            url=f"/admin?catalog_error={str(exc).replace(' ', '%20')}",
            status_code=303,
        )

    detail = (
        f"Fuente oficial sincronizada. Filas procesadas {summary['rows_processed']}, "
        f"organizaciones nuevas {summary['organizations_created']}, "
        f"organizaciones actualizadas {summary['organizations_updated']}, "
        f"sedes nuevas {summary['locations_created']}, "
        f"sedes actualizadas {summary['locations_updated']}"
    )
    log_audit_event(
        user_id=user["id"],
        organization_id=None,
        location_id=None,
        action="Sincronizacion",
        entity_type="Catalogo odontologico oficial",
        entity_label="REPS / datos.gov.co",
        detail=detail,
    )
    return RedirectResponse(url="/admin?catalog_synced=1", status_code=303)


@router.post("/admin/catalogs/sync/national")
async def sync_national_catalog_from_official_source(request: Request) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Tu rol no puede sincronizar catalogos.")

    try:
        summary = sync_official_national_catalog()
    except Exception as exc:
        return RedirectResponse(
            url=f"/admin?catalog_error={str(exc).replace(' ', '%20')}",
            status_code=303,
        )

    detail = (
        f"Fuente oficial nacional sincronizada. Filas procesadas {summary['rows_processed']}, "
        f"organizaciones nuevas {summary['organizations_created']}, "
        f"organizaciones actualizadas {summary['organizations_updated']}, "
        f"sedes nuevas {summary['locations_created']}, "
        f"sedes actualizadas {summary['locations_updated']}"
    )
    log_audit_event(
        user_id=user["id"],
        organization_id=None,
        location_id=None,
        action="Sincronizacion",
        entity_type="Catalogo nacional oficial",
        entity_label="REPS / datos.gov.co",
        detail=detail,
    )
    return RedirectResponse(url="/admin?catalog_synced=1", status_code=303)


@router.post("/admin/catalogs/sync/veterinary")
async def sync_veterinary_catalog_from_official_source(request: Request) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Tu rol no puede sincronizar catalogos.")

    try:
        summary = sync_official_veterinary_catalog()
    except Exception as exc:
        return RedirectResponse(
            url=f"/admin?catalog_error={str(exc).replace(' ', '%20')}",
            status_code=303,
        )

    detail = (
        f"Fuente oficial veterinaria sincronizada. Filas procesadas {summary['rows_processed']}, "
        f"organizaciones nuevas {summary['organizations_created']}, "
        f"organizaciones actualizadas {summary['organizations_updated']}, "
        f"sedes nuevas {summary['locations_created']}, "
        f"sedes actualizadas {summary['locations_updated']}"
    )
    log_audit_event(
        user_id=user["id"],
        organization_id=None,
        location_id=None,
        action="Sincronizacion",
        entity_type="Catalogo veterinario oficial",
        entity_label="ICA",
        detail=detail,
    )
    return RedirectResponse(url="/admin?catalog_veterinary_synced=1", status_code=303)


@router.post("/admin/organizations")
async def create_new_organization(
    request: Request,
    name: str = Form(...),
    country: str = Form(...),
    timezone: str = Form(...),
    contact_email: str = Form(""),
    contact_phone: str = Form(""),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Tu rol no puede crear organizaciones.")

    create_organization(
        {
            "name": name.strip(),
            "country": country.strip(),
            "timezone": timezone.strip(),
            "contact_email": contact_email.strip(),
            "contact_phone": contact_phone.strip(),
        }
    )
    log_audit_event(
        user_id=user["id"],
        organization_id=None,
        location_id=None,
        action="Creacion",
        entity_type="Organizacion",
        entity_label=name.strip(),
        detail=f"{country.strip()} | {timezone.strip()} | {contact_email.strip()}",
    )
    return RedirectResponse(url="/admin?organization_saved=1", status_code=303)


@router.post("/admin/organizations/{organization_id}")
async def update_existing_organization(
    request: Request,
    organization_id: int,
    name: str = Form(...),
    country: str = Form(...),
    timezone: str = Form(...),
    contact_email: str = Form(""),
    contact_phone: str = Form(""),
    currency: str = Form("COP"),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Tu rol no puede editar organizaciones.")
    if organization_id != int(user["organization_id"]):
        return redirect_to_module_with_error("/admin", "Esa organización no está disponible para tu acceso.")
    if currency not in {"COP", "MXN", "PEN", "USD", "CLP", "ARS"}:
        return RedirectResponse(url="/admin?settings_error=Selecciona+una+moneda+válida.&panel=admin-organization", status_code=303)

    update_organization(
        organization_id,
        {
            "name": name.strip(),
            "country": country.strip(),
            "timezone": timezone.strip(),
            "contact_email": contact_email.strip(),
            "contact_phone": contact_phone.strip(),
        },
    )
    with get_connection() as connection:
        row = connection.execute("SELECT settings_json FROM organization_preferences WHERE organization_id = ?", (organization_id,)).fetchone()
        try:
            preferences = json.loads(row["settings_json"]) if row and row["settings_json"] else {}
        except (TypeError, ValueError):
            preferences = {}
        preferences["currency"] = currency
        connection.execute(
            "INSERT INTO organization_preferences (organization_id, settings_json) VALUES (?, ?) ON CONFLICT(organization_id) DO UPDATE SET settings_json=excluded.settings_json",
            (organization_id, json.dumps(preferences, ensure_ascii=False)),
        )
        connection.commit()
    log_audit_event(
        user_id=user["id"],
        organization_id=organization_id,
        location_id=user.get("location_id"),
        action="Actualizacion",
        entity_type="Organizacion",
        entity_label=name.strip(),
        detail=f"{country.strip()} | {timezone.strip()} | {contact_email.strip()} | {currency}",
    )
    return RedirectResponse(url="/admin?organization_updated=1", status_code=303)


@router.post("/admin/locations")
async def create_new_location(
    request: Request,
    organization_id: int = Form(...),
    name: str = Form(...),
    city: str = Form(...),
    address: str = Form(...),
    sector: str = Form(""),
    phone: str = Form(""),
    opening_hours: str = Form(""),
    catalog_kind: str = Form("consulta-general"),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Tu rol no puede crear sedes.")
    if organization_id != int(user["organization_id"]):
        return redirect_to_module_with_error("/admin", "No puedes agregar sedes a otra organización.")

    if not name.strip() or not city.strip() or not address.strip():
        return RedirectResponse(url="/admin?permission_error=Completa+nombre%2C+ciudad+y+dirección.&panel=admin-organization", status_code=303)
    create_location(
        {
            "organization_id": organization_id,
            "name": name.strip(),
            "city": city.strip(),
            "address": address.strip(),
            "sector": sector.strip(),
            "phone": phone.strip(),
            "opening_hours": opening_hours.strip(),
            "catalog_kind": catalog_kind if catalog_kind in {"veterinaria", "odontologia", "consulta-general"} else "consulta-general",
        }
    )
    log_audit_event(
        user_id=user["id"],
        organization_id=organization_id,
        location_id=user.get("location_id"),
        action="Creacion",
        entity_type="Sede",
        entity_label=name.strip(),
        detail=f"{city.strip()} | {sector.strip()} | {address.strip()}",
    )
    return RedirectResponse(url="/admin?location_saved=1", status_code=303)


@router.post("/admin/locations/{location_id}")
async def update_existing_location(
    request: Request,
    location_id: int,
    organization_id: int = Form(...),
    name: str = Form(...),
    city: str = Form(...),
    address: str = Form(...),
    sector: str = Form(""),
    phone: str = Form(""),
    opening_hours: str = Form(""),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Tu rol no puede editar sedes.")
    existing_location = get_location_by_id(str(location_id))
    if (existing_location is None or int(existing_location["organization_id"]) != int(user["organization_id"])
            or organization_id != int(user["organization_id"])):
        return redirect_to_module_with_error("/admin", "Esa sede no pertenece a tu organización.")

    update_location(
        location_id,
        {
            "organization_id": organization_id,
            "name": name.strip(),
            "city": city.strip(),
            "address": address.strip(),
            "sector": sector.strip(),
            "phone": phone.strip(),
            "opening_hours": opening_hours.strip(),
        },
    )
    log_audit_event(
        user_id=user["id"],
        organization_id=organization_id,
        location_id=location_id,
        action="Actualizacion",
        entity_type="Sede",
        entity_label=name.strip(),
        detail=f"{city.strip()} | {sector.strip()} | {address.strip()}",
    )
    return RedirectResponse(url="/admin?location_updated=1", status_code=303)


@router.post("/admin/locations/{location_id}/toggle")
async def toggle_location(
    request: Request,
    location_id: int,
    is_active: int = Form(...),
    organization_id: int = Form(0),
    name: str = Form(""),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Tu rol no puede gestionar sedes.")

    target_location = get_location_by_id(str(location_id))
    if target_location is None or int(target_location["organization_id"]) != int(user["organization_id"]):
        return redirect_to_module_with_error("/admin", "Esa sede no pertenece a tu organización.")
    if is_active and sum(1 for loc in list_locations(str(user["organization_id"])) if loc["is_active"]) <= 1:
        return redirect_to_module_with_error("/admin", "No puedes eliminar la única sede activa.")
    next_state = not bool(is_active)
    set_location_active(location_id, next_state)
    log_audit_event(
        user_id=user["id"],
        organization_id=int(user["organization_id"]),
        location_id=location_id,
        action="Restauracion" if next_state else "Eliminacion",
        entity_type="Sede",
        entity_label=name or f"Sede #{location_id}",
        detail="Restaurada" if next_state else "Retirada de la operación; datos históricos conservados",
    )
    result = "location_restored" if next_state else "location_removed"
    return RedirectResponse(url=f"/admin?{result}=1&panel=admin-organization", status_code=303)


@router.post("/admin/users")
async def create_new_user(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    organization_id: int = Form(...),
    location_id: int = Form(...),
    specialty: str = Form(""),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Tu rol no puede crear usuarios.")

    if organization_id != int(user["organization_id"]) or not inventory_scope_allowed(user, organization_id, location_id):
        return redirect_to_module_with_error("/admin", "Asigna al usuario a una sede de tu organización.")
    if role not in {"admin", "clinical", "inventory"}:
        return RedirectResponse(url="/admin?permission_error=Selecciona+un+rol+válido.&panel=admin-team", status_code=303)
    password_min_length = minimum_password_length(organization_id)
    if len(password) < password_min_length:
        return RedirectResponse(url=f"/admin?permission_error={encoded_message(f'La clave temporal debe tener al menos {password_min_length} caracteres.')}&panel=admin-team", status_code=303)
    try:
        create_user(
        {
            "full_name": full_name.strip(),
            "email": email.strip().lower(),
            "password": password,
            "role": role.strip(),
            "organization_id": organization_id,
            "location_id": location_id,
            "specialty": specialty.strip(),
        }
        )
    except Exception as exc:
        if "unique" in str(exc).lower():
            return RedirectResponse(url="/admin?permission_error=Ya+existe+un+usuario+con+ese+correo.&panel=admin-team", status_code=303)
        raise
    log_audit_event(
        user_id=user["id"],
        organization_id=organization_id,
        location_id=location_id,
        action="Creacion",
        entity_type="Usuario",
        entity_label=full_name.strip(),
        detail=f"{role.strip()} | {specialty.strip()}",
    )
    return RedirectResponse(url="/admin?user_saved=1", status_code=303)


@router.post("/admin/users/{user_id}")
async def update_existing_user(
    request: Request,
    user_id: int,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(""),
    role: str = Form(...),
    organization_id: int = Form(...),
    location_id: int = Form(...),
    specialty: str = Form(""),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Tu rol no puede editar usuarios.")
    target_user = next((item for item in list_users() if int(item["id"]) == user_id), None)
    if (target_user is None or int(target_user.get("organization_id") or 0) != int(user["organization_id"])
            or organization_id != int(user["organization_id"])
            or not inventory_scope_allowed(user, organization_id, location_id)):
        return redirect_to_module_with_error("/admin", "Ese usuario o sede no pertenece a tu organización.")
    if role not in {"admin", "clinical", "inventory"}:
        return RedirectResponse(url="/admin?permission_error=Selecciona+un+rol+válido.&panel=admin-team", status_code=303)
    password_min_length = minimum_password_length(organization_id)
    if password and len(password) < password_min_length:
        return RedirectResponse(url=f"/admin?permission_error={encoded_message(f'La clave debe tener al menos {password_min_length} caracteres.')}&panel=admin-team", status_code=303)
    if user_id == user["id"] and role != "admin":
        return redirect_to_module_with_error("/admin", "No puedes quitarte tu propio rol de administrador.")

    try:
        update_user(
        user_id,
        {
            "full_name": full_name.strip(),
            "email": email.strip().lower(),
            "password": password,
            "role": role.strip(),
            "organization_id": organization_id,
            "location_id": location_id,
            "specialty": specialty.strip(),
        },
        )
    except Exception as exc:
        if "unique" in str(exc).lower():
            return RedirectResponse(url="/admin?permission_error=Ya+existe+un+usuario+con+ese+correo.&panel=admin-team", status_code=303)
        raise
    log_audit_event(
        user_id=user["id"],
        organization_id=organization_id,
        location_id=location_id,
        action="Actualizacion",
        entity_type="Usuario",
        entity_label=full_name.strip(),
        detail=f"{role.strip()} | {specialty.strip()}" + (" | clave reiniciada" if password.strip() else ""),
    )
    return RedirectResponse(url="/admin?user_updated=1&panel=admin-team", status_code=303)


@router.post("/admin/users/{user_id}/toggle")
async def toggle_user(
    request: Request,
    user_id: int,
    is_active: int = Form(...),
    organization_id: int = Form(0),
    location_id: int = Form(0),
    full_name: str = Form(""),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Tu rol no puede gestionar miembros del equipo.")
    target_user = next((item for item in list_users() if int(item["id"]) == user_id), None)
    if target_user is None or int(target_user.get("organization_id") or 0) != int(user["organization_id"]):
        return redirect_to_module_with_error("/admin", "Ese usuario no pertenece a tu organización.")
    if user_id == user["id"] and is_active:
        return redirect_to_module_with_error("/admin", "No puedes eliminar tu propio acceso administrativo.")
    next_state = not bool(is_active)
    set_user_active(user_id, next_state)
    log_audit_event(
        user_id=user["id"],
        organization_id=int(target_user["organization_id"]),
        location_id=int(target_user["location_id"]),
        action="Restauracion" if next_state else "Eliminacion",
        entity_type="Usuario",
        entity_label=full_name or f"Usuario #{user_id}",
        detail="Acceso restaurado" if next_state else "Acceso retirado; historial conservado",
    )
    result = "member_restored" if next_state else "member_removed"
    return RedirectResponse(url=f"/admin?{result}=1&panel=admin-team", status_code=303)


@router.post("/admin/users/{user_id}/delete")
async def permanently_delete_user(request: Request, user_id: int) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Tu rol no puede eliminar miembros definitivamente.")
    organization_id = int(user["organization_id"])
    target = next((item for item in list_users() if int(item["id"]) == user_id), None)
    if target is None or int(target.get("organization_id") or 0) != organization_id:
        return RedirectResponse(url=f"/admin?member_delete_error={encoded_message('Ese miembro no pertenece a tu organización.')}&panel=admin-team", status_code=303)
    if user_id == int(user["id"]):
        return RedirectResponse(url=f"/admin?member_delete_error={encoded_message('No puedes eliminar definitivamente tu propio usuario.')}&panel=admin-team", status_code=303)
    if target.get("is_active"):
        return RedirectResponse(url=f"/admin?member_delete_error={encoded_message('Primero retira el acceso del miembro y luego podrás solicitar su eliminación definitiva.')}&panel=admin-team", status_code=303)

    references = (
        ("auditorías", "audit_events", "user_id"),
        ("aceptaciones", "legal_acceptances", "user_id"),
        ("movimientos de inventario", "inventory_movements", "user_id"),
        ("registros de cadena de frío", "cold_chain_logs", "user_id"),
        ("solicitudes de inventario", "inventory_replenishments", "requested_by_user_id"),
        ("revisiones de inventario", "inventory_replenishments", "reviewed_by_user_id"),
        ("citas", "appointments", "veterinarian_user_id"),
        ("listas de espera", "appointment_waitlist", "veterinarian_user_id"),
        ("bloqueos de agenda", "appointment_blocks", "veterinarian_user_id"),
        ("cambios de pacientes", "patients", "updated_by_user_id"),
        ("alertas creadas", "alerts", "created_by"),
        ("alertas asignadas", "alerts", "assigned_user_id"),
        ("confirmaciones de alertas", "alert_acknowledgements", "user_id"),
        ("entregas de turno", "shift_handoffs", "created_by"),
        ("preferencias del tablero", "dashboard_preferences", "user_id"),
        ("solicitudes de recuperación", "password_reset_tokens", "user_id"),
        ("recepciones de inventario", "inventory_items", "received_by_user_id"),
    )
    with get_connection() as connection:
        for _label, table, column in references:
            row = connection.execute(
                f'SELECT COUNT(*) AS total FROM "{table}" WHERE "{column}" = ?',
                (user_id,),
            ).fetchone()
            if int(row["total"] or 0):
                message = "No se puede borrar: este usuario conserva registros de actividad o historial vinculados. Se mantuvo eliminado de la operación para proteger la trazabilidad."
                return RedirectResponse(url=f"/admin?member_delete_error={encoded_message(message)}&panel=admin-team", status_code=303)
        try:
            connection.execute(
                "DELETE FROM users WHERE id = ? AND organization_id = ? AND is_active = 0",
                (user_id, organization_id),
            )
            connection.commit()
        except sqlite3.IntegrityError:
            connection.rollback()
            message = "No se puede borrar: hay otros registros vinculados a este usuario. Se conservó el registro eliminado para proteger el historial."
            return RedirectResponse(url=f"/admin?member_delete_error={encoded_message(message)}&panel=admin-team", status_code=303)
    log_audit_event(
        user_id=user["id"], organization_id=organization_id, location_id=None,
        action="Eliminacion", entity_type="Usuario", entity_label=target["full_name"],
        detail="Cuenta eliminada definitivamente tras verificar que no tenía registros asociados",
    )
    return RedirectResponse(url="/admin?member_deleted=1&panel=admin-team", status_code=303)


@router.post("/admin/users/{user_id}/permissions")
async def update_existing_user_permissions(
    request: Request,
    user_id: int,
    permission_mode: str = Form("role"),
    allowed_permissions: list[str] = Form(default=[]),
    organization_id: int = Form(...),
    location_id: int = Form(...),
    full_name: str = Form(""),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/", "Tu rol no puede configurar permisos.")
    target_user = next((item for item in list_users() if int(item["id"]) == user_id), None)
    if (
        target_user is None
        or int(target_user.get("organization_id") or 0) != int(user.get("organization_id") or 0)
        or int(target_user.get("organization_id") or 0) != organization_id
        or not inventory_scope_allowed(user, organization_id, location_id)
    ):
        return redirect_to_module_with_error("/admin", "Ese usuario no pertenece a tu organizacion.")

    known_permissions = set(role_permissions("owner"))
    overrides = {} if permission_mode == "role" else {
        key: key in allowed_permissions for key in known_permissions
    }
    if user_id == user["id"] and overrides and not overrides.get("manage_admin"):
        return redirect_to_module_with_error("/admin", "No puedes retirar tu propio acceso administrativo.")
    update_user_permissions(user_id, overrides)
    log_audit_event(
        user_id=user["id"],
        organization_id=organization_id,
        location_id=location_id,
        action="Actualizacion",
        entity_type="Permisos de usuario",
        entity_label=full_name or f"Usuario #{user_id}",
        detail="Perfil del rol" if not overrides else "Permisos personalizados",
    )
    return RedirectResponse(url="/admin?permissions_saved=1&panel=admin-team", status_code=303)


@router.post("/admin/users/{user_id}/schedule")
async def save_admin_user_schedule(
    request: Request,
    user_id: int,
    working_days: list[str] = Form(default=[]),
    work_start: str = Form(...),
    work_end: str = Form(...),
    break_start: str = Form(""),
    break_end: str = Form(""),
    unavailable_dates: str = Form(""),
    organization_id: int = Form(...),
    location_id: int = Form(...),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    target = next((item for item in list_users() if int(item["id"]) == user_id), None)
    if (not user["permissions"]["manage_admin"] or target is None
            or int(target.get("organization_id") or 0) != int(user["organization_id"])
            or organization_id != int(user["organization_id"])
            or int(target.get("location_id") or 0) != location_id
            or not inventory_scope_allowed(user, organization_id, location_id)):
        return redirect_to_module_with_error("/admin", "No puedes cambiar la disponibilidad de ese usuario.")
    if (not working_days or any(day not in {"0", "1", "2", "3", "4", "5", "6"} for day in working_days)
            or work_start >= work_end or bool(break_start) != bool(break_end)
            or (break_start and not (work_start <= break_start < break_end <= work_end))):
        return RedirectResponse(url="/admin?permission_error=Revisa+días%2C+horario+y+descanso.&panel=admin-team", status_code=303)
    dates = [value.strip() for value in unavailable_dates.split(",") if value.strip()]
    try:
        for value in dates:
            date.fromisoformat(value)
    except ValueError:
        return RedirectResponse(url="/admin?permission_error=Usa+fechas+válidas+AAAA-MM-DD+para+las+ausencias.&panel=admin-team", status_code=303)
    update_user_schedule(user_id, {
        "working_days": ",".join(sorted(set(working_days))), "work_start": work_start, "work_end": work_end,
        "break_start": break_start, "break_end": break_end, "unavailable_dates": ",".join(dates),
    })
    log_audit_event(user_id=user["id"], organization_id=organization_id, location_id=location_id,
                    action="Actualización", entity_type="Disponibilidad profesional", entity_label=target["full_name"],
                    detail=f"{work_start}–{work_end} | descanso {break_start or 'sin descanso'}")
    return RedirectResponse(url="/admin?schedule_saved=1&panel=admin-team", status_code=303)


@router.post("/alerts")
async def create_manual_alert(
    request: Request,
    organization_id: int = Form(...),
    location_id: int = Form(...),
    title: str = Form(...),
    message: str = Form(""),
    due_at: str = Form(...),
    priority: str = Form("normal"),
    recurrence: str = Form("once"),
    escalation_minutes: int = Form(0),
    assigned_user_id: int = Form(0),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["view_inventory"] or not inventory_scope_allowed(user, organization_id, location_id):
        return RedirectResponse(url=f"/alertas?notice={encoded_message('No puedes programar alertas para esta sede.')}", status_code=303)
    safe_priority = priority if priority in {"normal", "important", "urgent"} else "normal"
    safe_recurrence = recurrence if recurrence in {"once", "daily", "weekly", "monthly"} else "once"
    valid_assignees = {
        item["id"] for item in list_users()
        if item["is_active"] and int(item["organization_id"] or 0) == organization_id
        and (item["role"] in {"owner", "admin"} or int(item["location_id"] or 0) == location_id)
    }
    safe_assigned_user_id = assigned_user_id if assigned_user_id in valid_assignees else 0
    create_alert({
        "organization_id": organization_id,
        "location_id": location_id,
        "created_by": user["id"],
        "assigned_user_id": safe_assigned_user_id,
        "title": title.strip(),
        "message": message.strip(),
        "due_at": due_at,
        "priority": safe_priority,
        "recurrence": safe_recurrence,
        "escalation_minutes": escalation_minutes if escalation_minutes in {0, 15, 30, 60, 120, 240} else 0,
    })
    log_audit_event(user_id=user["id"], organization_id=organization_id, location_id=location_id,
                    action="Creacion", entity_type="Alerta", entity_label=title.strip(),
                    detail=f"Prioridad {safe_priority} | repeticion {safe_recurrence} | escalamiento {escalation_minutes} min")
    suffix = build_scope_query(str(organization_id), str(location_id))
    return RedirectResponse(url=f"/alertas?saved=1&{suffix}", status_code=303)


@router.post("/alerts/{alert_id}/edit")
async def edit_manual_alert(
    request: Request,
    alert_id: int,
    organization_id: int = Form(...),
    location_id: int = Form(...),
    title: str = Form(...),
    message: str = Form(""),
    due_at: str = Form(...),
    priority: str = Form("normal"),
    recurrence: str = Form("once"),
    escalation_minutes: int = Form(0),
    assigned_user_id: int = Form(0),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["view_inventory"] or not alert_belongs_to_scope(alert_id, organization_id, location_id):
        return RedirectResponse(url=f"/alertas?notice={encoded_message('La alerta no pertenece a la sede activa.')}", status_code=303)
    safe_priority = priority if priority in {"normal", "important", "urgent"} else "normal"
    safe_recurrence = recurrence if recurrence in {"once", "daily", "weekly", "monthly"} else "once"
    valid_assignees = {
        item["id"] for item in list_users()
        if item["is_active"] and int(item["organization_id"] or 0) == organization_id
        and (item["role"] in {"owner", "admin"} or int(item["location_id"] or 0) == location_id)
    }
    updated = update_alert(alert_id, organization_id, location_id, {
        "title": title, "message": message, "due_at": due_at, "priority": safe_priority,
        "recurrence": safe_recurrence,
        "escalation_minutes": escalation_minutes if escalation_minutes in {0, 15, 30, 60, 120, 240} else 0,
        "assigned_user_id": assigned_user_id if assigned_user_id in valid_assignees else 0,
    })
    message_out = "Alerta actualizada; la confirmación de lectura se reinició."
    if updated:
        log_audit_event(user_id=user["id"], organization_id=organization_id, location_id=location_id,
                        action="Edicion", entity_type="Alerta", entity_label=title.strip(), detail=message_out)
    suffix = build_scope_query(str(organization_id), str(location_id))
    return RedirectResponse(url=f"/alertas?updated=1&notice={encoded_message(message_out)}&{suffix}", status_code=303)


@router.post("/alerts/{alert_id}/resolve")
async def resolve_manual_alert(request: Request, alert_id: int, organization_id: int = Form(0), location_id: int = Form(0)) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["view_inventory"] or not alert_belongs_to_scope(alert_id, organization_id, location_id):
        return RedirectResponse(url=f"/alertas?notice={encoded_message('La alerta no pertenece a la sede activa.')}", status_code=303)
    result = resolve_alert(alert_id, organization_id, location_id)
    suffix = build_scope_query(str(organization_id or ""), str(location_id or ""))
    message = "Alerta resuelta y retirada de pendientes."
    if result and result["recurring"]:
        message = f"Alerta resuelta. Próximo aviso: {result['next_due']}."
    log_audit_event(user_id=user["id"], organization_id=organization_id, location_id=location_id,
                    action="Resolucion", entity_type="Alerta", entity_label=f"Alerta #{alert_id}", detail=message)
    separator = f"&{suffix}" if suffix else ""
    return RedirectResponse(url=f"/alertas?notice={encoded_message(message)}{separator}", status_code=303)


@router.post("/alerts/acknowledge")
async def acknowledge_operational_alert(
    request: Request,
    alert_key: str = Form(...),
    organization_id: int = Form(...),
    location_id: int = Form(...),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["view_inventory"] or not inventory_scope_allowed(user, organization_id, location_id):
        return RedirectResponse(url=f"/alertas?notice={encoded_message('No puedes confirmar alertas de esta sede.')}", status_code=303)
    confirmed = acknowledge_alert(alert_key.strip(), organization_id, location_id, user["id"])
    message = "Lectura confirmada. La alerta seguirá pendiente hasta corregir su causa."
    if not confirmed:
        message = "La alerta ya no está disponible en esta sede."
    else:
        log_audit_event(user_id=user["id"], organization_id=organization_id, location_id=location_id,
                        action="Confirmacion de lectura", entity_type="Alerta", entity_label=alert_key.strip(), detail=message)
    suffix = build_scope_query(str(organization_id), str(location_id))
    return RedirectResponse(url=f"/alertas?notice={encoded_message(message)}&{suffix}", status_code=303)


@router.post("/alerts/{alert_id}/snooze")
async def snooze_manual_alert(request: Request, alert_id: int, organization_id: int = Form(0), location_id: int = Form(0), hours: int = Form(24)) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["view_inventory"] or not alert_belongs_to_scope(alert_id, organization_id, location_id):
        return RedirectResponse(url=f"/alertas?notice={encoded_message('La alerta no pertenece a la sede activa.')}", status_code=303)
    safe_hours = hours if hours in {1, 4, 8, 24, 72, 168} else 24
    next_due = snooze_alert(alert_id, organization_id, location_id, safe_hours)
    suffix = build_scope_query(str(organization_id or ""), str(location_id or ""))
    duration_label = "1 hora" if safe_hours == 1 else f"{safe_hours} horas"
    message = f"Alerta pospuesta {duration_label}. Volverá el {next_due}."
    log_audit_event(user_id=user["id"], organization_id=organization_id, location_id=location_id,
                    action="Posposicion", entity_type="Alerta", entity_label=f"Alerta #{alert_id}", detail=message)
    separator = f"&{suffix}" if suffix else ""
    return RedirectResponse(url=f"/alertas?notice={encoded_message(message)}{separator}", status_code=303)


@router.post("/alerts/{alert_id}/delete")
async def delete_manual_alert(request: Request, alert_id: int, organization_id: int = Form(0), location_id: int = Form(0)) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_inventory"] or not alert_belongs_to_scope(alert_id, organization_id, location_id):
        return RedirectResponse(url=f"/alertas?notice={encoded_message('Tu rol no puede eliminar esta alerta.')}", status_code=303)
    delete_alert(alert_id, organization_id, location_id)
    log_audit_event(user_id=user["id"], organization_id=organization_id, location_id=location_id,
                    action="Eliminacion", entity_type="Alerta", entity_label=f"Alerta #{alert_id}", detail="Eliminada permanentemente")
    suffix = build_scope_query(str(organization_id or ""), str(location_id or ""))
    separator = f"&{suffix}" if suffix else ""
    return RedirectResponse(url=f"/alertas?notice={encoded_message('Alerta eliminada permanentemente.')}{separator}", status_code=303)


@router.post("/inventory")
async def create_inventory(
    request: Request,
    organization_id: int = Form(...),
    location_id: int = Form(...),
    name: str = Form(...),
    barcode: str = Form(""),
    category: str = Form(...),
    brand: str = Form(...),
    regulatory_agency: str = Form(...),
    regulatory_code: str = Form(...),
    supplier: str = Form(""),
    lot: str = Form(...),
    quantity: float = Form(...),
    min_stock: float = Form(...),
    unit_cost: float = Form(0),
    sale_price: float = Form(0),
    storage_condition: str = Form(""),
    requires_cold_chain: int = Form(0),
    location: str = Form(...),
    last_counted_at: str = Form(""),
    expiry_date: str = Form(...),
    product_id: int = Form(0),
    item_type: str = Form("Medicamento"),
    unit_measure: str = Form("unidades"),
    manufacturer: str = Form(""),
    received_date: str = Form(...),
    document_number: str = Form(...),
    presentation: str = Form(""),
    concentration: str = Form(""),
    serial_number: str = Form(""),
    reception_temperature_c: float | None = Form(None),
    reception_note: str = Form(""),
    is_test: int = Form(0),
    replenishment_request_id: int = Form(0),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_inventory"]:
        return redirect_to_module_with_error("/inventario", "Tu rol no puede registrar productos.")
    if not inventory_scope_allowed(user, organization_id, location_id):
        return redirect_to_module_with_error("/inventario", "La sede no pertenece a tu organización.")

    try:
        create_inventory_item({
            "organization_id": organization_id,
            "location_id": location_id,
            "name": name.strip(),
            "barcode": barcode.strip(),
            "category": category.strip(),
            "brand": brand.strip(),
            "regulatory_agency": regulatory_agency.strip(),
            "regulatory_code": regulatory_code.strip(),
            "supplier": supplier.strip(),
            "lot": lot.strip(),
            "quantity": quantity,
            "min_stock": min_stock,
            "unit_cost": unit_cost,
            "sale_price": sale_price,
            "storage_condition": storage_condition.strip(),
            "requires_cold_chain": requires_cold_chain,
            "location": location.strip(),
            "last_counted_at": last_counted_at,
            "expiry_date": expiry_date,
            "product_id": product_id or None,
            "item_type": item_type.strip(),
            "unit_measure": unit_measure.strip(),
            "manufacturer": manufacturer.strip(),
            "received_date": received_date,
            "document_number": document_number.strip(),
            "presentation": presentation.strip(),
            "concentration": concentration.strip(),
            "serial_number": serial_number.strip(),
            "reception_temperature_c": reception_temperature_c,
            "reception_note": reception_note.strip(),
            "received_by_user_id": user["id"],
            "is_test": is_test,
            "replenishment_request_id": replenishment_request_id or None,
        })
    except ValueError as exc:
        return redirect_to_module_with_error("/inventario", str(exc))
    log_audit_event(
        user_id=user["id"],
        organization_id=organization_id,
        location_id=location_id,
        action="Creacion",
        entity_type="Inventario",
        entity_label=name.strip(),
        detail=f"Lote {lot.strip()} | proveedor {supplier.strip() or 'sin proveedor'} | stock inicial {quantity}",
    )
    suffix = build_scope_query(str(organization_id), str(location_id))
    return RedirectResponse(url=f"/inventario?saved=1&{suffix}", status_code=303)


@router.get("/inventario/export")
async def export_inventory(
    request: Request,
    search: str = Query(default=""),
    category: str = Query(default=""),
    status: str = Query(default=""),
    item_type: str = Query(default=""),
    expiry: str = Query(default=""),
    organization_id: str = Query(default=""),
    location_id: str = Query(default=""),
):
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["view_inventory"]:
        return redirect_to_module_with_error("/inventario", "Tu rol no puede exportar inventario.")
    effective_org = organization_id or request.session.get("preferred_organization_id", "")
    effective_location = location_id or request.session.get("preferred_location_id", "")
    if not effective_org or not effective_location or not inventory_scope_allowed(user, int(effective_org), int(effective_location)):
        return redirect_to_module_with_error("/inventario", "No puedes exportar información de otra organización.")
    items = list_inventory_items(
        search=search,
        category=category,
        status=status,
        item_type=item_type,
        expiry=expiry,
        organization_id=effective_org,
        location_id=effective_location,
    )
    return Response(
        content=build_inventory_csv(items),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="velmorax-inventario.csv"'},
    )


@router.get("/inventario/historial/export")
async def export_inventory_history(
    request: Request,
    organization_id: str = Query(default=""),
    location_id: str = Query(default=""),
):
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["view_inventory"]:
        return redirect_to_module_with_error("/inventario", "Tu rol no puede exportar el historial.")
    effective_org = organization_id or request.session.get("preferred_organization_id", "")
    effective_location = location_id or request.session.get("preferred_location_id", "")
    if not effective_org or not effective_location or not inventory_scope_allowed(user, int(effective_org), int(effective_location)):
        return redirect_to_module_with_error("/inventario", "No puedes exportar información de otra organización.")
    movements = list_recent_movements(
        limit=1000,
        organization_id=effective_org,
        location_id=effective_location,
    )
    return Response(
        content=build_inventory_movements_csv(movements),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="velmorax-trazabilidad-insumos.csv"'},
    )


@router.post("/inventory/{item_id}/delete")
async def delete_inventory(
    request: Request,
    item_id: int,
    organization_id: int = Form(0),
    location_id: int = Form(0),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/inventario", "Solo administración puede borrar un registro creado por error.")
    if not inventory_item_scope_allowed(user, item_id, organization_id, location_id):
        return redirect_to_module_with_error("/inventario", "El lote no pertenece a la sede seleccionada.")

    try:
        delete_inventory_item(item_id)
    except ValueError as exc:
        return redirect_to_module_with_error("/inventario", str(exc))
    log_audit_event(
        user_id=user["id"],
        organization_id=organization_id or None,
        location_id=location_id or None,
        action="Eliminacion",
        entity_type="Inventario",
        entity_label=f"Item #{item_id}",
        detail="Producto eliminado desde tablero web",
    )
    suffix = build_scope_query(str(organization_id or ""), str(location_id or ""))
    return RedirectResponse(url=f"/inventario?{suffix}" if suffix else "/inventario", status_code=303)


@router.post("/inventory/{item_id}/edit")
async def edit_inventory(
    request: Request,
    item_id: int,
    organization_id: int = Form(...), location_id: int = Form(...),
    name: str = Form(...), brand: str = Form(...), supplier: str = Form(""),
    barcode: str = Form(""), regulatory_code: str = Form(...), lot: str = Form(...),
    expiry_date: str = Form(...), min_stock: float = Form(...), unit_cost: float = Form(0),
    sale_price: float = Form(0), location: str = Form(...), storage_condition: str = Form(""),
    requires_cold_chain: int = Form(0), item_type: str = Form("Medicamento"),
    unit_measure: str = Form("unidades"),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_inventory"]:
        return redirect_to_module_with_error("/inventario", "Tu rol no puede editar lotes.")
    if not inventory_item_scope_allowed(user, item_id, organization_id, location_id):
        return redirect_to_module_with_error("/inventario", "El lote no pertenece a la sede seleccionada.")
    try:
        update_inventory_item(item_id, locals())
    except ValueError as exc:
        return redirect_to_module_with_error("/inventario", str(exc))
    log_audit_event(user_id=user["id"], organization_id=organization_id, location_id=location_id,
                    action="Edicion", entity_type="Inventario", entity_label=name.strip(), detail=f"Lote {lot.strip()} actualizado")
    suffix = build_scope_query(str(organization_id), str(location_id))
    return RedirectResponse(url=f"/inventario?saved=1&{suffix}#inventory-item-{item_id}", status_code=303)


@router.post("/inventory/{item_id}/retire")
async def retire_inventory(
    request: Request, item_id: int, quantity: float = Form(...), reason: str = Form(...),
    organization_id: int = Form(0), location_id: int = Form(0),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_inventory"]:
        return redirect_to_module_with_error("/inventario", "Tu rol no puede retirar existencias.")
    if not inventory_item_scope_allowed(user, item_id, organization_id, location_id):
        return redirect_to_module_with_error("/inventario", "El lote no pertenece a la sede seleccionada.")
    ok, message = retire_inventory_lot(item_id, quantity, reason, user["id"])
    suffix = build_scope_query(str(organization_id or ""), str(location_id or ""))
    if not ok:
        return RedirectResponse(url=f"/inventario?movement_error={encoded_message(message)}&{suffix}", status_code=303)
    log_audit_event(user_id=user["id"], organization_id=organization_id or None, location_id=location_id or None,
                    action="Retiro", entity_type="Inventario", entity_label=f"Lote #{item_id}", detail=f"{quantity:g} | {reason.strip()}")
    return RedirectResponse(
        url=f"/inventario?moved=1&notice={encoded_message(message)}&{suffix}",
        status_code=303,
    )


@router.post("/inventory/{item_id}/count")
async def count_inventory(
    request: Request, item_id: int, counted_quantity: float = Form(...), note: str = Form("Conteo físico"),
    organization_id: int = Form(0), location_id: int = Form(0),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_inventory"]:
        return redirect_to_module_with_error("/inventario", "Tu rol no puede realizar conteos.")
    if not inventory_item_scope_allowed(user, item_id, organization_id, location_id):
        return redirect_to_module_with_error("/inventario", "El lote no pertenece a la sede seleccionada.")
    ok, message = count_inventory_item(item_id, counted_quantity, note, user["id"])
    suffix = build_scope_query(str(organization_id or ""), str(location_id or ""))
    key = f"moved=1&notice={encoded_message(message)}" if ok else f"movement_error={encoded_message(message)}"
    return RedirectResponse(url=f"/inventario?{key}&{suffix}#inventory-item-{item_id}", status_code=303)


@router.post("/inventory/{item_id}/cold-chain")
async def cold_chain_inventory(
    request: Request, item_id: int, temperature_c: float = Form(...), note: str = Form(""),
    organization_id: int = Form(0), location_id: int = Form(0),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_inventory"]:
        return redirect_to_module_with_error("/inventario", "Tu rol no puede registrar temperaturas.")
    if not inventory_item_scope_allowed(user, item_id, organization_id, location_id):
        return redirect_to_module_with_error("/inventario", "El lote no pertenece a la sede seleccionada.")
    ok, message = record_cold_chain(item_id, temperature_c, note, user["id"])
    suffix = build_scope_query(str(organization_id or ""), str(location_id or ""))
    key = f"moved=1&notice={encoded_message(message)}" if ok else f"movement_error={encoded_message(message)}"
    return RedirectResponse(url=f"/inventario?{key}&{suffix}#inventory-item-{item_id}", status_code=303)


@router.post("/inventory/movements")
async def create_movement(
    request: Request,
    item_id: int = Form(...),
    movement_type: str = Form(...),
    quantity: float = Form(...),
    note: str = Form(...),
    reason_type: str = Form("Movimiento"),
    organization_id: int = Form(0),
    location_id: int = Form(0),
    patient_id: int = Form(0),
    appointment_id: int = Form(0),
    priority: str = Form("Normal"),
    external_reference: str = Form(""),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_inventory"] and not (
        user["permissions"].get("consume_inventory") and movement_type == "out" and reason_type == "Consumo clínico"
    ):
        return redirect_to_module_with_error("/inventario", "Tu rol no puede registrar movimientos.")
    if reason_type.strip().startswith("Traslado"):
        return redirect_to_module_with_error(
            "/inventario", "Usa la opción Trasladar para conservar el registro en ambas sedes."
        )
    if not inventory_item_scope_allowed(user, item_id, organization_id, location_id):
        return redirect_to_module_with_error("/inventario", "El lote no pertenece a la sede seleccionada.")

    ok, message = create_inventory_movement(
        item_id=item_id,
        movement_type=movement_type.strip(),
        quantity=quantity,
        note=note,
        user_id=user["id"],
        reason_type=reason_type,
        patient_id=patient_id or None,
        appointment_id=appointment_id or None,
        priority=priority if priority in {"Normal", "Urgente"} else "Normal",
        external_reference=external_reference,
    )
    suffix = build_scope_query(str(organization_id or ""), str(location_id or ""))
    if ok:
        log_audit_event(
            user_id=user["id"],
            organization_id=organization_id or None,
            location_id=location_id or None,
            action="Movimiento",
            entity_type="Inventario",
            entity_label=f"Item #{item_id}",
            detail=f"{reason_type.strip()} | {movement_type.strip()} x{quantity} | {note.strip()}",
        )
        patient = next((item for item in list_patients(organization_id=str(organization_id), location_id=str(location_id)) if item["id"] == patient_id), None)
        linked_label = f" para {patient['display_name']}" if patient else ""
        notice = encoded_message(f"{reason_type.strip()} registrado{linked_label}. Existencias actualizadas.")
        return RedirectResponse(
            url=f"/inventario?moved=1&notice={notice}&{suffix}" if suffix else f"/inventario?moved=1&notice={notice}",
            status_code=303,
        )

    return RedirectResponse(
        url=f"/inventario?movement_error={message}&{suffix}" if suffix else f"/inventario?movement_error={message}",
        status_code=303,
    )


@router.post("/inventory/{item_id}/quarantine")
async def quarantine_inventory_lot(
    request: Request,
    item_id: int,
    enabled: int = Form(1),
    reason: str = Form(""),
    organization_id: int = Form(0),
    location_id: int = Form(0),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_inventory"]:
        return redirect_to_module_with_error("/inventario", "Tu rol no puede administrar cuarentenas.")
    if not inventory_item_scope_allowed(user, item_id, organization_id, location_id):
        return redirect_to_module_with_error("/inventario", "El lote no pertenece a la sede seleccionada.")
    ok, message = set_inventory_quarantine(item_id, bool(enabled), reason)
    suffix = build_scope_query(str(organization_id or ""), str(location_id or ""))
    if ok:
        log_audit_event(
            user_id=user["id"], organization_id=organization_id or None, location_id=location_id or None,
            action="Cuarentena" if enabled else "Liberación", entity_type="Inventario",
            entity_label=f"Item #{item_id}", detail=reason.strip() or "Lote liberado",
        )
    key = f"saved=1&notice={encoded_message(message)}" if ok else f"movement_error={encoded_message(message)}"
    return RedirectResponse(url=f"/inventario?{key}&{suffix}#inventory-item-{item_id}", status_code=303)


@router.post("/inventory/{item_id}/transfer")
async def transfer_inventory_lot(
    request: Request,
    item_id: int,
    quantity: float = Form(...),
    destination_location_id: int = Form(...),
    destination_storage: str = Form(...),
    note: str = Form(...),
    organization_id: int = Form(0),
    location_id: int = Form(0),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_inventory"]:
        return redirect_to_module_with_error("/inventario", "Tu rol no puede trasladar inventario.")
    if not inventory_item_scope_allowed(user, item_id, organization_id, location_id):
        return redirect_to_module_with_error("/inventario", "El lote no pertenece a la sede seleccionada.")
    destination = get_location_by_id(str(destination_location_id))
    if not destination or int(destination["organization_id"]) != organization_id:
        return redirect_to_module_with_error("/inventario", "La sede de destino no pertenece a tu organización.")
    ok, message, reference = transfer_inventory_item(
        item_id, quantity, destination_location_id, destination_storage, note, user["id"]
    )
    suffix = build_scope_query(str(organization_id or ""), str(location_id or ""))
    if ok:
        log_audit_event(
            user_id=user["id"], organization_id=organization_id or None, location_id=location_id or None,
            action="Traslado", entity_type="Inventario", entity_label=f"Item #{item_id}",
            detail=f"{reference} | {quantity} | destino {destination_location_id} | {note.strip()}",
        )
    key = f"moved=1&notice={encoded_message(message + (' Referencia ' + reference if reference else ''))}" if ok else f"movement_error={encoded_message(message)}"
    return RedirectResponse(url=f"/inventario?{key}&{suffix}", status_code=303)


@router.post("/inventory/replenishments")
async def request_inventory_replenishment(
    request: Request,
    item_id: int = Form(...),
    requested_quantity: float = Form(...),
    supplier: str = Form(...),
    priority: str = Form("Normal"),
    note: str = Form(""),
    organization_id: int = Form(...),
    location_id: int = Form(...),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_inventory"]:
        return redirect_to_module_with_error("/inventario", "Tu rol no puede solicitar abastecimiento.")
    if not inventory_item_scope_allowed(user, item_id, organization_id, location_id):
        return redirect_to_module_with_error("/inventario", "El lote no pertenece a la sede seleccionada.")
    ok, message = create_inventory_replenishment(
        item_id, requested_quantity, supplier, priority, note, user["id"]
    )
    if ok:
        log_audit_event(
            user_id=user["id"], organization_id=organization_id, location_id=location_id,
            action="Solicitud de abastecimiento", entity_type="Inventario",
            entity_label=f"Item #{item_id}", detail=f"{requested_quantity} | {priority} | {supplier.strip()}",
        )
    suffix = build_scope_query(str(organization_id), str(location_id))
    key = f"saved=1&notice={encoded_message(message)}" if ok else f"movement_error={encoded_message(message)}"
    return RedirectResponse(url=f"/inventario?{key}&{suffix}", status_code=303)


@router.post("/inventory/replenishments/{replenishment_id}/review")
async def review_replenishment(
    request: Request,
    replenishment_id: int,
    decision: str = Form(...),
    organization_id: int = Form(...),
    location_id: int = Form(...),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"].get("approve_inventory"):
        return redirect_to_module_with_error("/inventario", "Tu rol no puede aprobar abastecimiento.")
    if not inventory_scope_allowed(user, organization_id, location_id):
        return redirect_to_module_with_error("/inventario", "La sede no pertenece a tu organización.")
    ok, message = review_inventory_replenishment(
        replenishment_id, decision, user["id"], organization_id, location_id
    )
    if ok:
        log_audit_event(
            user_id=user["id"], organization_id=organization_id, location_id=location_id,
            action="Revisión de abastecimiento", entity_type="Inventario",
            entity_label=f"Solicitud #{replenishment_id}", detail=message,
        )
    suffix = build_scope_query(str(organization_id), str(location_id))
    key = f"saved=1&notice={encoded_message(message)}" if ok else f"movement_error={encoded_message(message)}"
    return RedirectResponse(url=f"/inventario?{key}&{suffix}", status_code=303)


@router.post("/appointments")
async def create_new_appointment(
    request: Request,
    organization_id: int = Form(...),
    location_id: int = Form(...),
    appointment_date: str = Form(...),
    appointment_time: str = Form(...),
    patient_id: int = Form(...),
    service: str = Form(...),
    channel: str = Form(...),
    status: str = Form(...),
    specialty: str = Form(...),
    note: str = Form(...),
    duration_minutes: int = Form(30),
    veterinarian_user_id: int = Form(...),
    priority: str = Form("Normal"),
    triage_level: str = Form(""),
    triage_note: str = Form(""),
    resource_id: int = Form(0),
    reminder_channel: str = Form(""),
    recurrence_interval_days: int = Form(0),
    recurrence_occurrences: int = Form(1),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_agenda"]:
        return redirect_to_module_with_error("/agenda", "Tu rol no puede registrar citas.")

    patients = list_patients(organization_id=str(organization_id), location_id=str(location_id))
    patient = next((item for item in patients if item["id"] == patient_id), None)
    provider = get_user_by_id(veterinarian_user_id)
    if patient is None or provider is None or (
        provider["location_id"] != location_id and provider["role"] not in {"admin", "owner"}
    ):
        return redirect_to_module_with_error("/agenda", "Selecciona un paciente y veterinario válidos.")
    patient_name = patient["display_name"]
    try:
        appointment_payload = {
            "organization_id": organization_id,
            "location_id": location_id,
            "appointment_date": appointment_date,
            "appointment_time": appointment_time,
            "patient_name": patient_name.strip(),
            "service": service.strip(),
            "channel": channel.strip(),
            "status": status.strip(),
            "specialty": specialty.strip(),
            "note": note.strip(),
            "duration_minutes": duration_minutes,
            "veterinarian": provider["full_name"],
            "patient_id": patient_id,
            "veterinarian_user_id": veterinarian_user_id,
            "cancellation_reason": "",
            "priority": "Urgente" if priority == "Urgente" else "Normal",
            "triage_level": triage_level,
            "triage_note": triage_note,
            "arrival_at": f"{appointment_date}T{appointment_time}" if priority == "Urgente" else "",
            "resource_id": resource_id or None,
            "resource_name": "",
            "reminder_channel": reminder_channel,
            "reminder_status": "Pendiente" if reminder_channel else "",
        }
        if recurrence_interval_days and recurrence_occurrences > 1:
            create_recurring_appointments(appointment_payload, recurrence_interval_days, recurrence_occurrences)
        else:
            create_appointment(appointment_payload)
        if reminder_channel:
            enqueue_integration_event(
                organization_id=organization_id,
                location_id=location_id,
                event_type=f"agenda.reminder.{reminder_channel.lower()}",
                event_key=f"agenda-reminder:{patient_id}:{appointment_date}:{appointment_time}:{reminder_channel.lower()}",
                payload={
                    "patient_id": patient_id,
                    "appointment_date": appointment_date,
                    "appointment_time": appointment_time,
                    "service": service.strip(),
                    "channel": reminder_channel,
                },
            )
    except ValueError as exc:
        suffix = build_scope_query(str(organization_id), str(location_id), appointment_date)
        return RedirectResponse(url=f"/agenda?agenda_error={quote(str(exc))}&{suffix}", status_code=303)
    log_audit_event(
        user_id=user["id"],
        organization_id=organization_id,
        location_id=location_id,
        action="Creacion",
        entity_type="Agenda",
        entity_label=patient_name.strip(),
        detail=f"{appointment_date} {appointment_time} | {service.strip()}",
    )
    suffix = build_scope_query(str(organization_id), str(location_id), appointment_date)
    return RedirectResponse(url=f"/agenda?appointment_saved=1&{suffix}", status_code=303)


@router.post("/agenda/professionals/{professional_id}/schedule")
async def save_professional_schedule(
    request: Request,
    professional_id: int,
    working_days: list[str] = Form(default=[]),
    work_start: str = Form(...),
    work_end: str = Form(...),
    break_start: str = Form(""),
    break_end: str = Form(""),
    unavailable_dates: str = Form(""),
    day: str = Form(""),
    organization_id: int = Form(0),
    location_id: int = Form(0),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/agenda", "Solo un administrador puede cambiar la disponibilidad.")
    if not working_days or work_start >= work_end:
        return redirect_to_module_with_error("/agenda", "Revisa los días y el horario laboral.")
    update_user_schedule(professional_id, {
        "working_days": ",".join(sorted(working_days)),
        "work_start": work_start, "work_end": work_end,
        "break_start": break_start, "break_end": break_end,
        "unavailable_dates": ",".join(value.strip() for value in unavailable_dates.split(",") if value.strip()),
    })
    suffix = build_scope_query(str(organization_id or ""), str(location_id or ""), day)
    return RedirectResponse(url=f"/agenda?appointment_updated=1&{suffix}", status_code=303)


@router.post("/appointments/{appointment_id}/reschedule")
async def quick_reschedule_appointment(
    request: Request, appointment_id: int, appointment_date: str = Form(...), appointment_time: str = Form(...),
    organization_id: int = Form(...), location_id: int = Form(...),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_agenda"] or not appointment_belongs_to_scope(appointment_id, organization_id, location_id):
        return redirect_to_module_with_error("/agenda", "No puedes reprogramar esta cita.")
    try:
        reschedule_appointment(appointment_id, appointment_date, appointment_time)
    except ValueError as exc:
        return RedirectResponse(url=f"/agenda?agenda_error={quote(str(exc))}&{build_scope_query(str(organization_id), str(location_id), appointment_date)}", status_code=303)
    log_audit_event(user_id=user["id"], organization_id=organization_id, location_id=location_id, action="Reprogramó cita", entity_type="Agenda", entity_label=f"Cita #{appointment_id}", detail=f"{appointment_date} {appointment_time}")
    return RedirectResponse(url=f"/agenda?appointment_updated=1&{build_scope_query(str(organization_id), str(location_id), appointment_date)}", status_code=303)


@router.post("/agenda/waitlist")
async def add_to_waitlist(
    request: Request, organization_id: int = Form(...), location_id: int = Form(...), patient_id: int = Form(...),
    service: str = Form(...), veterinarian_user_id: int = Form(0), requested_date: str = Form(""), preferred_time: str = Form(""),
    priority: str = Form("Normal"), channel: str = Form("Correo"), note: str = Form(""),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_agenda"] or not inventory_scope_allowed(user, organization_id, location_id):
        return redirect_to_module_with_error("/agenda", "No puedes gestionar la lista de espera.")
    create_waitlist_entry({"organization_id": organization_id, "location_id": location_id, "patient_id": patient_id, "service": service.strip(), "veterinarian_user_id": veterinarian_user_id or None, "requested_date": requested_date, "preferred_time": preferred_time, "priority": "Urgente" if priority == "Urgente" else "Normal", "channel": channel, "note": note.strip()})
    log_audit_event(user_id=user["id"], organization_id=organization_id, location_id=location_id, action="Agregó lista de espera", entity_type="Agenda", entity_label=service.strip())
    return RedirectResponse(url=f"/agenda?appointment_updated=1&{build_scope_query(str(organization_id), str(location_id), requested_date)}", status_code=303)


@router.post("/agenda/resources")
async def add_agenda_resource(
    request: Request, organization_id: int = Form(...), location_id: int = Form(...), name: str = Form(...), resource_type: str = Form("Consultorio"),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"] or not inventory_scope_allowed(user, organization_id, location_id):
        return redirect_to_module_with_error("/agenda", "Solo administración puede crear recursos.")
    if name.strip():
        create_appointment_resource(organization_id, location_id, name, resource_type)
        log_audit_event(user_id=user["id"], organization_id=organization_id, location_id=location_id, action="Creó recurso de agenda", entity_type="Agenda", entity_label=name.strip())
    return RedirectResponse(url=f"/agenda?appointment_updated=1&{build_scope_query(str(organization_id), str(location_id))}", status_code=303)


@router.post("/agenda/blocks")
async def add_agenda_block(
    request: Request, organization_id: int = Form(...), location_id: int = Form(...), veterinarian_user_id: int = Form(0),
    block_date: str = Form(...), start_time: str = Form(""), end_time: str = Form(""), block_type: str = Form("Ausencia"), note: str = Form(""),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"] or not inventory_scope_allowed(user, organization_id, location_id):
        return redirect_to_module_with_error("/agenda", "Solo administración puede bloquear agenda.")
    create_appointment_block({"organization_id": organization_id, "location_id": location_id, "veterinarian_user_id": veterinarian_user_id or None, "block_date": block_date, "start_time": start_time, "end_time": end_time, "block_type": block_type, "note": note.strip()})
    log_audit_event(user_id=user["id"], organization_id=organization_id, location_id=location_id, action="Bloqueó agenda", entity_type="Agenda", entity_label=block_type, detail=block_date)
    return RedirectResponse(url=f"/agenda?appointment_updated=1&{build_scope_query(str(organization_id), str(location_id), block_date)}", status_code=303)


@router.get("/agenda/export")
async def export_agenda(request: Request, day: str = Query(default=""), organization_id: str = Query(default=""), location_id: str = Query(default=""), veterinarian: str = Query(default="")) -> Response:
    user = user_with_permissions(request)
    if user is None:
        return Response(status_code=401)
    if not user["permissions"].get("export_dashboard", False):
        return Response("Tu rol no puede exportar la agenda.", status_code=403)
    selected_day = day or datetime.now().date().isoformat()
    items = list_appointments_between(selected_day, selected_day, organization_id, location_id)
    if veterinarian.isdigit():
        items = [item for item in items if item.get("veterinarian_user_id") == int(veterinarian)]
    output = StringIO(); writer = csv.writer(output)
    writer.writerow(["Agenda Velmorax", selected_day]); writer.writerow(["Hora", "Paciente", "Servicio", "Veterinario", "Estado", "Prioridad", "Recurso", "Llegada", "Espera (min)"])
    for item in items: writer.writerow([item["time"], item["patient"], item["service"], item["veterinarian"], item["status"], item["priority"], item["resource_name"], item["arrival_at"], item["wait_minutes"]])
    log_audit_event(user_id=user["id"], organization_id=int(organization_id or user["organization_id"]), location_id=int(location_id or user["location_id"]), action="Exportó agenda", entity_type="Agenda", entity_label=selected_day)
    return Response("\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="agenda-{selected_day}.csv"'})


@router.get("/agenda/imprimir", response_class=HTMLResponse)
async def print_agenda(
    request: Request,
    day: str = Query(default=""),
    organization_id: str = Query(default=""),
    location_id: str = Query(default=""),
    veterinarian: str = Query(default=""),
) -> HTMLResponse:
    user = user_with_permissions(request)
    if user is None:
        return HTMLResponse("Inicia sesión para imprimir la agenda.", status_code=401)
    if not user["permissions"].get("export_dashboard", False):
        return HTMLResponse("Tu rol no puede imprimir la agenda.", status_code=403)
    selected_day = day or datetime.now().date().isoformat()
    items = list_appointments_between(selected_day, selected_day, organization_id, location_id)
    professional = "Todos los profesionales"
    if veterinarian.isdigit():
        items = [item for item in items if item.get("veterinarian_user_id") == int(veterinarian)]
        professional = items[0]["veterinarian"] if items else "Profesional seleccionado"
    log_audit_event(
        user_id=user["id"], organization_id=int(organization_id or user["organization_id"]),
        location_id=int(location_id or user["location_id"]), action="Imprimió agenda",
        entity_type="Agenda", entity_label=selected_day,
    )
    return templates.TemplateResponse(request, "agenda_print.html", {
        "day": selected_day, "items": items, "professional": professional,
        "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
    })


@router.post("/appointments/{appointment_id}")
async def update_full_appointment(
    request: Request,
    appointment_id: int,
    appointment_date: str = Form(...),
    appointment_time: str = Form(...),
    patient_id: int = Form(...),
    service: str = Form(...),
    channel: str = Form(...),
    status: str = Form(...),
    specialty: str = Form("Veterinaria"),
    note: str = Form(""),
    duration_minutes: int = Form(30),
    veterinarian_user_id: int = Form(...),
    priority: str = Form("Normal"),
    triage_level: str = Form(""),
    triage_note: str = Form(""),
    resource_id: int = Form(0),
    reminder_channel: str = Form(""),
    organization_id: int = Form(0),
    location_id: int = Form(0),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_agenda"]:
        return redirect_to_module_with_error("/agenda", "Tu rol no puede editar citas.")
    if not appointment_belongs_to_scope(appointment_id, organization_id, location_id):
        return redirect_to_module_with_error("/agenda", "La cita no pertenece a la sede seleccionada.")
    patients = list_patients(organization_id=str(organization_id), location_id=str(location_id))
    patient = next((item for item in patients if item["id"] == patient_id), None)
    provider = get_user_by_id(veterinarian_user_id)
    if patient is None or provider is None or (
        provider["location_id"] != location_id and provider["role"] not in {"admin", "owner"}
    ):
        return redirect_to_module_with_error("/agenda", "Selecciona un paciente y veterinario válidos.")
    patient_name = patient["display_name"]
    try:
        update_appointment_record(appointment_id, {
        "appointment_date": appointment_date,
        "appointment_time": appointment_time,
        "patient_name": patient_name.strip(),
        "service": service.strip(),
        "channel": channel.strip(),
        "status": status.strip(),
        "specialty": specialty.strip(),
        "note": note.strip(),
        "duration_minutes": duration_minutes,
        "veterinarian": provider["full_name"],
        "patient_id": patient_id,
        "veterinarian_user_id": veterinarian_user_id,
        "location_id": location_id,
        "priority": "Urgente" if priority == "Urgente" else "Normal",
        "triage_level": triage_level,
        "triage_note": triage_note,
        "arrival_at": f"{appointment_date}T{appointment_time}" if priority == "Urgente" else "",
        "resource_id": resource_id or None,
        "resource_name": "",
        "reminder_channel": reminder_channel,
    })
    except ValueError as exc:
        suffix = build_scope_query(str(organization_id or ""), str(location_id or ""), appointment_date)
        return RedirectResponse(url=f"/agenda?agenda_error={quote(str(exc))}&{suffix}", status_code=303)
    log_audit_event(user_id=user["id"], organization_id=organization_id or None,
                    location_id=location_id or None, action="Actualizacion",
                    entity_type="Agenda", entity_label=patient_name.strip(),
                    detail=f"Cita #{appointment_id} actualizada para {appointment_date} {appointment_time}")
    suffix = build_scope_query(str(organization_id or ""), str(location_id or ""), appointment_date)
    return RedirectResponse(url=f"/agenda?appointment_updated=1&{suffix}", status_code=303)


@router.post("/appointments/{appointment_id}/status")
async def update_appointment(
    request: Request,
    appointment_id: int,
    status: str = Form(...),
    day: str = Form(""),
    organization_id: int = Form(0),
    location_id: int = Form(0),
    cancellation_reason: str = Form(""),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_agenda"]:
        return redirect_to_module_with_error("/agenda", "Tu rol no puede actualizar citas.")
    if not appointment_belongs_to_scope(appointment_id, organization_id, location_id):
        return redirect_to_module_with_error("/agenda", "La cita no pertenece a la sede seleccionada.")

    if status == "Cancelada" and not cancellation_reason.strip():
        return redirect_to_module_with_error("/agenda", "Indica el motivo de la cancelación.")
    update_appointment_status(appointment_id, status, cancellation_reason)
    if status == "Cancelada":
        notify_waitlist_of_opening(organization_id, location_id, day)
    log_audit_event(
        user_id=user["id"],
        organization_id=organization_id or None,
        location_id=location_id or None,
        action="Actualizacion",
        entity_type="Agenda",
        entity_label=f"Cita #{appointment_id}",
        detail=f"Estado cambiado a {status.strip()}",
    )
    suffix = build_scope_query(str(organization_id or ""), str(location_id or ""), day)
    return RedirectResponse(url=f"/agenda?{suffix}" if suffix else "/agenda", status_code=303)


@router.post("/appointments/{appointment_id}/delete")
async def remove_appointment(
    request: Request,
    appointment_id: int,
    day: str = Form(""),
    organization_id: int = Form(0),
    location_id: int = Form(0),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_admin"]:
        return redirect_to_module_with_error("/agenda", "Tu rol no puede eliminar citas.")
    if not appointment_belongs_to_scope(appointment_id, organization_id, location_id):
        return redirect_to_module_with_error("/agenda", "La cita no pertenece a la sede seleccionada.")

    delete_appointment(appointment_id)
    notify_waitlist_of_opening(organization_id, location_id, day)
    log_audit_event(
        user_id=user["id"],
        organization_id=organization_id or None,
        location_id=location_id or None,
        action="Eliminacion",
        entity_type="Agenda",
        entity_label=f"Cita #{appointment_id}",
        detail="Cita eliminada desde el modulo de agenda",
    )
    suffix = build_scope_query(str(organization_id or ""), str(location_id or ""), day)
    return RedirectResponse(url=f"/agenda?{suffix}" if suffix else "/agenda", status_code=303)


@router.post("/patients")
async def create_new_patient(
    request: Request,
    organization_id: int = Form(...),
    location_id: int = Form(...),
    display_name: str = Form(...),
    patient_type: str = Form(...),
    specialty: str = Form(...),
    owner_name: str = Form(""),
    phone: str = Form(""),
    document_number: str = Form(""),
    birth_date: str = Form(""),
    sex: str = Form(""),
    insurance_name: str = Form(""),
    species: str = Form(""),
    breed: str = Form(""),
    weight_kg: float = Form(0),
    vaccine_status: str = Form("No aplica"),
    color: str = Form(""),
    microchip: str = Form(""),
    tutor_email: str = Form(""),
    tutor_address: str = Form(""),
    emergency_contact_name: str = Form(""),
    emergency_contact_phone: str = Form(""),
    emergency_contact_relationship: str = Form(""),
    reproductive_status: str = Form(""),
    sterilized: int = Form(0),
    sterilization_date: str = Form(""),
    allergies: str = Form(""),
    preexisting_conditions: str = Form(""),
    medical_history: str = Form(""),
    deworming_status: str = Form(""),
    deworming_date: str = Form(""),
    next_deworming_due: str = Form(""),
    clinical_alert: str = Form(""),
    patient_status: str = Form("active"),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_clinical"]:
        return redirect_to_module_with_error("/clinica", "Tu rol no puede registrar pacientes.")
    if not inventory_scope_allowed(user, organization_id, location_id):
        return redirect_to_module_with_error(
            "/clinica",
            "La organización o sede seleccionada no pertenece a tu alcance.",
        )

    duplicate = find_patient_duplicate(
        organization_id=organization_id,
        location_id=location_id,
        display_name=display_name,
        owner_name=owner_name,
        document_number=document_number,
        microchip=microchip,
        species=species,
        birth_date=birth_date,
    )

    if duplicate:
        return redirect_to_module_with_error(
            "/clinica",
            f"La mascota '{duplicate['display_name']}' ya está registrada."
        )


    create_patient(
        {
            "organization_id": organization_id,
            "location_id": location_id,
            "display_name": display_name.strip(),
            "patient_type": patient_type.strip(),
            "specialty": specialty.strip(),
            "owner_name": owner_name.strip(),
            "phone": phone.strip(),
            "last_visit": "",
            "document_number": document_number.strip(),
            "birth_date": birth_date,
            "sex": sex.strip(),
            "insurance_name": insurance_name.strip(),
            "species": species.strip(),
            "breed": breed.strip(),
            "weight_kg": weight_kg,
            "vaccine_status": vaccine_status.strip(),
            "color": color.strip(),
            "microchip": microchip.strip(),
            "tutor_email": tutor_email.strip(),
            "tutor_address": tutor_address.strip(),
            "emergency_contact_name": emergency_contact_name.strip(),
            "emergency_contact_phone": emergency_contact_phone.strip(),
            "emergency_contact_relationship": emergency_contact_relationship.strip(),
            "reproductive_status": reproductive_status.strip(),
            "sterilized": int(bool(sterilized)),
            "sterilization_date": sterilization_date,
            "allergies": allergies.strip(),
            "preexisting_conditions": preexisting_conditions.strip(),
            "medical_history": medical_history.strip(),
            "deworming_status": deworming_status.strip(),
            "deworming_date": deworming_date,
            "next_deworming_due": next_deworming_due,
            "clinical_alert": clinical_alert.strip(),
            "patient_status": patient_status.strip() or "active",
            "updated_at": datetime.now(UTC).isoformat(),
            "updated_by_user_id": user["id"],
        }
    )
    log_audit_event(
        user_id=user["id"],
        organization_id=organization_id,
        location_id=location_id,
        action="Creacion",
        entity_type="Paciente",
        entity_label=display_name.strip(),
        detail=f"{patient_type.strip()} | {specialty.strip()} | {document_number.strip() or owner_name.strip() or 'sin identificacion'}",
    )
    suffix = build_scope_query(str(organization_id), str(location_id))
    return RedirectResponse(url=f"/clinica?patient_saved=1&{suffix}", status_code=303)

@router.post("/patients/{patient_id}/edit")
async def edit_patient(
    request: Request,
    patient_id: int,
    organization_id: int = Form(...),
    location_id: int = Form(...),
    display_name: str = Form(...),
    patient_type: str = Form(...),
    specialty: str = Form(...),
    owner_name: str = Form(""),
    phone: str = Form(""),
    document_number: str = Form(""),
    birth_date: str = Form(""),
    sex: str = Form(""),
    insurance_name: str = Form(""),
    species: str = Form(""),
    breed: str = Form(""),
    weight_kg: float = Form(0),
    vaccine_status: str = Form("No aplica"),
    color: str = Form(""),
    microchip: str = Form(""),
    tutor_email: str = Form(""),
    tutor_address: str = Form(""),
    emergency_contact_name: str = Form(""),
    emergency_contact_phone: str = Form(""),
    emergency_contact_relationship: str = Form(""),
    reproductive_status: str = Form(""),
    sterilized: int = Form(0),
    sterilization_date: str = Form(""),
    allergies: str = Form(""),
    preexisting_conditions: str = Form(""),
    medical_history: str = Form(""),
    deworming_status: str = Form(""),
    deworming_date: str = Form(""),
    next_deworming_due: str = Form(""),
    clinical_alert: str = Form(""),
    patient_status: str = Form("active"),
) -> RedirectResponse:
    user = user_with_permissions(request)

    if user is None:
        return redirect_to_login()

    if not user["permissions"]["manage_clinical"]:
        return redirect_to_module_with_error(
            "/clinica",
            "Tu rol no puede editar pacientes."
        )

    if not inventory_scope_allowed(user, organization_id, location_id):
        return redirect_to_module_with_error(
            "/clinica",
            "La organización o sede seleccionada no pertenece a tu alcance."
        )

    patient = get_patient(patient_id)

    if patient is None:
        return redirect_to_module_with_error(
            "/clinica",
            "La mascota no existe."
        )

    if (
        int(patient["organization_id"]) != organization_id
        or int(patient["location_id"]) != location_id
    ):
        return redirect_to_module_with_error(
            "/clinica",
            "La mascota no pertenece a la sede seleccionada.",
        )

    duplicate = find_patient_duplicate(
        organization_id=organization_id,
        location_id=location_id,
        display_name=display_name,
        owner_name=owner_name.strip() or patient.get("owner_name", ""),
        document_number=document_number.strip() or patient.get("document_number", ""),
        microchip=microchip.strip() or patient.get("microchip", ""),
        species=species,
        birth_date=birth_date,
        exclude_patient_id=patient_id,
    )

    if duplicate:
        return redirect_to_module_with_error(
            "/clinica",
            f"La información coincide con la mascota '{duplicate['display_name']}'."
        )

    update_patient(
        patient_id,
        {
            "display_name": display_name.strip(),
            "patient_type": patient.get("patient_type", patient_type).strip(),
            "specialty": patient.get("specialty", specialty).strip(),
            "owner_name": owner_name.strip(),
            "phone": phone.strip(),
            "document_number": document_number.strip() or patient.get("document_number", ""),
            "birth_date": birth_date,
            "sex": sex.strip(),
            "insurance_name": insurance_name.strip() or patient.get("insurance_name", ""),
            "species": species.strip(),
            "breed": breed.strip(),
            "weight_kg": weight_kg,
            "vaccine_status": vaccine_status.strip(),
            "color": color.strip() or patient.get("color", ""),
            "microchip": microchip.strip(),
            "tutor_email": tutor_email.strip() or patient.get("tutor_email", ""),
            "tutor_address": tutor_address.strip() or patient.get("tutor_address", ""),
            "emergency_contact_name": emergency_contact_name.strip() or patient.get("emergency_contact_name", ""),
            "emergency_contact_phone": emergency_contact_phone.strip() or patient.get("emergency_contact_phone", ""),
            "emergency_contact_relationship": emergency_contact_relationship.strip() or patient.get("emergency_contact_relationship", ""),
            "reproductive_status": reproductive_status.strip() or patient.get("reproductive_status", ""),
            "sterilized": int(patient.get("sterilized", False)),
            "sterilization_date": sterilization_date or patient.get("sterilization_date", ""),
            "allergies": allergies.strip() or patient.get("allergies", ""),
            "preexisting_conditions": preexisting_conditions.strip() or patient.get("preexisting_conditions", ""),
            "medical_history": medical_history.strip() or patient.get("medical_history", ""),
            "deworming_status": deworming_status.strip() or patient.get("deworming_status", ""),
            "deworming_date": deworming_date or patient.get("deworming_date", ""),
            "next_deworming_due": next_deworming_due or patient.get("next_deworming_due", ""),
            "clinical_alert": clinical_alert.strip() or patient.get("clinical_alert", ""),
            "patient_status": patient_status.strip() if patient_status != "active" else patient.get("patient_status", "active"),
            "updated_at": datetime.now(UTC).isoformat(),
            "updated_by_user_id": user["id"],
        },
    )

    log_audit_event(
        user_id=user["id"],
        organization_id=organization_id,
        location_id=location_id,
        action="Edicion",
        entity_type="Paciente",
        entity_label=display_name.strip(),
        detail=f"Paciente #{patient_id} actualizado",
    )

    suffix = build_scope_query(
        str(organization_id),
        str(location_id)
    )

    return RedirectResponse(
        url=f"/clinica?patient_updated=1&{suffix}",
        status_code=303,
    )

@router.post("/patients/{patient_id}/delete")
async def remove_patient(
    request: Request,
    patient_id: int,
    organization_id: int = Form(0),
    location_id: int = Form(0),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_clinical"]:
        return redirect_to_module_with_error("/clinica", "Tu rol no puede eliminar pacientes.")

    patient = get_patient(patient_id)
    if patient is None:
        return redirect_to_module_with_error("/clinica", "La mascota no existe.")
    if not inventory_scope_allowed(
        user,
        int(patient["organization_id"]),
        int(patient["location_id"]),
    ):
        return redirect_to_module_with_error(
            "/clinica",
            "Tu rol no puede eliminar mascotas de otra sede.",
        )

    delete_patient(patient_id)
    log_audit_event(
        user_id=user["id"],
        organization_id=patient["organization_id"],
        location_id=patient["location_id"],
        action="Eliminacion",
        entity_type="Paciente",
        entity_label=patient["display_name"],
        detail="Paciente y sus registros relacionados fueron eliminados",
    )
    suffix = build_scope_query(
        str(patient["organization_id"]),
        str(patient["location_id"]),
    )
    return RedirectResponse(url=f"/clinica?{suffix}" if suffix else "/clinica", status_code=303)


@router.post("/clinical-records")
async def create_new_record(
    request: Request,
    organization_id: int = Form(...),
    location_id: int = Form(...),
    patient_id: int = Form(...),
    encounter_date: str = Form(...),
    specialty: str = Form(...),
    reason: str = Form(...),
    note: str = Form(...),
    status: str = Form(...),
    professional: str = Form(...),
    diagnosis: str = Form(""),
    treatment_plan: str = Form(""),
    allergies: str = Form(""),
    vital_signs: str = Form(""),
    prescription: str = Form(""),
    discharge_notes: str = Form(""),
    service_performed: str = Form(""),
    follow_up_date: str = Form(""),
    next_vaccine_due: str = Form(""),
    dental_chart: str = Form(""),
    current_weight_kg: float = Form(0),
    payment_amount: float = Form(0),
    payment_method: str = Form("Sin definir"),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_clinical"]:
        return redirect_to_module_with_error("/clinica", "Tu rol no puede registrar atenciones.")
    if not inventory_scope_allowed(user, organization_id, location_id):
        return redirect_to_module_with_error(
            "/clinica",
            "La organización o sede seleccionada no pertenece a tu alcance.",
        )

    patient = get_patient(patient_id)
    if patient is None or (
        int(patient["organization_id"]) != organization_id
        or int(patient["location_id"]) != location_id
    ):
        return redirect_to_module_with_error(
            "/clinica",
            "La mascota no pertenece a la sede seleccionada.",
        )

    create_clinical_record(
        {
            "patient_id": patient_id,
            "organization_id": organization_id,
            "location_id": location_id,
            "encounter_date": encounter_date,
            "specialty": specialty.strip(),
            "reason": reason.strip(),
            "note": note.strip(),
            "status": status.strip(),
            "professional": professional.strip(),
            "diagnosis": diagnosis.strip(),
            "treatment_plan": treatment_plan.strip(),
            "allergies": allergies.strip(),
            "vital_signs": vital_signs.strip(),
            "prescription": prescription.strip(),
            "discharge_notes": discharge_notes.strip(),
            "service_performed": service_performed.strip(),
            "follow_up_date": follow_up_date,
            "next_vaccine_due": next_vaccine_due,
            "dental_chart": dental_chart.strip(),
            "current_weight_kg": current_weight_kg,
            "payment_amount": payment_amount,
            "payment_method": payment_method.strip(),
        }
    )
    log_audit_event(
        user_id=user["id"],
        organization_id=organization_id,
        location_id=location_id,
        action="Creacion",
        entity_type="Historia",
        entity_label=f"Paciente #{patient_id}",
        detail=f"{specialty.strip()} | {reason.strip()} | dx {diagnosis.strip() or 'sin dx'} | pago {payment_amount:.0f}",
    )
    suffix = build_scope_query(str(organization_id), str(location_id), encounter_date)
    return RedirectResponse(url=f"/clinica?record_saved=1&{suffix}", status_code=303)


@router.get("/clinica/reportes/atenciones/export")
async def export_clinical_records_report(
    request: Request,
    organization_id: str = Query(default=""),
    location_id: str = Query(default=""),
):
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["view_clinical"]:
        return redirect_to_module_with_error("/clinica", "Tu rol no puede exportar atenciones.")
    records = list_clinical_records(
        limit=500,
        organization_id=organization_id or request.session.get("preferred_organization_id", ""),
        location_id=location_id or request.session.get("preferred_location_id", ""),
    )
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Fecha",
            "Paciente",
            "Especialidad",
            "Servicio",
            "Diagnostico",
            "Profesional",
            "Estado",
            "Pago",
            "Medio",
            "Sede",
        ]
    )
    for item in records:
        writer.writerow(
            [
                item["encounter_date"],
                item["display_name"],
                item["specialty"],
                item["service_performed"],
                item["diagnosis"],
                item["professional"],
                item["status"],
                f"{float(item['payment_amount'] or 0):.0f}",
                item["payment_method"],
                item["site_name"],
            ]
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="velmorax-atenciones.csv"'},
    )


@router.post("/clinical-records/{record_id}/status")
async def update_record(
    request: Request,
    record_id: int,
    status: str = Form(...),
    organization_id: int = Form(0),
    location_id: int = Form(0),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_clinical"]:
        return redirect_to_module_with_error("/clinica", "Tu rol no puede actualizar atenciones.")

    update_clinical_record_status(record_id, status)
    log_audit_event(
        user_id=user["id"],
        organization_id=organization_id or None,
        location_id=location_id or None,
        action="Actualizacion",
        entity_type="Historia",
        entity_label=f"Registro #{record_id}",
        detail=f"Estado cambiado a {status.strip()}",
    )
    suffix = build_scope_query(str(organization_id or ""), str(location_id or ""))
    return RedirectResponse(url=f"/clinica?{suffix}" if suffix else "/clinica", status_code=303)


@router.post("/clinical-records/{record_id}/delete")
async def remove_record(
    request: Request,
    record_id: int,
    organization_id: int = Form(0),
    location_id: int = Form(0),
    patient_id: int = Form(0),
) -> RedirectResponse:
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_clinical"]:
        return redirect_to_module_with_error("/clinica", "Tu rol no puede eliminar atenciones.")

    record = get_clinical_record(record_id)
    if (
        record is None
        or not inventory_scope_allowed(user, organization_id, location_id)
        or int(record["organization_id"]) != organization_id
        or int(record["location_id"]) != location_id
        or (patient_id and int(record["patient_id"]) != patient_id)
    ):
        return redirect_to_module_with_error(
            "/clinica", "La atención no pertenece a la sede seleccionada."
        )

    delete_clinical_record(record_id)
    log_audit_event(
        user_id=user["id"],
        organization_id=organization_id or None,
        location_id=location_id or None,
        action="Eliminacion",
        entity_type="Historia",
        entity_label=f"Registro #{record_id}",
        detail="Registro clinico eliminado desde la interfaz",
    )
    suffix = build_scope_query(str(organization_id), str(location_id))
    return RedirectResponse(
        url=f"/pacientes/{record['patient_id']}/historial?{suffix}#historial-clinico",
        status_code=303,
    )


@router.post("/pacientes/{patient_id}/historial/delete")
async def remove_patient_history(
    request: Request,
    patient_id: int,
    organization_id: int = Form(0),
    location_id: int = Form(0),
) -> RedirectResponse:
    """Elimina el historial clínico, conservando la ficha de la mascota."""
    user = user_with_permissions(request)
    if user is None:
        return redirect_to_login()
    if not user["permissions"]["manage_clinical"]:
        return redirect_to_module_with_error("/clinica", "Tu rol no puede eliminar historiales.")

    patient = get_patient(patient_id)
    if (
        patient is None
        or not inventory_scope_allowed(user, organization_id, location_id)
        or int(patient["organization_id"]) != organization_id
        or int(patient["location_id"]) != location_id
    ):
        return redirect_to_module_with_error(
            "/clinica", "El historial no pertenece a la sede seleccionada."
        )

    delete_patient_history(patient_id)
    log_audit_event(
        user_id=user["id"],
        organization_id=organization_id,
        location_id=location_id,
        action="Eliminacion",
        entity_type="Historia",
        entity_label=f"Historial de {patient['display_name']}",
        detail="Historial clínico eliminado; ficha de paciente conservada",
    )
    suffix = build_scope_query(str(organization_id), str(location_id))
    return RedirectResponse(
        url=f"/pacientes/{patient_id}/historial?{suffix}#historial-clinico",
        status_code=303,
    )


def health_payload(check_database: bool = True) -> tuple[dict, int]:
    database_status = "ok"
    if check_database:
        try:
            with get_connection() as connection:
                connection.execute("SELECT 1").fetchone()
        except Exception:
            database_status = "unavailable"
    payload = {
        "status": "ok" if database_status == "ok" else "degraded",
        "service": "velmorax-web",
        "database": get_database_dialect(),
        "database_status": database_status,
        "version": settings.app_version,
        "session_idle_timeout_minutes": settings.session_idle_timeout_minutes,
    }
    return payload, 200 if database_status == "ok" else 503


@router.get("/health")
async def healthcheck() -> JSONResponse:
    payload, status_code = health_payload()
    return JSONResponse(payload, status_code=status_code, headers={"Cache-Control": "no-store"})


@router.get("/health/live")
async def liveness() -> JSONResponse:
    payload, _ = health_payload(check_database=False)
    payload["check"] = "liveness"
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@router.get("/health/ready")
async def readiness() -> JSONResponse:
    payload, status_code = health_payload()
    payload["check"] = "readiness"
    return JSONResponse(payload, status_code=status_code, headers={"Cache-Control": "no-store"})
