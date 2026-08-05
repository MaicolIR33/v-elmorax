import os
import re
import unittest
from pathlib import Path


TEST_DB = Path("data") / "velmorax-test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["SESSION_SECRET"] = "velmorax-test-secret"

from fastapi.testclient import TestClient

from app.main import app


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


if __name__ == "__main__":
    unittest.main()
