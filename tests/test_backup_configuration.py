from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BackupConfigurationTests(unittest.TestCase):
    def test_backup_cycle_encrypts_and_verifies_a_restore(self):
        script = (ROOT / "deploy" / "backup-cycle.sh").read_text()
        self.assertIn("pg_dump --format=custom", script)
        self.assertIn("openssl enc -aes-256-cbc", script)
        self.assertIn("sha256sum", script)
        self.assertIn("createdb", script)
        self.assertIn("pg_restore", script)
        self.assertIn("to_regclass", script)

    def test_production_stack_does_not_publish_postgres(self):
        compose = (ROOT / "docker-compose.production.yml").read_text()
        postgres_section = compose.split("  postgres:", 1)[1].split("\n  app:", 1)[0]
        self.assertNotIn("ports:", postgres_section)
        self.assertIn("backup:", compose)
        self.assertIn("backup_passphrase", (ROOT / "deploy" / "backup-cycle.sh").read_text())


if __name__ == "__main__":
    unittest.main()
