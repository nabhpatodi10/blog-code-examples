"""Original transaction example, not an authenticated application or workflow engine.

Use a psycopg connection with autocommit=True and row_factory=dict_row.
Actor IDs must come from a trusted server; access, reviewer eligibility and
administrator authority must be established there before calling these commands.
"""

from uuid import uuid4

from psycopg.types.json import Jsonb


class Conflict(Exception):
    pass


def lock_request(connection, request_id):
    row = connection.execute(
        "SELECT * FROM approval_requests WHERE id = %s FOR UPDATE", (request_id,)
    ).fetchone()
    if row is None:
        raise Conflict("Request not found")
    return row


def open_task(connection, task_id, expected_revision):
    locator = connection.execute(
        "SELECT request_id FROM review_tasks WHERE id = %s", (task_id,)
    ).fetchone()
    if locator is None:
        raise Conflict("Task not found")
    # All mutations lock the parent first; only then read current task state.
    request = lock_request(connection, locator["request_id"])
    task = connection.execute(
        "SELECT * FROM review_tasks WHERE id = %s", (task_id,)
    ).fetchone()
    if (request["state"] != "in_review" or task["state"] != "open"
            or task["revision"] != expected_revision):
        raise Conflict("Review changed; reload before acting")
    return request, task


def record_event(connection, task, actor_id, action, details):
    connection.execute(
        """INSERT INTO workflow_events
           (request_id, submission_id, task_id, actor_id, action, details)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (task["request_id"], task["submission_id"], task["id"],
         actor_id, action, Jsonb(details)),
    )


def create_request(connection, requester_id, content):
    request_id = uuid4()
    with connection.transaction():
        connection.execute(
            """INSERT INTO approval_requests (id, requester_id, state, working_content)
               VALUES (%s, %s, 'draft', %s)""",
            (request_id, requester_id, Jsonb(content)),
        )
    return request_id


def save_draft(connection, request_id, actor_id, expected_revision, content):
    with connection.transaction():
        request = lock_request(connection, request_id)
        if (request["requester_id"] != actor_id
                or request["state"] not in ("draft", "changes_requested")
                or request["revision"] != expected_revision):
            raise Conflict("Draft is not editable in the version you opened")
        return connection.execute(
            """UPDATE approval_requests
               SET working_content = %s, revision = revision + 1
               WHERE id = %s RETURNING revision""", (Jsonb(content), request_id)
        ).fetchone()["revision"]


def submit_request(connection, request_id, actor_id, expected_revision, reviewer_id):
    with connection.transaction():
        request = lock_request(connection, request_id)
        if (request["requester_id"] != actor_id
                or request["state"] not in ("draft", "changes_requested")
                or request["revision"] != expected_revision):
            raise Conflict("Request changed or cannot be submitted")
        if reviewer_id == actor_id:
            raise ValueError("The requester cannot review their own request")
        content = request["working_content"]
        if any(not isinstance(content.get(key), str) or not content[key].strip()
               for key in ("item", "justification")):
            raise ValueError("Item and justification are required")
        number = connection.execute(
            """SELECT COALESCE(MAX(submission_number), 0) + 1 AS next_number
               FROM request_submissions WHERE request_id = %s""", (request_id,)
        ).fetchone()["next_number"]
        submission_id, task_id = uuid4(), uuid4()
        connection.execute(
            """INSERT INTO request_submissions
               (id, request_id, submission_number, content) VALUES (%s, %s, %s, %s)""",
            (submission_id, request_id, number, Jsonb(content)),
        )
        task = connection.execute(
            """INSERT INTO review_tasks
               (id, request_id, submission_id, assignee_id, state)
               VALUES (%s, %s, %s, %s, 'open') RETURNING *""",
            (task_id, request_id, submission_id, reviewer_id),
        ).fetchone()
        connection.execute(
            "UPDATE approval_requests SET state = 'in_review', revision = revision + 1 WHERE id = %s",
            (request_id,),
        )
        record_event(connection, task, actor_id, "submitted", {"submission_number": number})
    return task


def decide_review(connection, task_id, actor_id, submission_id, expected_revision,
                  decision, reason=""):
    if decision not in ("approved", "rejected", "changes_requested"):
        raise ValueError("Unsupported decision")
    if decision in ("changes_requested", "rejected") and not reason.strip():
        raise ValueError("Explain what must change or why the request was rejected")
    with connection.transaction():
        request, task = open_task(connection, task_id, expected_revision)
        if actor_id == request["requester_id"]:
            raise Conflict("Self-review is not allowed")
        decided = connection.execute(
            """UPDATE review_tasks
               SET state = %s, revision = revision + 1, decided_at = now()
               WHERE id = %s AND request_id = %s AND assignee_id = %s
                 AND submission_id = %s AND revision = %s AND state = 'open'
               RETURNING *""",
            (decision, task_id, task["request_id"], actor_id, submission_id, expected_revision),
        ).fetchone()
        if decided is None:
            raise Conflict("Assignment or submission changed; reload before acting")
        connection.execute(
            "UPDATE approval_requests SET state = %s, revision = revision + 1 WHERE id = %s",
            (decision, request["id"]),
        )
        record_event(connection, decided, actor_id, decision, {"reason": reason.strip()})
    return decided


def reassign_review(connection, task_id, actor_id, expected_revision, reviewer_id, reason):
    # The calling server must first establish this actor's administrator authority.
    if not reason.strip():
        raise ValueError("A reassignment reason is required")
    with connection.transaction():
        request, task = open_task(connection, task_id, expected_revision)
        if reviewer_id == request["requester_id"]:
            raise ValueError("The requester cannot review their own request")
        reassigned = connection.execute(
            """UPDATE review_tasks SET assignee_id = %s, revision = revision + 1
               WHERE id = %s RETURNING *""", (reviewer_id, task_id)
        ).fetchone()
        record_event(connection, reassigned, actor_id, "reassigned", {
            "previous_assignee": str(task["assignee_id"]),
            "assignee": str(reviewer_id), "reason": reason.strip(),
        })
    return reassigned
