import unittest

from app.core.config import Settings


class ProductionSettingsTests(unittest.TestCase):
    def test_secure_production_configuration_is_accepted(self):
        settings = Settings(
            app_env="production",
            session_secret="a" * 64,
            session_https_only=True,
            show_demo_access=False,
            seed_demo_data=False,
            database_url="postgresql://velmorax:secret@postgres/velmorax",
            public_base_url="https://app.clinica.example",
            allowed_hosts=["app.clinica.example", "localhost"],
            legal_company_name="Velmorax Tecnología S.A.S.",
            legal_tax_id="900000000-1",
            legal_contact_email="privacidad@clinica.example",
            legal_contact_address="Bogotá D.C., Colombia",
        )
        settings.validate_production()

    def test_insecure_production_configuration_is_rejected(self):
        settings = Settings(
            app_env="production",
            session_secret="velmorax-dev-secret",
            session_https_only=False,
            show_demo_access=True,
            seed_demo_data=True,
            database_url="sqlite:///data/velmorax.db",
            public_base_url="http://127.0.0.1:8000",
            allowed_hosts=["*"],
        )
        with self.assertRaisesRegex(RuntimeError, "Configuración de producción inválida"):
            settings.validate_production()


if __name__ == "__main__":
    unittest.main()
