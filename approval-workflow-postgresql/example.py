"""Run the article's correction/reassignment journey in a disposable schema."""

import os
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from workflow import create_request, decide_review, reassign_review, save_draft, submit_request

url = os.environ["APPROVAL_EXAMPLE_DATABASE_URL"]
settings = conninfo_to_dict(url)
if settings.get("host") not in ("127.0.0.1", "localhost") or settings.get("dbname") != "approval_example":
    raise RuntimeError("Use the disposable loopback approval_example database from README.md")

requester, reviewer, substitute, administrator = [UUID(int=value) for value in range(1, 5)]
content = {"item": "Additional monitor", "justification": "Review source material beside a document"}
corrected = {**content, "justification": "The existing display cannot show both documents legibly"}
schema = "approval_demo_" + uuid4().hex

with psycopg.connect(url, autocommit=True, row_factory=dict_row) as connection:
    connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        connection.execute(Path(__file__).with_name("schema.sql").read_text())

        request_id = create_request(connection, requester, content)
        first = submit_request(connection, request_id, requester, 1, reviewer)
        decide_review(
            connection, first["id"], reviewer, first["submission_id"], 1,
            "changes_requested", "Explain why the existing monitor is unsuitable",
        )
        revision = save_draft(connection, request_id, requester, 3, corrected)
        second = submit_request(connection, request_id, requester, revision, reviewer)
        moved = reassign_review(
            connection, second["id"], administrator, 1, substitute,
            "The original reviewer is unavailable",
        )
        decide_review(
            connection, moved["id"], substitute, moved["submission_id"],
            moved["revision"], "approved",
        )

        request = connection.execute("SELECT state, revision FROM approval_requests").fetchone()
        print(f"Request: {request['state']} (revision {request['revision']})")
        for row in connection.execute("""
            SELECT s.submission_number, t.state, t.revision, t.assignee_id
            FROM request_submissions s JOIN review_tasks t ON t.submission_id = s.id
            ORDER BY s.submission_number
        """):
            print(f"Submission {row['submission_number']}: {row['state']} "
                  f"(task revision {row['revision']}, reviewer {row['assignee_id']})")
        for row in connection.execute("SELECT action, details FROM workflow_events ORDER BY id"):
            print(f"History: {row['action']} {row['details']}")
    finally:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
