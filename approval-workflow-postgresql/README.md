# Approval workflow: runnable PostgreSQL companion

An original equipment-request example for [Approval Workflow Database Design: Requests, Versions and Review Tasks](https://nabhpatodi.com/blog/approval-workflow-design-states-roles-and-audit-trails/). It follows one request through submission, return for correction, resubmission, reassignment and approval.

## Files

- `schema.sql`: requests, fixed submissions, review tasks, a small history table and evidence-change guards.
- `workflow.py`: transaction commands using bound psycopg parameters and a consistent parent-row lock.
- `example.py`: the complete journey shown in the article, with the resulting versions and history printed.
- `test_workflow.py`: nine checks, including simultaneous decisions on separate database connections and rollback when history storage fails.

Requires Docker, Python 3.12 or newer, and uv. These instructions use PostgreSQL 18.4 and psycopg 3.3.5.

## Run locally

Clone the examples repository and enter this example's directory:

```sh
git clone https://github.com/nabhpatodi10/blog-code-examples.git
cd blog-code-examples/approval-workflow-postgresql
```

From this directory, start a disposable database. It binds only to loopback, uses a demonstration password and stores its data in temporary memory. Use this container only for the example.

```sh
docker run --rm --detach --name approval-workflow-example --env POSTGRES_PASSWORD=local-example-only --env POSTGRES_DB=approval_example --publish 127.0.0.1:55439:5432 --tmpfs /var/lib/postgresql postgres:18.4-bookworm
docker exec approval-workflow-example pg_isready -U postgres -d approval_example
```

Wait until `pg_isready` reports that connections are accepted. If port 55439 is occupied, choose an unused port and use it in the connection URL too.

Set the connection URL in PowerShell:

```powershell
$env:APPROVAL_EXAMPLE_DATABASE_URL = 'postgresql://postgres:local-example-only@127.0.0.1:55439/approval_example'
```

Or in a POSIX shell:

```sh
export APPROVAL_EXAMPLE_DATABASE_URL='postgresql://postgres:local-example-only@127.0.0.1:55439/approval_example'
```

Run the walkthrough and tests:

```sh
uv run --with "psycopg[binary]==3.3.5" python example.py
uv run --with "psycopg[binary]==3.3.5" python -m unittest -v test_workflow.py
```

The walkthrough and each test create their own uniquely named schema and remove it afterwards. Both refuse non-loopback hosts and database names other than `approval_example`.

The walkthrough ends with an approved request at revision 6. Submission 1 has a closed `changes_requested` task; submission 2 has an `approved` task at revision 3 after reassignment and decision. Its five history entries are `submitted`, `changes_requested`, `submitted`, `reassigned` and `approved`.

Stop the example database when finished:

```sh
docker stop approval-workflow-example
```

## What is tested

- Correction preserves submission 1 and creates submission 2 with a new task.
- Reassignment invalidates the old reviewer and revision, even after reassignment back to them.
- Concurrent approval and rejection produce one winner and one decision event.
- A failed history insert rolls back both the decision and request state.
- Self-review, a wrong submitted version, unsupported decisions and missing reasons are refused.
- Submission requires content and a reviewer other than the requester.
- Stale draft edits and edits during review are refused.
- Ordinary updates and deletes cannot rewrite submissions or history.
- Foreign keys reject cross-request submission links; the partial index rejects two open tasks.

## Boundaries

This is a transaction example, not a complete approval application. It does not implement authentication, tenant access, identity/role storage, reviewer eligibility, administrator authorisation, document uploads, notifications or an idempotency protocol. The trusted calling server must establish access and authority before calling a command; do not expose supplied actor IDs as an authentication mechanism.

The test account owns its database. In a deployed system, use separate migration/runtime roles and restricted privileges. The evidence triggers reject ordinary row updates/deletes; an owner or superuser can remove those triggers or truncate tables. The example does not claim tamper-proof storage.

There is exactly one assigned review step. Conditional routing, parallel/sequential stages, escalation, withdrawal and the invalidation of earlier approvals after a correction require explicit additional rules.

All request mutations in this example use the same commands and parent-row lock. Direct writes that bypass them are outside that concurrency contract. Connections use `autocommit=True`; each command opens its own explicit transaction.

No private client code, schema or policy is included. This directory contains this README and the four files listed above.
