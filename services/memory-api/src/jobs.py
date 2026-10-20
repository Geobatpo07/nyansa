"""Ingestion tasks: run in the background, their state kept in SQLite.

The state survives a restart. A task still marked running when the service
starts was interrupted (stop, crash, power loss): it is marked so and not
resumed. Incremental ingestion is idempotent, so the next run only indexes
what the interrupted one did not record.
"""

import asyncio
import json
import logging
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from .ingest import CamelModel, IngestMode, Ingestor, IngestReport, iso

type JobStatus = Literal["running", "completed", "aborted", "failed", "interrupted"]

# Finished tasks kept in the database.
HISTORY = 100

log = logging.getLogger(__name__)


class Progress(CamelModel):
    # Notes to index in this run (new or changed), and notes already attempted.
    total: int = 0
    done: int = 0


class Job(CamelModel):
    id: str
    mode: IngestMode
    # running, then completed (errors on single notes are in the report),
    # aborted (upstream service down), failed (the run could not complete)
    # or interrupted (the service stopped during the run).
    status: JobStatus
    started_at: str
    finished_at: str | None = None
    progress: Progress = Field(default_factory=Progress)
    report: IngestReport | None = None
    error: str | None = None


class JobInProgressError(Exception):
    def __init__(self, job: Job) -> None:
        super().__init__("an ingestion is already running")
        self.job = job


class JobStore:
    """Tasks in a SQLite file. Each write is a short transaction on the event loop thread."""

    def __init__(self, path: str | Path, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL, started_at TEXT NOT NULL, "
            "data TEXT NOT NULL)"
        )
        for job in self._query("SELECT data FROM jobs WHERE status = 'running'"):
            job.status, job.finished_at, job.error = "interrupted", iso(now()), "the service restarted during the run"
            self.save(job)
            log.warning("ingestion %s was interrupted by a restart", job.id)

    def save(self, job: Job) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO jobs (id, status, started_at, data) VALUES (?, ?, ?, ?)",
                (job.id, job.status, job.started_at, job.model_dump_json()),
            )
            self._db.execute(
                "DELETE FROM jobs WHERE status != 'running' AND id NOT IN "
                "(SELECT id FROM jobs ORDER BY started_at DESC LIMIT ?)",
                (HISTORY,),
            )

    def get(self, job_id: str) -> Job | None:
        jobs = self._query("SELECT data FROM jobs WHERE id = ?", (job_id,))
        return jobs[0] if jobs else None

    def recent(self, limit: int = 20) -> list[Job]:
        return self._query("SELECT data FROM jobs ORDER BY started_at DESC LIMIT ?", (limit,))

    def close(self) -> None:
        self._db.close()

    def _query(self, sql: str, parameters: tuple[object, ...] = ()) -> list[Job]:
        return [Job.model_validate(json.loads(data)) for (data,) in self._db.execute(sql, parameters)]


class IngestJobs:
    """Starts one ingestion at a time in the background and records its progress."""

    def __init__(
        self, ingestor: Ingestor, store: JobStore, now: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._ingestor = ingestor
        self._store = store
        self._now = now
        self._current: Job | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def current(self) -> Job | None:
        """The running task, if any."""
        return self._current

    def start(self, mode: IngestMode) -> Job:
        if self._current is not None:
            raise JobInProgressError(self._current)
        job = Job(id=str(uuid.uuid4()), mode=mode, status="running", started_at=iso(self._now()))
        self._store.save(job)
        self._current = job
        self._task = asyncio.create_task(self._run(job))
        return job

    async def stop(self) -> None:
        """Cancels the running task, which is recorded as interrupted."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self, job: Job) -> None:
        def progress(done: int, total: int) -> None:
            job.progress = Progress(total=total, done=done)
            self._store.save(job)

        try:
            job.report = await self._ingestor.run(job.mode, on_progress=progress)
            job.status = "aborted" if job.report.aborted else "completed"
        except asyncio.CancelledError:
            job.status, job.error = "interrupted", "the service stopped during the run"
            raise
        except Exception as err:
            job.status, job.error = "failed", str(err)
            log.exception("ingestion %s failed", job.id)
        finally:
            job.finished_at = iso(self._now())
            self._store.save(job)
            self._current = None
