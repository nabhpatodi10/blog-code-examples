# React + FastAPI background jobs

An original local example accompanying **How to Track Background Job Progress in React and FastAPI**. The report is three short sections of fixed text with intentional worker delays. It makes no model calls.

## Follow the article in the code

| File | Responsibility |
| --- | --- |
| `app.py` | SQLite schema, persisted creation, status/result endpoints and the single worker's startup/shutdown lifecycle. |
| `web/useJob.js` | Sequential polling, response validation, cancellation, connection recovery and terminal states. |
| `web/main.jsx` | Creation form, saved job selection, the `?job=<id>` URL and the progress/download view. |
| `test_app.py` | Disposable-database checks for the API contract and interrupted-worker recovery. |

`POST /api/jobs` saves work before acknowledging it. `GET /api/jobs/{id}` only reads a snapshot. `GET /api/jobs/{id}/result` returns the saved report, and `GET /api/jobs` supports finding work after a lost creation acknowledgement. The article's Python endpoint excerpts use these same functions.

## Run

Requires Python 3.12 or newer, uv, and Node.js 24. Clone this repository first:

    git clone https://github.com/nabhpatodi10/react-fastapi-background-jobs.git
    cd react-fastapi-background-jobs

Then:

1. Start the API in one terminal:

   ```sh
   uv run --with "fastapi==0.141.1" --with "uvicorn==0.52.4" uvicorn app:app --host 127.0.0.1 --port 8009 --workers 1
   ```

2. In another terminal, install the isolated example's JavaScript dependencies and start its view:

   ```sh
   npm ci
   npm run dev
   ```

3. Open http://127.0.0.1:5181/.

Create a report, refresh while it is running and check that the URL still identifies the same job. Temporarily take the browser offline to see the connection warning and recovery. Select the failure mode to exercise a recorded worker failure.

Stop and restart the API to recover queued or interrupted jobs. The database is the ignored local file `jobs.local`; `BLOG_DEMO_DB` can select a separate test database. `BLOG_DEMO_SECTION_DELAY` controls the deliberate delay per section.

## Boundaries

- Run one API process with one worker and bind to loopback. There are no accounts or access checks; do not expose this demo as a hosted service.
- A SQLite transaction persists the completed section before the next one starts. A restart resumes after the last committed section. This is not a lease-based distributed worker.
- Job creation has no idempotency protocol. A lost create acknowledgement must be reconciled through Existing jobs; the UI never automatically repeats that POST.
- Counts mean sections written. They are not estimates of elapsed time or overall production workload.
- Status errors preserve the last known job. Completed and failed states stop polling. Switching jobs tears down the previous polling view.
- The existing-jobs list refreshes on request; its badges are snapshots. The selected job is the view that polls.
- The article's production discussion draws separately on the linked Research-AI source and official documentation; the demo is not a copy of that application.
- The worker is started in FastAPI's lifespan and polls persisted queued jobs. It does not use `BackgroundTasks`, and it is not a general replacement for a durable worker system. SQLite operations here are synchronous and intentionally small.

## Companion article

How to Track Background Job Progress in React and FastAPI is planned for 20 September 2026 on [Nabh's blog](https://nabhpatodi.com/blog/). This repository is the independently runnable companion.

## Verify the API

```sh
uv run --with "fastapi==0.141.1" --with "httpx==0.28.1" python -m unittest test_app.py
```

The checks use disposable databases and exercise persisted creation, usable completion, terminal failure, inaccessible results, and recovery after an interrupted worker.
