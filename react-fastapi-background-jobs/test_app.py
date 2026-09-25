import tempfile
import time
import unittest
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

import app


class JobContractTests(unittest.TestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory()
        self.original_db = app.DATABASE
        self.original_delay = app.SECTION_DELAY
        app.DATABASE = Path(self.storage.name) / "jobs.sqlite"
        app.SECTION_DELAY = 0.02

    def tearDown(self):
        app.DATABASE = self.original_db
        app.SECTION_DELAY = self.original_delay
        self.storage.cleanup()

    def wait_for(self, client, job_id, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            payload = client.get(f"/api/jobs/{job_id}").json()
            if predicate(payload):
                return payload
            time.sleep(0.01)
        self.fail(f"Job did not reach the requested state: {payload}")

    def test_acknowledgement_refers_to_a_saved_job(self):
        with TestClient(app.app) as client:
            created = client.post("/api/jobs", json={"mode": "success"})
            self.assertEqual(created.status_code, 202)
            self.assertEqual(created.headers["Cache-Control"], "no-store")
            job_id = created.json()["id"]
            self.assertEqual(created.headers["Location"], f"/api/jobs/{job_id}")
            self.assertEqual(client.get(f"/api/jobs/{job_id}").status_code, 200)
            self.assertEqual(len(client.get("/api/jobs").json()), 1)

    def test_completed_job_has_all_sections_and_a_download(self):
        with TestClient(app.app) as client:
            job_id = client.post("/api/jobs", json={}).json()["id"]
            finished = self.wait_for(client, job_id, lambda job: job["status"] == "completed")
            self.assertTrue(finished["result_available"])
            self.assertEqual(finished["progress"]["completed"], 3)
            result = client.get(f"/api/jobs/{job_id}/result")
            self.assertEqual(result.status_code, 200)
            for heading, _body in app.SECTIONS:
                self.assertEqual(result.text.count(heading), 1)

    def test_failure_is_terminal_without_a_download(self):
        with TestClient(app.app) as client:
            job_id = client.post("/api/jobs", json={"mode": "failure"}).json()["id"]
            failed = self.wait_for(client, job_id, lambda job: job["status"] == "failed")
            self.assertFalse(failed["result_available"])
            self.assertEqual(failed["progress"]["completed"], 1)
            self.assertIn("section 2", failed["error"])
            self.assertEqual(client.get(f"/api/jobs/{job_id}/result").status_code, 409)

    def test_missing_and_invalid_jobs(self):
        with TestClient(app.app) as client:
            self.assertEqual(client.get(f"/api/jobs/{uuid4()}").status_code, 404)
            self.assertEqual(client.post("/api/jobs", json={"mode": "invalid"}).status_code, 422)

    def test_worker_restart_keeps_identity_and_completed_sections(self):
        app.SECTION_DELAY = 0.1
        with TestClient(app.app) as client:
            job_id = client.post("/api/jobs", json={}).json()["id"]
            self.wait_for(client, job_id, lambda job: job["progress"]["completed"] == 1)
            self.assertEqual(client.get(f"/api/jobs/{job_id}/result").status_code, 409)
        with TestClient(app.app) as client:
            finished = self.wait_for(client, job_id, lambda job: job["status"] == "completed")
            self.assertEqual(finished["id"], job_id)
            self.assertEqual(len(client.get("/api/jobs").json()), 1)
            result = client.get(f"/api/jobs/{job_id}/result").text
            self.assertEqual(result.count("Summary"), 1)
            self.assertEqual(result.count("Next steps"), 1)


if __name__ == "__main__":
    unittest.main()
