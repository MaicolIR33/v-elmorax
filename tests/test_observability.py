import json
import logging
import os
from io import StringIO
from pathlib import Path
import unittest

from fastapi.testclient import TestClient

TEST_DB = Path("data") / "velmorax-test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["SESSION_SECRET"] = "velmorax-test-secret"

from app.core.observability import JsonFormatter
from app.main import app


class ObservabilityTests(unittest.TestCase):
    def test_health_endpoints_and_request_id(self):
        with TestClient(app) as client:
            live = client.get("/health/live")
            ready = client.get("/health/ready", headers={"X-Request-ID": "qa-request-12345"})
        self.assertEqual(live.status_code, 200)
        self.assertEqual(live.json()["check"], "liveness")
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json()["database_status"], "ok")
        self.assertEqual(ready.headers["X-Request-ID"], "qa-request-12345")

    def test_json_logs_do_not_need_request_content(self):
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        test_logger = logging.getLogger("velmorax-test-json")
        test_logger.handlers = [handler]
        test_logger.propagate = False
        test_logger.setLevel(logging.INFO)
        test_logger.info(
            "Request completed",
            extra={"event": "request_completed", "path": "/agenda", "status_code": 200},
        )
        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["path"], "/agenda")
        self.assertEqual(payload["status_code"], 200)
        self.assertNotIn("query", payload)
        self.assertNotIn("body", payload)


if __name__ == "__main__":
    unittest.main()
