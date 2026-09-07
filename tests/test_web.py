import os
import json
import re
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path


TEST_DB = Path("data") / "velmorax-test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["SESSION_SECRET"] = "velmorax-test-secret"

from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_connection
from app.services.appointments import available_slots, create_appointment, list_appointments
from app.services.alerts import acknowledge_alert, list_alerts
from app.services.auth import effective_permissions, get_user_by_id, list_users
from app.services.inventory import create_inventory_movement
from app.services.commercial import assert_capacity, organization_subscription
from app.services.client_migration import migrate_client_bundle
from app.services.integrations import enqueue_integration_event, integration_outbox_summary, integration_readiness


class VelmoraxWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if TEST_DB.exists():
            TEST_DB.unlink()
        cls.client_manager = TestClient(app)
        cls.client = cls.client_manager.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_manager.__exit__(None, None, None)
        if TEST_DB.exists():
            TEST_DB.unlink()

    def test_login_page_renders_clean_credentials_form(self):
        self.client.post("/logout")
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Correo", response.text)
        self.assertIn("Clave", response.text)
        self.assertNotIn("Sede / ubicacion", response.text)

    def test_legal_documents_and_versioned_acceptance_are_available(self):
        for path, heading in (
            ("/privacidad", "Aviso de privacidad"),
            ("/tratamiento-de-datos", "Política de tratamiento de datos"),
            ("/terminos", "Términos de uso"),
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(heading, response.text)

        self.client.post("/logout")
        self.client.post(
            "/login",
            data={
                "intent": "veterinaria",
                "email": "admin@velmorax.local",
                "password": "velmorax123",
                "legal_acceptance": "1",
            },
        )
        self.client.post("/login/push-approval", data={"approve": "1"})
        with get_connection() as connection:
            acceptance = connection.execute(
                "SELECT privacy_version, terms_version, evidence_hash FROM legal_acceptances ORDER BY id DESC"
            ).fetchone()
        self.assertIsNotNone(acceptance)
        self.assertEqual(len(acceptance["evidence_hash"]), 64)

    def test_commercial_plans_are_public_and_capacity_is_visible_and_enforced(self):
        public = self.client.get("/planes")
        self.assertEqual(public.status_code, 200)
        self.assertIn(">Esencial</h2>", public.text)
        self.assertIn("Hospital y red", public.text)
        self.assertIn("nunca bloquean una urgencia", public.text)

        subscription = organization_subscription(1)
        self.assertEqual(subscription["code"], "essential")
        self.assertIn("users", subscription["usage"])

        with get_connection() as connection:
            original = connection.execute("SELECT plan_code FROM organizations WHERE id = 1").fetchone()["plan_code"]
            connection.execute("UPDATE organizations SET plan_code = 'essential' WHERE id = 1")
            for index in range(10):
                connection.execute(
                    """INSERT OR IGNORE INTO users
                       (full_name,email,password_hash,role,is_active,organization_id,location_id,specialty)
                       VALUES (?,?,?,?,1,1,2,'Veterinaria')""",
                    (f"Capacidad QA {index}", f"capacidad-{index}@qa.local", "x", "clinical"),
                )
            connection.commit()
        try:
            with self.assertRaisesRegex(ValueError, "capacidad de usuarios activos"):
                assert_capacity(1, "users")
        finally:
            with get_connection() as connection:
                connection.execute("DELETE FROM users WHERE email LIKE 'capacidad-%@qa.local'")
                connection.execute("UPDATE organizations SET plan_code = ? WHERE id = 1", (original,))
                connection.commit()

    def test_client_migration_validates_imports_and_is_idempotent(self):
        source = "qa-migration"
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            (bundle / "manifest.json").write_text(json.dumps({"organization_id": 1, "location_id": 2, "source_system": source}))
            (bundle / "patients.csv").write_text("external_id,name,owner_name,species,weight_kg\nP-1,Nala,Tutor QA,Felino,4.2\n")
            (bundle / "inventory.csv").write_text("external_id,name,lot,quantity,expiry_date\nI-1,Vacuna QA,L-QA,5,2027-01-01\n")
            (bundle / "appointments.csv").write_text("external_id,date,time,patient_name,service\nA-1,2026-10-01,10:30,Nala,Control QA\n")
            preview = migrate_client_bundle(bundle)
            self.assertTrue(preview["valid"])
            self.assertEqual(preview["imported"], {})
            applied = migrate_client_bundle(bundle, apply=True)
            self.assertEqual(applied["imported"], {"patients": 1, "inventory": 1, "appointments": 1})
            repeated = migrate_client_bundle(bundle, apply=True)
            self.assertEqual(repeated["imported"], {"patients": 0, "inventory": 0, "appointments": 0})
        with get_connection() as connection:
            connection.execute("DELETE FROM appointments WHERE source_system = ?", (source,))
            connection.execute("DELETE FROM inventory_items WHERE source_system = ?", (source,))
            connection.execute("DELETE FROM patients WHERE source_system = ?", (source,))
            connection.commit()

    def test_integration_outbox_is_idempotent_and_does_not_store_secrets(self):
        key = "qa:integration:1"
        created = enqueue_integration_event(organization_id=1, location_id=2, event_type="appointment.created", event_key=key, payload={"appointment_id": 9, "token": "never-store", "patient_name": "Nala"})
        repeated = enqueue_integration_event(organization_id=1, location_id=2, event_type="appointment.created", event_key=key, payload={"appointment_id": 9})
        self.assertTrue(created)
        self.assertFalse(repeated)
        self.assertEqual(len(integration_readiness()), 5)
        self.assertGreaterEqual(integration_outbox_summary(1)["pending"], 1)
        with get_connection() as connection:
            payload = connection.execute("SELECT payload FROM integration_outbox WHERE event_key=?", (key,)).fetchone()["payload"]
            self.assertNotIn("never-store", payload)
            connection.execute("DELETE FROM integration_outbox WHERE event_key=?", (key,))
            connection.commit()

    def test_demo_user_can_login_and_open_clinical_module(self):
        response = self.client.post(
            "/login",
            data={
                "intent": "odontologia",
                "email": "admin@velmorax.local",
                "password": "velmorax123",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login/push-approval")

        response = self.client.post(
            "/login/push-approval",
            data={"approve": "1"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("/clinica", response.headers["location"])

        clinical = self.client.get(response.headers["location"])
        self.assertEqual(clinical.status_code, 200)
        self.assertIn("Pacientes", clinical.text)

    def test_password_reset_flow_generates_link_and_allows_new_login(self):
        with TestClient(app) as client:
            response = client.post("/password-reset", data={"email": "clinica@velmorax.local"})
            self.assertEqual(response.status_code, 200)
            match = re.search(r"/password-reset/confirm\?token=([^\s<]+)", response.text)
            self.assertIsNotNone(match)
            token = match.group(1)

            confirm = client.post(
                "/password-reset/confirm",
                data={
                    "token": token,
                    "password": "NuevaClave123",
                    "password_confirm": "NuevaClave123",
                },
                follow_redirects=False,
            )
            self.assertEqual(confirm.status_code, 303)
            self.assertIn("/login", confirm.headers["location"])

            login = client.post(
                "/login",
                data={
                    "intent": "odontologia",
                    "email": "clinica@velmorax.local",
                    "password": "NuevaClave123",
                },
                follow_redirects=False,
            )
            self.assertEqual(login.status_code, 303)

    def test_inventory_export_requires_authenticated_access(self):
        with TestClient(app) as anonymous:
            response = anonymous.get("/inventario/export", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/login", response.headers["location"])

    def test_enterprise_controls_permissions_handoff_escalation_and_concurrent_booking(self):
        self.client.post("/logout")
        self.client.post("/login", data={"intent": "veterinaria", "email": "admin@velmorax.local", "password": "velmorax123"})
        self.client.post("/login/push-approval", data={"approve": "1"})
        target = next(item for item in list_users() if item["email"] == "clinica@velmorax.local")
        customized = self.client.post(
            f"/admin/users/{target['id']}/permissions",
            data={"permission_mode": "custom", "allowed_permissions": ["view_inventory", "consume_inventory"],
                  "organization_id": target["organization_id"], "location_id": target["location_id"],
                  "full_name": target["full_name"]}, follow_redirects=False,
        )
        self.assertIn("user_updated=1", customized.headers["location"])
        permissions = effective_permissions(get_user_by_id(target["id"]))
        self.assertTrue(permissions["consume_inventory"])
        self.assertFalse(permissions["manage_inventory"])
        self.assertFalse(permissions["manage_agenda"])
        self.client.post(
            f"/admin/users/{target['id']}/permissions",
            data={"permission_mode": "role", "organization_id": target["organization_id"],
                  "location_id": target["location_id"], "full_name": target["full_name"]},
        )

        handoff = self.client.post("/dashboard/handoff", data={
            "organization_id": 1, "location_id": 2, "shift_label": "Urgencias",
            "summary": "Turno estable; paciente en observación", "pending_actions": "Revisar temperatura a las 02:00",
        }, follow_redirects=False)
        self.assertEqual(handoff.status_code, 303)
        dashboard = self.client.get("/?organization_id=1&location_id=2")
        self.assertIn("Turno estable; paciente en observación", dashboard.text)

        due = (datetime.now() - timedelta(hours=2)).isoformat(timespec="minutes")
        with get_connection() as connection:
            connection.execute(
                """INSERT INTO alerts (organization_id,location_id,created_by,title,message,priority,status,due_at,recurrence,escalation_minutes,source)
                   VALUES (1,2,?,'QA escalamiento','Control pendiente','important','active',?,'once',30,'manual')""",
                (target["id"], due),
            )
            alert_id = connection.execute("SELECT id FROM alerts WHERE title='QA escalamiento' ORDER BY id DESC LIMIT 1").fetchone()["id"]
            connection.commit()

        escalated = next(item for item in list_alerts("1", "2") if item["id"] == alert_id)
        self.assertTrue(escalated["escalated"])
        self.assertEqual(escalated["priority"], "urgent")

        future = date.today() + timedelta(days=2)
        while future.weekday() == 6:
            future += timedelta(days=1)
        provider = target
        with get_connection() as connection:
            patient = connection.execute("SELECT id FROM patients WHERE organization_id=1 AND location_id=2 LIMIT 1").fetchone()
        payload = {
            "organization_id": 1, "location_id": 2, "appointment_date": future.isoformat(),
            "appointment_time": "10:00", "patient_name": "Paciente concurrencia QA", "service": "Control",
            "channel": "Presencial", "status": "Confirmada", "specialty": "Veterinaria", "note": "",
            "duration_minutes": 30, "veterinarian": provider["full_name"], "patient_id": patient["id"],
            "veterinarian_user_id": provider["id"], "cancellation_reason": "", "priority": "Normal",
        }
        def reserve_once(_: int) -> str:
            try:
                create_appointment(payload.copy())
                return "created"
            except ValueError:
                return "blocked"
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(reserve_once, range(2)))
        self.assertEqual(outcomes.count("created"), 1)
        self.assertEqual(outcomes.count("blocked"), 1)
        with get_connection() as connection:
            connection.execute("DELETE FROM appointments WHERE patient_name='Paciente concurrencia QA'")
            connection.execute("DELETE FROM alerts WHERE id=?", (alert_id,))
            connection.execute("DELETE FROM shift_handoffs WHERE summary='Turno estable; paciente en observación'")
            connection.commit()

    def test_automatic_alert_notifies_again_when_problem_returns(self):
        with get_connection() as connection:
            connection.execute(
                """INSERT INTO inventory_items
                   (organization_id,location_id,name,category,brand,regulatory_agency,regulatory_code,lot,quantity,min_stock,location,expiry_date)
                   VALUES (1,2,'Alerta recurrente QA','Veterinaria','QA','ICA','ICA-ACK-QA','ACK-QA',0,1,'Bodega',?)""",
                ((date.today() + timedelta(days=365)).isoformat(),),
            )
            item_id = connection.execute("SELECT id FROM inventory_items WHERE lot='ACK-QA'").fetchone()["id"]
            connection.commit()
        key = f"inventory-stock-{item_id}"
        try:
            self.assertTrue(acknowledge_alert(key, 1, 2, 1))
            acknowledged = next(item for item in list_alerts("1", "2") if item["key"] == key)
            self.assertTrue(acknowledged["acknowledged"])
            with get_connection() as connection:
                connection.execute("UPDATE inventory_items SET quantity=5 WHERE id=?", (item_id,))
                connection.commit()
            list_alerts("1", "2")
            with get_connection() as connection:
                stale = connection.execute("SELECT id FROM alert_acknowledgements WHERE alert_key=?", (key,)).fetchone()
                connection.execute("UPDATE inventory_items SET quantity=0 WHERE id=?", (item_id,))
                connection.commit()
            self.assertIsNone(stale)
            returned = next(item for item in list_alerts("1", "2") if item["key"] == key)
            self.assertFalse(returned["acknowledged"])
        finally:
            with get_connection() as connection:
                connection.execute("DELETE FROM alert_acknowledgements WHERE alert_key=?", (key,))
                connection.execute("DELETE FROM inventory_items WHERE id=?", (item_id,))
                connection.commit()

    def test_inventory_concurrent_outputs_never_create_negative_stock(self):
        with get_connection() as connection:
            connection.execute(
                """INSERT INTO inventory_items (organization_id,location_id,name,category,brand,regulatory_agency,regulatory_code,lot,quantity,min_stock,location,expiry_date)
                   VALUES (1, 2, 'Carga concurrente QA', 'Veterinaria', 'QA', 'ICA', 'ICA-LOAD', 'LOAD-QA', 20, 1, 'Bodega', ?)""",
                ((date.today() + timedelta(days=365)).isoformat(),),
            )
            item_id = connection.execute("SELECT id FROM inventory_items WHERE lot='LOAD-QA'").fetchone()["id"]
            connection.commit()
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(
                lambda _: create_inventory_movement(item_id, "out", 1, "Prueba concurrente", reason_type="Merma"),
                range(40),
            ))
        with get_connection() as connection:
            final_quantity = connection.execute("SELECT quantity FROM inventory_items WHERE id=?", (item_id,)).fetchone()["quantity"]
            movement_count = connection.execute("SELECT COUNT(*) AS total FROM inventory_movements WHERE item_id=?", (item_id,)).fetchone()["total"]
        self.assertEqual(sum(1 for ok, _ in results if ok), 20)
        self.assertEqual(final_quantity, 0)
        self.assertEqual(movement_count, 20)

    def test_inventory_operational_health_and_backup_are_verifiable(self):
        self.client.post("/logout")
        self.client.post("/login", data={"intent": "veterinaria", "email": "admin@velmorax.local", "password": "velmorax123"})
        self.client.post("/login/push-approval", data={"approve": "1"})
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["database_status"], "ok")
        backup = self.client.get("/admin/backup")
        self.assertEqual(backup.status_code, 200)
        self.assertTrue(backup.content.startswith(b"SQLite format 3"))
        with tempfile.NamedTemporaryFile(suffix=".db") as restored:
            restored.write(backup.content)
            restored.flush()
            with sqlite3.connect(restored.name) as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                inventory_tables = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('inventory_items','inventory_movements')"
                ).fetchone()[0]
            self.assertEqual(integrity, "ok")
            self.assertEqual(inventory_tables, 2)

    def test_veterinary_dashboard_is_visual_and_uses_veterinary_scope(self):
        self.client.post("/logout")
        login = self.client.post(
            "/login",
            data={
                "intent": "veterinaria",
                "email": "admin@velmorax.local",
                "password": "velmorax123",
            },
            follow_redirects=False,
        )
        self.assertEqual(login.headers["location"], "/login/push-approval")

        approval = self.client.post(
            "/login/push-approval",
            data={"approve": "1"},
            follow_redirects=False,
        )
        self.assertIn("location_id=2", approval.headers["location"])

        dashboard = self.client.get("/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("data-veterinary-dashboard", dashboard.text)
        self.assertIn("Sede Mascotas Centro", dashboard.text)
        self.assertIn("Agenda inmediata", dashboard.text)
        self.assertIn("Pulso operativo", dashboard.text)
        self.assertIn("Próximas atenciones", dashboard.text)
        self.assertNotIn("Carga del equipo", dashboard.text)
        self.assertIn("Con retraso", dashboard.text)
        self.assertIn("Equipo activo", dashboard.text)
        self.assertNotIn("Alertas prioritarias", dashboard.text)
        self.assertNotIn(">Nueva cita</a>", dashboard.text)
        self.assertNotIn("vet-board-shortcuts", dashboard.text)
        self.assertIn("data-dashboard-updated", dashboard.text)
        self.assertNotIn("Pacientes recientes", dashboard.text)
        self.assertNotIn("Referencias usadas para mejorar el flujo", dashboard.text)
        self.assertNotIn("Operacion en red", dashboard.text)

        for path in ("/", "/agenda", "/inventario", "/clinica", "/admin"):
            page = self.client.get(path)
            self.assertEqual(page.status_code, 200)
            self.assertIn("class=\"vet-wordmark\">Velmorax", page.text)
            self.assertNotIn("class=\"site-header\"", page.text)
            self.assertNotIn("Sede Norte Dental", page.text)

    def test_veterinary_dashboard_escalates_delayed_emergency(self):
        self.client.post("/logout")
        self.client.post("/login", data={"intent": "veterinaria", "email": "admin@velmorax.local", "password": "velmorax123"})
        self.client.post("/login/push-approval", data={"approve": "1"})
        with get_connection() as connection:
            patient = connection.execute("SELECT id, display_name FROM patients WHERE location_id=2 LIMIT 1").fetchone()
            provider = connection.execute("SELECT id, full_name FROM users WHERE role='admin' LIMIT 1").fetchone()
            delayed_time = (datetime.now() - timedelta(minutes=30)).strftime("%H:%M")
            connection.execute(
                """INSERT INTO appointments (
                    organization_id, location_id, appointment_date, appointment_time,
                    patient_name, service, channel, status, specialty, note,
                    duration_minutes, veterinarian, patient_id, veterinarian_user_id
                ) VALUES (1,2,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    date.today().isoformat(), delayed_time, patient["display_name"], "Urgencia veterinaria",
                    "Presencial", "En espera", "Veterinaria", "Paciente crítico",
                    30, provider["full_name"], patient["id"], provider["id"],
                ),
            )
            appointment_id = connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            connection.commit()
        try:
            dashboard = self.client.get("/?organization_id=1&location_id=2")
            self.assertEqual(dashboard.status_code, 200)
            self.assertIn("Atención inmediata", dashboard.text)
            self.assertIn("Urgencia veterinaria", dashboard.text)
            self.assertRegex(dashboard.text, r"<dt>Urgencias</dt><dd>1</dd>")
            self.assertRegex(dashboard.text, r"<dt>Con retraso</dt><dd>1</dd>")
            self.assertIn("Atención inmediata", dashboard.text)
            self.assertIn("vet-operations-critical", dashboard.text)
            self.assertIn("vet-board-queue-urgent", dashboard.text)
            self.assertIn("Retrasada", dashboard.text)
        finally:
            with get_connection() as connection:
                connection.execute("DELETE FROM appointments WHERE id=?", (appointment_id,))
                connection.commit()

    def test_veterinary_alerts_support_manual_lifecycle_and_scope_security(self):
        self.client.post("/logout")
        self.client.post("/login", data={"intent": "veterinaria", "email": "admin@velmorax.local", "password": "velmorax123"})
        self.client.post("/login/push-approval", data={"approve": "1"})
        title = "Revisar autoclave · PRUEBA ALERTAS"
        create = self.client.post(
            "/alerts",
            data={
                "organization_id": 1,
                "location_id": 2,
                "title": title,
                "message": "Validar ciclo y registrar resultado",
                "due_at": (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M"),
                "priority": "important",
                "recurrence": "once",
                "assigned_user_id": 0,
            },
            follow_redirects=False,
        )
        self.assertEqual(create.status_code, 303)
        with get_connection() as connection:
            alert = connection.execute("SELECT id FROM alerts WHERE title = ? ORDER BY id DESC LIMIT 1", (title,)).fetchone()
        self.assertIsNotNone(alert)
        alert_id = alert["id"]
        try:
            page = self.client.get("/alertas?organization_id=1&location_id=2")
            self.assertIn(title, page.text)
            self.assertIn("Marcar resuelta", page.text)
            self.assertIn("Confirmar lectura", page.text)
            self.assertIn("Las automáticas se cierran al corregir el lote", page.text)
            self.assertNotRegex(page.text, r'<details class="vet-inventory-drawer"\s+open>')

            edited = self.client.post(
                f"/alerts/{alert_id}/edit",
                data={"organization_id": 1, "location_id": 2, "title": title,
                      "message": "Validación editada y trazable",
                      "due_at": (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M"),
                      "priority": "important", "recurrence": "once", "escalation_minutes": 60,
                      "assigned_user_id": 1}, follow_redirects=False,
            )
            self.assertIn("updated=1", edited.headers["location"])
            with get_connection() as connection:
                edited_row = connection.execute("SELECT message, escalation_minutes FROM alerts WHERE id=?", (alert_id,)).fetchone()
            self.assertEqual(edited_row["message"], "Validación editada y trazable")
            self.assertEqual(edited_row["escalation_minutes"], 60)

            acknowledged = self.client.post(
                "/alerts/acknowledge",
                data={"alert_key": f"manual-{alert_id}", "organization_id": 1, "location_id": 2},
                follow_redirects=False,
            )
            self.assertIn("Lectura%20confirmada", acknowledged.headers["location"])
            read_page = self.client.get("/alertas?organization_id=1&location_id=2")
            self.assertIn("Leída por Administrador Velmorax", read_page.text)
            with get_connection() as connection:
                ack = connection.execute("SELECT user_id FROM alert_acknowledgements WHERE alert_key=?", (f"manual-{alert_id}",)).fetchone()
            self.assertIsNotNone(ack)

            blocked = self.client.post(
                f"/alerts/{alert_id}/resolve",
                data={"organization_id": 1, "location_id": 1},
                follow_redirects=False,
            )
            self.assertEqual(blocked.status_code, 303)
            with get_connection() as connection:
                status = connection.execute("SELECT status FROM alerts WHERE id = ?", (alert_id,)).fetchone()["status"]
            self.assertEqual(status, "active")

            snoozed = self.client.post(
                f"/alerts/{alert_id}/snooze",
                data={"organization_id": 1, "location_id": 2, "hours": 4},
                follow_redirects=False,
            )
            self.assertIn("pospuesta%204%20horas", snoozed.headers["location"])
            scheduled = self.client.get("/alertas?organization_id=1&location_id=2")
            self.assertIn("Programadas", scheduled.text)
            self.assertIn("Pospuesta", scheduled.text)

            resolved = self.client.post(
                f"/alerts/{alert_id}/resolve",
                data={"organization_id": 1, "location_id": 2},
                follow_redirects=False,
            )
            self.assertIn("resuelta", resolved.headers["location"])
            with get_connection() as connection:
                status = connection.execute("SELECT status FROM alerts WHERE id = ?", (alert_id,)).fetchone()["status"]
            self.assertEqual(status, "resolved")
            history = self.client.get("/alertas?organization_id=1&location_id=2")
            self.assertIn("Historial", history.text)
            self.assertIn("Resuelta", history.text)
        finally:
            with get_connection() as connection:
                connection.execute("DELETE FROM alert_acknowledgements WHERE alert_key = ?", (f"manual-{alert_id}",))
                connection.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
                connection.commit()

    def test_veterinary_agenda_rejects_overlaps_and_tracks_cancellation(self):
        self.client.post("/logout")
        self.client.post("/login", data={"intent": "veterinaria", "email": "admin@velmorax.local", "password": "velmorax123"})
        self.client.post("/login/push-approval", data={"approve": "1"})
        with get_connection() as connection:
            patient = connection.execute("SELECT id FROM patients WHERE location_id = 2 LIMIT 1").fetchone()
            provider = connection.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
        candidate = date.today() + timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        appointment_day = candidate.isoformat()
        payload = {
            "organization_id": 1, "location_id": 2, "appointment_date": appointment_day,
            "appointment_time": "09:00", "patient_id": patient["id"], "service": "Control",
            "channel": "Presencial", "status": "Confirmada", "specialty": "Veterinaria",
            "note": "Control programado", "duration_minutes": 30,
            "veterinarian_user_id": provider["id"],
        }
        created = self.client.post("/appointments", data=payload, follow_redirects=False)
        self.assertIn("appointment_saved=1", created.headers["location"])
        agenda = self.client.get(f"/agenda?organization_id=1&location_id=2&day={appointment_day}")
        self.assertIn("data-edit-appointment", agenda.text)
        self.assertIn("data-cancel-appointment-action", agenda.text)
        self.assertIn("data-delete-appointment-action", agenda.text)
        self.assertNotIn("Más acciones", agenda.text)
        appointments = list_appointments(appointment_day, organization_id="1", location_id="2")
        professional = next(item for item in list_users() if item["id"] == provider["id"])
        open_slots = available_slots(appointment_day, professional, appointments, duration=30)
        self.assertNotIn("09:00", open_slots)
        self.assertNotIn("08:30", available_slots(appointment_day, professional, appointments, duration=60))
        conflict = self.client.post("/appointments", data={**payload, "appointment_time": "09:15"}, follow_redirects=False)
        self.assertIn("agenda_error=", conflict.headers["location"])
        with get_connection() as connection:
            appointment = connection.execute("SELECT id FROM appointments WHERE patient_id = ? ORDER BY id DESC LIMIT 1", (patient["id"],)).fetchone()
        missing_reason = self.client.post(f"/appointments/{appointment['id']}/status", data={"status": "Cancelada", "day": appointment_day, "organization_id": 1, "location_id": 2}, follow_redirects=False)
        self.assertIn("permission_error=", missing_reason.headers["location"])
        self.client.post(f"/appointments/{appointment['id']}/status", data={"status": "Cancelada", "cancellation_reason": "Tutor no puede asistir", "day": appointment_day, "organization_id": 1, "location_id": 2})
        with get_connection() as connection:
            cancelled = connection.execute("SELECT status, cancellation_reason FROM appointments WHERE id = ?", (appointment["id"],)).fetchone()
        self.assertEqual(cancelled["status"], "Cancelada")
        self.assertEqual(cancelled["cancellation_reason"], "Tutor no puede asistir")

    def test_veterinary_agenda_supports_emergency_intake_and_scope_security(self):
        self.client.post("/logout")
        self.client.post("/login", data={"intent": "veterinaria", "email": "admin@velmorax.local", "password": "velmorax123"})
        self.client.post("/login/push-approval", data={"approve": "1"})
        with get_connection() as connection:
            patient = connection.execute("SELECT id FROM patients WHERE location_id=2 LIMIT 1").fetchone()
            provider = connection.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
        emergency_day = date.today()
        while emergency_day.weekday() != 6:
            emergency_day += timedelta(days=1)
        base = {
            "organization_id": 1, "location_id": 2, "appointment_date": emergency_day.isoformat(),
            "appointment_time": "02:15", "patient_id": patient["id"], "service": "Urgencia nocturna QA",
            "channel": "Presencial", "status": "En espera", "specialty": "Veterinaria",
            "note": "Ingreso inmediato fuera de horario", "duration_minutes": 30,
            "veterinarian_user_id": provider["id"],
        }
        regular = self.client.post("/appointments", data={**base, "priority": "Normal"}, follow_redirects=False)
        self.assertIn("agenda_error=", regular.headers["location"])
        emergency = self.client.post("/appointments", data={**base, "priority": "Urgente", "triage_level": "Rojo", "triage_note": "Compromiso respiratorio"}, follow_redirects=False)
        self.assertIn("appointment_saved=1", emergency.headers["location"])
        with get_connection() as connection:
            created = connection.execute("SELECT id, priority, triage_level, triage_note, arrival_at FROM appointments WHERE service='Urgencia nocturna QA' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(created["priority"], "Urgente")
        self.assertEqual(created["triage_level"], "Rojo")
        self.assertEqual(created["triage_note"], "Compromiso respiratorio")
        self.assertTrue(created["arrival_at"].endswith("T02:15"))
        page = self.client.get(f"/agenda?organization_id=1&location_id=2&day={emergency_day.isoformat()}")
        self.assertIn("Urgencias: 1", page.text)
        self.assertIn("vet-priority-urgent", page.text)
        self.assertIn("Triaje Rojo", page.text)
        dashboard = self.client.get(f"/?organization_id=1&location_id=2&day={emergency_day.isoformat()}")
        self.assertIn("Triaje Rojo", dashboard.text)
        crossed = self.client.post(
            f"/appointments/{created['id']}/status",
            data={"status": "Atendida", "day": emergency_day.isoformat(), "organization_id": 1, "location_id": 1},
            follow_redirects=False,
        )
        self.assertIn("permission_error=", crossed.headers["location"])
        with get_connection() as connection:
            unchanged = connection.execute("SELECT status FROM appointments WHERE id=?", (created["id"],)).fetchone()
            connection.execute("DELETE FROM appointments WHERE id=?", (created["id"],))
            connection.commit()
        self.assertEqual(unchanged["status"], "En espera")

    def test_veterinary_inventory_complete_traceability_flow(self):
        self.client.post("/logout")
        self.client.post("/login", data={"intent": "veterinaria", "email": "admin@velmorax.local", "password": "velmorax123"})
        self.client.post("/login/push-approval", data={"approve": "1"})
        single_site_page = self.client.get("/inventario?organization_id=1&location_id=2")
        self.assertNotIn("Trasladar", single_site_page.text)
        self.assertNotIn("Vista de red", single_site_page.text)
        self.assertIn("Abastecimiento", single_site_page.text)
        today = date.today().isoformat()
        expiry = (date.today() + timedelta(days=365)).isoformat()
        lot = "QA-VET-FINAL-001"
        payload = {
            "organization_id": 1, "location_id": 2, "name": "Vacuna QA trazable",
            "barcode": "QA770001", "category": "Veterinaria", "brand": "Velmorax QA",
            "regulatory_agency": "ICA", "regulatory_code": "ICA-QA-001",
            "supplier": "Proveedor QA", "lot": lot, "quantity": 10, "min_stock": 3,
            "unit_cost": 12000, "sale_price": 22000, "storage_condition": "Refrigerado 2–8 °C",
            "requires_cold_chain": 1, "location": "Nevera QA", "expiry_date": expiry,
            "product_id": 0, "item_type": "Vacuna", "unit_measure": "dosis",
            "manufacturer": "Laboratorio QA", "received_date": today,
            "document_number": "REM-QA-001", "presentation": "Frasco 10 dosis",
            "concentration": "1 ml", "serial_number": "", "reception_temperature_c": 4.2,
            "reception_note": "Empaque íntegro",
        }
        created = self.client.post("/inventory", data=payload, follow_redirects=False)
        self.assertIn("saved=1", created.headers["location"])
        with get_connection() as connection:
            item = connection.execute("SELECT * FROM inventory_items WHERE lot = ?", (lot,)).fetchone()
            patient = connection.execute("SELECT id FROM patients WHERE location_id=2 LIMIT 1").fetchone()
            self.assertIsNotNone(item)
            item_id = item["id"]
            receipt = connection.execute("SELECT * FROM inventory_movements WHERE item_id=? AND reason_type='Recepción'", (item_id,)).fetchone()
            cold = connection.execute("SELECT * FROM cold_chain_logs WHERE item_id=?", (item_id,)).fetchone()
        self.assertEqual(receipt["stock_before"], 0)
        self.assertEqual(receipt["stock_after"], 10)
        self.assertEqual(cold["has_incident"], 0)

        duplicate = self.client.post("/inventory", data=payload, follow_redirects=False)
        self.assertIn("permission_error=", duplicate.headers["location"])

        edit_payload = {
            "organization_id": 1, "location_id": 2, "name": payload["name"], "brand": payload["brand"],
            "supplier": payload["supplier"], "barcode": payload["barcode"], "regulatory_code": payload["regulatory_code"],
            "lot": lot, "expiry_date": expiry, "min_stock": 4, "unit_cost": 12500, "sale_price": 22500,
            "location": "Nevera B", "storage_condition": payload["storage_condition"], "requires_cold_chain": 1,
            "item_type": "Vacuna", "unit_measure": "dosis",
        }
        edited = self.client.post(f"/inventory/{item_id}/edit", data=edit_payload, follow_redirects=False)
        self.assertIn("saved=1", edited.headers["location"])
        counted = self.client.post(f"/inventory/{item_id}/count", data={"counted_quantity": 8, "note": "Conteo QA", "organization_id": 1, "location_id": 2}, follow_redirects=False)
        self.assertIn("moved=1", counted.headers["location"])
        self.assertIn("notice=Conteo%20guardado", counted.headers["location"])
        unlinked = self.client.post("/inventory/movements", data={"item_id": item_id, "movement_type": "out", "quantity": 1, "note": "Sin paciente", "reason_type": "Consumo clínico", "organization_id": 1, "location_id": 2}, follow_redirects=False)
        self.assertIn("movement_error=", unlinked.headers["location"])
        quarantined = self.client.post(f"/inventory/{item_id}/quarantine", data={"enabled": 1, "reason": "Verificación sanitaria QA", "organization_id": 1, "location_id": 2}, follow_redirects=False)
        self.assertIn("saved=1", quarantined.headers["location"])
        blocked = self.client.post("/inventory/movements", data={"item_id": item_id, "movement_type": "out", "quantity": 1, "note": "Intento bloqueado", "reason_type": "Consumo clínico", "organization_id": 1, "location_id": 2, "patient_id": patient["id"]}, follow_redirects=False)
        self.assertIn("movement_error=", blocked.headers["location"])
        released = self.client.post(f"/inventory/{item_id}/quarantine", data={"enabled": 0, "reason": "Liberación QA", "organization_id": 1, "location_id": 2}, follow_redirects=False)
        self.assertIn("saved=1", released.headers["location"])
        moved = self.client.post("/inventory/movements", data={"item_id": item_id, "movement_type": "out", "quantity": 2, "note": "Aplicación QA", "reason_type": "Consumo clínico", "organization_id": 1, "location_id": 2, "patient_id": patient["id"], "priority": "Urgente", "external_reference": "CASO-QA-001"}, follow_redirects=False)
        self.assertIn("moved=1", moved.headers["location"])
        temperature = self.client.post(f"/inventory/{item_id}/cold-chain", data={"temperature_c": 9.5, "note": "Incidente QA", "organization_id": 1, "location_id": 2}, follow_redirects=False)
        self.assertIn("moved=1", temperature.headers["location"])
        self.assertIn("notice=Temperatura%20registrada", temperature.headers["location"])
        retired = self.client.post(f"/inventory/{item_id}/retire", data={"quantity": 6, "reason": "Daño", "organization_id": 1, "location_id": 2}, follow_redirects=False)
        self.assertIn("moved=1", retired.headers["location"])
        self.assertIn("notice=Retiro%20registrado", retired.headers["location"])
        with get_connection() as connection:
            final = connection.execute("SELECT * FROM inventory_items WHERE id=?", (item_id,)).fetchone()
            movements = connection.execute("SELECT COUNT(*) AS total FROM inventory_movements WHERE item_id=?", (item_id,)).fetchone()["total"]
            cold_logs = connection.execute("SELECT COUNT(*) AS total FROM cold_chain_logs WHERE item_id=?", (item_id,)).fetchone()["total"]
            linked = connection.execute("SELECT patient_id, priority, external_reference FROM inventory_movements WHERE item_id=? AND reason_type='Consumo clínico'", (item_id,)).fetchone()
        self.assertEqual(final["quantity"], 0)
        self.assertEqual(final["lot_status"], "retired")
        self.assertEqual(final["retirement_reason"], "Daño")
        self.assertEqual(final["cold_chain_incident"], 1)
        self.assertEqual(movements, 4)
        self.assertEqual(cold_logs, 2)
        self.assertEqual(linked["patient_id"], patient["id"])
        self.assertEqual(linked["priority"], "Urgente")
        self.assertEqual(linked["external_reference"], "CASO-QA-001")
        retired_page = self.client.get("/inventario?organization_id=1&location_id=2&status=retired")
        self.assertIn(lot, retired_page.text)
        self.assertNotIn('id="inventory-item-2"', retired_page.text)
        self.assertNotIn("Guardar edición", retired_page.text)
        exported = self.client.get("/inventario/export?organization_id=1&location_id=2&status=retired")
        self.assertEqual(exported.status_code, 200)
        self.assertIn(lot, exported.text)
        self.assertNotIn("Vacuna triple felina", exported.text)

    def test_inventory_management_is_denied_without_permission(self):
        self.client.post("/logout")
        self.client.post("/login", data={"intent": "veterinaria", "email": "clinica@velmorax.local", "password": "velmorax123"})
        self.client.post("/login/push-approval", data={"approve": "1"})
        denied_lot = "QA-DENIED-001"
        response = self.client.post("/inventory", data={
            "organization_id": 1, "location_id": 2, "name": "Producto no autorizado",
            "category": "Veterinaria", "brand": "QA", "regulatory_agency": "ICA",
            "regulatory_code": "ICA-DENIED", "lot": denied_lot, "quantity": 1,
            "min_stock": 1, "location": "Bodega", "expiry_date": (date.today() + timedelta(days=90)).isoformat(),
            "received_date": date.today().isoformat(), "document_number": "REM-DENIED",
        }, follow_redirects=False)
        self.assertIn("permission_error=", response.headers["location"])
        with get_connection() as connection:
            self.assertIsNone(connection.execute("SELECT id FROM inventory_items WHERE lot=?", (denied_lot,)).fetchone())
        with get_connection() as connection:
            item = connection.execute("SELECT id FROM inventory_items WHERE location_id=2 LIMIT 1").fetchone()
        denied = self.client.post(f"/inventory/{item['id']}/count", data={"counted_quantity": 1, "organization_id": 1, "location_id": 2}, follow_redirects=False)
        self.assertIn("permission_error=", denied.headers["location"])
        denied_waste = self.client.post("/inventory/movements", data={
            "item_id": item["id"], "movement_type": "out", "quantity": 1,
            "note": "Intento no autorizado", "reason_type": "Merma",
            "organization_id": 1, "location_id": 2,
        }, follow_redirects=False)
        self.assertIn("permission_error=", denied_waste.headers["location"])
        employee_inventory = self.client.get("/inventario?organization_id=1&location_id=2")
        self.assertIn("Registrar consumo", employee_inventory.text)
        self.assertIn("Uso clínico trazable", employee_inventory.text)
        self.assertNotIn("Nuevo lote</strong>", employee_inventory.text)
        self.assertNotIn("<option>Merma</option>", employee_inventory.text)
        self.assertIn("data-open-scanner", employee_inventory.text)
        self.assertIn("Escanear código", employee_inventory.text)
        history_export = self.client.get("/inventario/historial/export?organization_id=1&location_id=2")
        self.assertEqual(history_export.status_code, 200)
        self.assertIn("Paciente", history_export.text)

    def test_inventory_scope_isolated_between_organizations(self):
        self.client.post("/logout")
        self.client.post("/login", data={"intent": "veterinaria", "email": "admin@velmorax.local", "password": "velmorax123"})
        self.client.post("/login/push-approval", data={"approve": "1"})
        with get_connection() as connection:
            connection.execute("INSERT INTO organizations (name, country) VALUES ('Organización ajena QA', 'Colombia')")
            other_org = connection.execute("SELECT id FROM organizations WHERE name='Organización ajena QA'").fetchone()["id"]
            connection.execute("INSERT INTO locations (organization_id,name,city,is_active,catalog_kind) VALUES (?, 'Sede ajena QA', 'Bogotá', 1, 'veterinaria')", (other_org,))
            other_location = connection.execute("SELECT id FROM locations WHERE organization_id=? AND name='Sede ajena QA'", (other_org,)).fetchone()["id"]
            connection.execute(
                """INSERT INTO inventory_items (organization_id,location_id,name,category,brand,regulatory_agency,regulatory_code,lot,quantity,min_stock,location,expiry_date)
                   VALUES (?, ?, 'Producto ajeno QA', 'Veterinaria', 'QA', 'ICA', 'ICA-OTHER', 'OTHER-QA', 5, 1, 'Bodega', ?)""",
                (other_org, other_location, (date.today() + timedelta(days=365)).isoformat()),
            )
            other_item = connection.execute("SELECT id FROM inventory_items WHERE lot='OTHER-QA'").fetchone()["id"]
            connection.commit()
        blocked = self.client.post("/inventory/movements", data={
            "item_id": other_item, "movement_type": "out", "quantity": 1, "note": "Intento cruzado",
            "reason_type": "Merma", "organization_id": 1, "location_id": 2,
        }, follow_redirects=False)
        self.assertIn("permission_error=", blocked.headers["location"])
        blocked_export = self.client.get(f"/inventario/export?organization_id={other_org}&location_id={other_location}", follow_redirects=False)
        self.assertEqual(blocked_export.status_code, 303)
        with get_connection() as connection:
            quantity = connection.execute("SELECT quantity FROM inventory_items WHERE id=?", (other_item,)).fetchone()["quantity"]
        self.assertEqual(quantity, 5)

    def test_veterinary_inventory_transfer_is_balanced_between_configured_sites(self):
        self.client.post("/logout")
        self.client.post("/login", data={"intent": "veterinaria", "email": "admin@velmorax.local", "password": "velmorax123"})
        self.client.post("/login/push-approval", data={"approve": "1"})
        with get_connection() as connection:
            connection.execute(
                "INSERT INTO locations (organization_id, name, city, address, is_active, catalog_kind) VALUES (?, ?, ?, ?, 1, 'veterinaria')",
                (1, "Sede Veterinaria QA", "Bogotá", "Dirección QA"),
            )
            destination_id = connection.execute("SELECT id FROM locations WHERE name='Sede Veterinaria QA'").fetchone()["id"]
            connection.commit()

        lot = "QA-TRANSFER-001"
        payload = {
            "organization_id": 1, "location_id": 2, "name": "Solución QA traslado",
            "category": "Veterinaria", "brand": "QA", "regulatory_agency": "ICA",
            "regulatory_code": "ICA-TR-QA", "supplier": "Proveedor QA", "lot": lot,
            "quantity": 12, "min_stock": 2, "location": "Bodega origen",
            "expiry_date": (date.today() + timedelta(days=365)).isoformat(),
            "received_date": date.today().isoformat(), "document_number": "REM-TR-QA",
            "item_type": "Medicamento", "unit_measure": "unidades",
        }
        created = self.client.post("/inventory", data=payload, follow_redirects=False)
        self.assertIn("saved=1", created.headers["location"])
        with get_connection() as connection:
            source_id = connection.execute("SELECT id FROM inventory_items WHERE lot=? AND location_id=2", (lot,)).fetchone()["id"]

        page = self.client.get("/inventario?organization_id=1&location_id=2")
        self.assertIn("Trasladar", page.text)
        transferred = self.client.post(
            f"/inventory/{source_id}/transfer",
            data={"quantity": 5, "destination_location_id": destination_id, "destination_storage": "Farmacia urgencias", "note": "Reposición operativa", "organization_id": 1, "location_id": 2},
            follow_redirects=False,
        )
        self.assertIn("moved=1", transferred.headers["location"])
        with get_connection() as connection:
            source = connection.execute("SELECT quantity FROM inventory_items WHERE id=?", (source_id,)).fetchone()
            target = connection.execute("SELECT quantity, location FROM inventory_items WHERE lot=? AND location_id=?", (lot, destination_id)).fetchone()
            transfers = connection.execute("SELECT reason_type, transfer_reference, counterparty_location_id FROM inventory_movements WHERE transfer_reference != '' AND item_id IN (?, (SELECT id FROM inventory_items WHERE lot=? AND location_id=?)) ORDER BY id", (source_id, lot, destination_id)).fetchall()
        self.assertEqual(source["quantity"], 7)
        self.assertEqual(target["quantity"], 5)
        self.assertEqual(target["location"], "Farmacia urgencias")
        self.assertEqual(len(transfers), 2)
        self.assertEqual(transfers[0]["transfer_reference"], transfers[1]["transfer_reference"])
        self.assertEqual({row["reason_type"] for row in transfers}, {"Traslado enviado", "Traslado recibido"})

    def test_veterinary_inventory_workflow_supports_replenishment_approval_and_receipt(self):
        self.client.post("/logout")
        self.client.post("/login", data={"intent": "veterinaria", "email": "admin@velmorax.local", "password": "velmorax123"})
        self.client.post("/login/push-approval", data={"approve": "1"})
        with get_connection() as connection:
            source = connection.execute("SELECT id, name, product_id FROM inventory_items WHERE lot='QA-TRANSFER-001' AND location_id=2").fetchone()
        requested = self.client.post(
            "/inventory/replenishments",
            data={"item_id": source["id"], "requested_quantity": 20, "supplier": "Proveedor regional QA", "priority": "Urgente", "note": "Cobertura de urgencias", "organization_id": 1, "location_id": 2},
            follow_redirects=False,
        )
        self.assertIn("saved=1", requested.headers["location"])
        with get_connection() as connection:
            replenishment = connection.execute("SELECT * FROM inventory_replenishments WHERE item_id=?", (source["id"],)).fetchone()
        approved = self.client.post(
            f"/inventory/replenishments/{replenishment['id']}/review",
            data={"decision": "approve", "organization_id": 1, "location_id": 2},
            follow_redirects=False,
        )
        self.assertIn("saved=1", approved.headers["location"])
        received = self.client.post("/inventory", data={
            "organization_id": 1, "location_id": 2, "name": source["name"],
            "category": "Veterinaria", "brand": "QA", "regulatory_agency": "ICA",
            "regulatory_code": "ICA-TR-QA", "supplier": "Proveedor regional QA",
            "lot": "QA-RECEIPT-002", "quantity": 20, "min_stock": 2,
            "location": "Farmacia principal", "expiry_date": (date.today() + timedelta(days=500)).isoformat(),
            "received_date": date.today().isoformat(), "document_number": "REM-PO-QA-002",
            "product_id": source["product_id"], "item_type": "Medicamento", "unit_measure": "unidades",
            "replenishment_request_id": replenishment["id"],
        }, follow_redirects=False)
        self.assertIn("saved=1", received.headers["location"])
        with get_connection() as connection:
            closed = connection.execute("SELECT status, received_inventory_item_id FROM inventory_replenishments WHERE id=?", (replenishment["id"],)).fetchone()
            received_item = connection.execute("SELECT quantity, replenishment_request_id FROM inventory_items WHERE id=?", (closed["received_inventory_item_id"],)).fetchone()
        self.assertEqual(closed["status"], "Recibida")
        self.assertEqual(received_item["quantity"], 20)
        self.assertEqual(received_item["replenishment_request_id"], replenishment["id"])
        page = self.client.get("/inventario?organization_id=1&location_id=2")
        self.assertIn("Abastecimiento", page.text)
        self.assertIn("Vista de red", page.text)


if __name__ == "__main__":
    unittest.main()
