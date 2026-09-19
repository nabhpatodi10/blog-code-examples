"""Local, single-process example for the background-job progress article."""

import asyncio
import json
import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager, suppress
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

DATABASE = Path(os.environ.get("BLOG_DEMO_DB", Path(__file__).with_name("jobs.local")))
SECTION_DELAY = float(os.environ.get("BLOG_DEMO_SECTION_DELAY", "2"))
SECTIONS = (
    ("Summary", "The report follows one persisted job from request to result."),
    ("Observations", "The browser reads recorded progress and can reconnect."),
    ("Next steps", "Open the result without starting another job."),
)


@contextmanager
def database():
    connection = sqlite3.connect(DATABASE, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialise():
    with database() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL CHECK (
                    status IN ('queued', 'running', 'completed', 'failed')
                ),
                mode TEXT NOT NULL CHECK (mode IN ('success', 'failure')),
                completed INTEGER NOT NULL DEFAULT 0,
                label TEXT NOT NULL DEFAULT 'Waiting for the worker',
                parts TEXT NOT NULL DEFAULT '[]',
                error TEXT
            )
        """)
        # Exactly one local worker: continue after the last committed section.
        connection.execute("""
            UPDATE jobs SET status = 'queued', label = 'Waiting to resume'
            WHERE status = 'running'
        """)


def claim_job():
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM jobs WHERE status = 'queued' ORDER BY rowid LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        connection.execute(
            "UPDATE jobs SET status = 'running' WHERE id = ?", (row["id"],)
        )
        return dict(row)


async def run_job(job):
    parts = json.loads(job["parts"])
    for index in range(job["completed"], len(SECTIONS)):
        with database() as connection:
            connection.execute(
                "UPDATE jobs SET label = ? WHERE id = ?",
                (f"Writing section {index + 1} of {len(SECTIONS)}", job["id"]),
            )
        # A deliberate teaching delay, not a measured estimate of real work.
        await asyncio.sleep(SECTION_DELAY)
        if job["mode"] == "failure" and index == 1:
            with database() as connection:
                connection.execute(
                    "UPDATE jobs SET status = 'failed', label = ?, error = ? WHERE id = ?",
                    ("Report stopped", "The demo worker stopped at section 2.", job["id"]),
                )
            return
        heading, body = SECTIONS[index]
        parts.append(f"{heading}\n{body}")
        complete = index + 1 == len(SECTIONS)
        # The final result and completed state are committed together.
        with database() as connection:
            connection.execute(
                "UPDATE jobs SET completed = ?, parts = ?, status = ?, label = ? WHERE id = ?",
                (
                    index + 1,
                    json.dumps(parts),
                    "completed" if complete else "running",
                    "Report ready" if complete else f"{index + 1} sections written",
                    job["id"],
                ),
            )


async def worker():
    while True:
        job = claim_job()
        if job is None:
            await asyncio.sleep(0.1)
        else:
            await run_job(job)


@asynccontextmanager
async def lifespan(_app):
    initialise()
    task = asyncio.create_task(worker())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(lifespan=lifespan)


class NewJob(BaseModel):
    mode: Literal["success", "failure"] = "success"


def job_snapshot(row):
    parts = json.loads(row["parts"])
    return {
        "id": row["id"],
        "status": row["status"],
        "progress": {
            "label": row["label"],
            "completed": row["completed"],
            "total": len(SECTIONS),
        },
        "result_available": row["status"] == "completed" and bool(parts),
        "error": row["error"],
    }


def get_job(job_id):
    with database() as connection:
        row = connection.execute(
            "SELECT * FROM jobs WHERE id = ?", (str(job_id),)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Job not found")
    return row


@app.post("/api/jobs", status_code=202)
async def create_job(body: NewJob, response: Response):
    job_id = str(uuid4())
    with database() as connection:
        connection.execute(
            "INSERT INTO jobs (id, status, mode) VALUES (?, 'queued', ?)",
            (job_id, body.mode),
        )
    response.headers.update({
        "Location": f"/api/jobs/{job_id}",
        "Retry-After": "2",
        "Cache-Control": "no-store",
    })
    return {"id": job_id, "status": "queued"}


@app.get("/api/jobs")
async def list_jobs(response: Response):
    response.headers["Cache-Control"] = "no-store"
    with database() as connection:
        rows = connection.execute("SELECT * FROM jobs ORDER BY rowid DESC").fetchall()
    return [job_snapshot(row) for row in rows]


@app.get("/api/jobs/{job_id}")
async def read_job(job_id: UUID, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return job_snapshot(get_job(job_id))


@app.get("/api/jobs/{job_id}/result")
async def read_result(job_id: UUID):
    row = get_job(job_id)
    parts = json.loads(row["parts"])
    if row["status"] != "completed" or not parts:
        raise HTTPException(409, "A completed result is not available")
    return PlainTextResponse(
        "\n\n".join(parts),
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="report-{job_id}.txt"',
        },
    )
