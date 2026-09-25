"""Run only against the disposable loopback database described in README.md."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
import unittest
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from workflow import (
    Conflict, create_request, decide_review, reassign_review, save_draft, submit_request,
)

REQUESTER, REVIEWER, SUBSTITUTE, ADMIN = [UUID(int=value) for value in range(1, 5)]
CONTENT = {"item": "Additional monitor", "justification": "Review source material beside a document"}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.url = os.environ["APPROVAL_EXAMPLE_DATABASE_URL"]
        settings = conninfo_to_dict(self.url)
        if settings.get("host") not in ("127.0.0.1", "localhost") or settings.get("dbname") != "approval_example":
            raise RuntimeError("Use the disposable loopback approval_example database")
        self.schema = "approval_test_" + uuid4().hex
        self.connection = psycopg.connect(self.url, autocommit=True, row_factory=dict_row)
        self.connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self.schema)))
        self.connection.execute(Path(__file__).with_name("schema.sql").read_text())

    def tearDown(self):
        # Only the uniquely named schema created by this test is removed.
        self.connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))
        self.connection.close()

    def request_row(self, request_id):
        return self.connection.execute(
            "SELECT * FROM approval_requests WHERE id = %s", (request_id,)
        ).fetchone()

    def submitted(self):
        request_id = create_request(self.connection, REQUESTER, CONTENT)
        return request_id, submit_request(self.connection, request_id, REQUESTER, 1, REVIEWER)

    def decide(self, task, decision="approved", actor=REVIEWER, reason=""):
        return decide_review(self.connection, task["id"], actor, task["submission_id"],
                             task["revision"], decision, reason)

    def test_correction_resubmits_without_replacing_evidence(self):
        request_id, first = self.submitted()
        self.decide(first, "changes_requested", reason="Explain why the existing monitor is unsuitable")
        corrected = {**CONTENT, "justification": "The existing display cannot show both documents legibly"}
        revision = save_draft(self.connection, request_id, REQUESTER, 3, corrected)
        second = submit_request(self.connection, request_id, REQUESTER, revision, REVIEWER)
        self.assertNotEqual(first["id"], second["id"])
        with self.assertRaises(Conflict):
            self.decide(first)
        self.decide(second)
        self.assertEqual(self.request_row(request_id)["state"], "approved")
        versions = self.connection.execute(
            "SELECT submission_number, content FROM request_submissions ORDER BY submission_number"
        ).fetchall()
        self.assertEqual(versions, [
            {"submission_number": 1, "content": CONTENT},
            {"submission_number": 2, "content": corrected},
        ])
        events = self.connection.execute("SELECT action FROM workflow_events ORDER BY id").fetchall()
        self.assertEqual([row["action"] for row in events],
                         ["submitted", "changes_requested", "submitted", "approved"])

    def test_reassignment_away_and_back_does_not_restore_old_authority(self):
        request_id, original = self.submitted()
        moved = reassign_review(self.connection, original["id"], ADMIN, 1, SUBSTITUTE, "Reviewer unavailable")
        with self.assertRaises(Conflict):
            self.decide(original)
        with self.assertRaises(Conflict):
            self.decide(moved, actor=REVIEWER)
        returned = reassign_review(self.connection, moved["id"], ADMIN, 2, REVIEWER, "Reviewer returned")
        with self.assertRaises(Conflict):
            self.decide(original)
        self.assertEqual(returned["revision"], 3)
        self.assertEqual(self.request_row(request_id)["state"], "in_review")
        self.decide(returned)

    def test_competing_decisions_have_one_winner_and_one_event(self):
        request_id, task = self.submitted()
        start = Barrier(2)

        def compete(decision):
            with psycopg.connect(self.url, autocommit=True, row_factory=dict_row) as connection:
                connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self.schema)))
                connection.execute("SET lock_timeout = '5s'")
                start.wait(timeout=5)
                try:
                    decide_review(connection, task["id"], REVIEWER, task["submission_id"],
                                  1, decision, "Recorded reviewer explanation")
                    return decision
                except Conflict:
                    return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(compete, ("approved", "rejected")))
        self.assertEqual(outcomes.count("conflict"), 1)
        winner = next(result for result in outcomes if result != "conflict")
        self.assertEqual(self.request_row(request_id)["state"], winner)
        events = self.connection.execute(
            "SELECT action FROM workflow_events WHERE action IN ('approved', 'rejected')"
        ).fetchall()
        self.assertEqual(events, [{"action": winner}])

    def test_history_failure_rolls_back_the_decision_and_request(self):
        request_id, task = self.submitted()
        self.connection.execute("""
            CREATE FUNCTION simulate_history_failure() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'Simulated history storage failure'; END; $$;
            CREATE TRIGGER fail_history BEFORE INSERT ON workflow_events
            FOR EACH ROW EXECUTE FUNCTION simulate_history_failure();
        """)
        with self.assertRaises(psycopg.Error):
            self.decide(task)
        self.assertEqual(self.request_row(request_id)["state"], "in_review")
        current = self.connection.execute("SELECT state, revision FROM review_tasks").fetchone()
        self.assertEqual(current, {"state": "open", "revision": 1})

    def test_self_review_wrong_version_and_invalid_decisions_are_refused(self):
        _request_id, task = self.submitted()
        with self.assertRaises(Conflict):
            self.decide(task, actor=REQUESTER)
        with self.assertRaises(Conflict):
            decide_review(self.connection, task["id"], REVIEWER, uuid4(), 1, "approved")
        for decision, reason in (("open", ""), ("changes_requested", " "), ("rejected", "")):
            with self.assertRaises(ValueError):
                self.decide(task, decision, reason=reason)

    def test_submission_requires_content_and_a_different_reviewer(self):
        request_id = create_request(self.connection, REQUESTER, {})
        with self.assertRaises(ValueError):
            submit_request(self.connection, request_id, REQUESTER, 1, REVIEWER)
        revision = save_draft(self.connection, request_id, REQUESTER, 1, CONTENT)
        with self.assertRaises(ValueError):
            submit_request(self.connection, request_id, REQUESTER, revision, REQUESTER)
        self.assertEqual(self.request_row(request_id)["state"], "draft")

    def test_stale_or_in_review_drafts_cannot_overwrite_content(self):
        request_id = create_request(self.connection, REQUESTER, CONTENT)
        save_draft(self.connection, request_id, REQUESTER, 1, CONTENT)
        with self.assertRaises(Conflict):
            save_draft(self.connection, request_id, REQUESTER, 1, {})
        submit_request(self.connection, request_id, REQUESTER, 2, REVIEWER)
        with self.assertRaises(Conflict):
            save_draft(self.connection, request_id, REQUESTER, 3, {})

    def test_submissions_and_events_refuse_ordinary_update_or_delete(self):
        self.submitted()
        for statement in (
            "UPDATE request_submissions SET content = '{}'",
            "DELETE FROM request_submissions",
            "UPDATE workflow_events SET action = 'rewritten'",
            "DELETE FROM workflow_events",
        ):
            with self.assertRaises(psycopg.Error):
                self.connection.execute(statement)

    def test_constraints_reject_cross_request_links_and_two_open_tasks(self):
        first_request, first_task = self.submitted()
        second_request, _second_task = self.submitted()
        extra_submission = uuid4()
        self.connection.execute(
            """INSERT INTO request_submissions (id, request_id, submission_number, content)
               VALUES (%s, %s, 2, '{}')""", (extra_submission, first_request)
        )
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.connection.execute(
                """INSERT INTO review_tasks (id, request_id, submission_id, assignee_id, state)
                   VALUES (%s, %s, %s, %s, 'approved')""",
                (uuid4(), second_request, extra_submission, REVIEWER),
            )
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self.connection.execute(
                """INSERT INTO review_tasks (id, request_id, submission_id, assignee_id, state)
                   VALUES (%s, %s, %s, %s, 'open')""",
                (uuid4(), first_request, extra_submission, REVIEWER),
            )
        self.decide(first_task)


if __name__ == "__main__":
    unittest.main()
