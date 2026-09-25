-- Original, single-review teaching schema. Run in an empty example schema.
CREATE TABLE approval_requests (
    id uuid PRIMARY KEY,
    requester_id uuid NOT NULL,
    state text NOT NULL CHECK (
        state IN ('draft', 'in_review', 'changes_requested', 'approved', 'rejected')
    ),
    working_content jsonb NOT NULL CHECK (jsonb_typeof(working_content) = 'object'),
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0)
);

CREATE TABLE request_submissions (
    id uuid PRIMARY KEY,
    request_id uuid NOT NULL REFERENCES approval_requests(id),
    submission_number integer NOT NULL CHECK (submission_number > 0),
    content jsonb NOT NULL,
    submitted_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (request_id, submission_number),
    UNIQUE (request_id, id)
);

CREATE TABLE review_tasks (
    id uuid PRIMARY KEY,
    request_id uuid NOT NULL,
    submission_id uuid NOT NULL UNIQUE,
    assignee_id uuid NOT NULL,
    state text NOT NULL CHECK (
        state IN ('open', 'approved', 'changes_requested', 'rejected')
    ),
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    decided_at timestamptz,
    FOREIGN KEY (request_id, submission_id)
        REFERENCES request_submissions(request_id, id)
);

CREATE UNIQUE INDEX one_open_review_per_request
    ON review_tasks (request_id) WHERE state = 'open';

CREATE TABLE workflow_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id uuid NOT NULL REFERENCES approval_requests(id),
    submission_id uuid NOT NULL REFERENCES request_submissions(id),
    task_id uuid NOT NULL REFERENCES review_tasks(id),
    actor_id uuid NOT NULL,
    action text NOT NULL,
    details jsonb NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now()
);

-- Protect snapshots/history against ordinary UPDATE/DELETE statements.
-- This is not protection against a table owner or superuser changing the schema.
CREATE FUNCTION refuse_evidence_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Submitted evidence and history cannot be changed';
END;
$$;

CREATE TRIGGER keep_submissions_fixed
    BEFORE UPDATE OR DELETE ON request_submissions
    FOR EACH ROW EXECUTE FUNCTION refuse_evidence_change();
CREATE TRIGGER keep_events_fixed
    BEFORE UPDATE OR DELETE ON workflow_events
    FOR EACH ROW EXECUTE FUNCTION refuse_evidence_change();
