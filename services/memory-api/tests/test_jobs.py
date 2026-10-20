import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.domain import UpstreamError
from src.ingest import Ingestor
from src.jobs import HISTORY, IngestJobs, Job, JobInProgressError, JobStore
from tests.fakes import FakeEmbedder, InMemoryStore, Vault

NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)


def job(number: int, status: str = "completed") -> Job:
    return Job.model_validate(
        {"id": f"job-{number:03}", "mode": "incremental", "status": status, "startedAt": f"2026-10-20T{number:06}"}
    )


class TestJobStore:
    def test_keeps_tasks_across_restarts(self, tmp_path: Path) -> None:
        path = tmp_path / "state" / "jobs.db"
        store = JobStore(path)
        store.save(job(1))
        store.close()

        reopened = JobStore(path)
        assert reopened.get("job-001") == job(1)
        assert reopened.get("missing") is None

    def test_marks_tasks_left_running_as_interrupted_on_start(self, tmp_path: Path) -> None:
        store = JobStore(tmp_path / "jobs.db")
        store.save(job(1, "running"))
        store.save(job(2, "completed"))
        store.close()

        reopened = JobStore(tmp_path / "jobs.db", now=lambda: NOW)

        interrupted = reopened.get("job-001")
        assert interrupted is not None
        assert (interrupted.status, interrupted.finished_at) == ("interrupted", "2026-10-20T12:00:00.000Z")
        assert interrupted.error == "the service restarted during the run"
        assert reopened.get("job-002") == job(2)

    def test_lists_the_most_recent_tasks_first_and_prunes_the_oldest(self, tmp_path: Path) -> None:
        store = JobStore(tmp_path / "jobs.db")
        for number in range(1, HISTORY + 6):
            store.save(job(number))

        assert [j.id for j in store.recent(3)] == [f"job-{n:03}" for n in (HISTORY + 5, HISTORY + 4, HISTORY + 3)]
        assert len(store.recent(1000)) == HISTORY
        assert store.get("job-005") is None
        assert store.get("job-006") is not None


@pytest.fixture
def history(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "jobs.db")


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def jobs(vault: Vault, embedder: FakeEmbedder, history: JobStore) -> IngestJobs:
    vault.write("a.md", "# A\nFirst note.")
    vault.write("b.md", "# B\nSecond note.")
    return IngestJobs(Ingestor(str(vault.root), embedder, InMemoryStore(), 200), history)


async def wait(jobs: IngestJobs) -> None:
    while jobs.current is not None:  # noqa: ASYNC110 # polls the public state, as an API client would
        await asyncio.sleep(0.01)


class TestIngestJobs:
    async def test_runs_one_ingestion_in_the_background(self, jobs: IngestJobs, history: JobStore) -> None:
        started = jobs.start("incremental")
        with pytest.raises(JobInProgressError) as raised:
            jobs.start("full")
        assert raised.value.job.id == started.id

        await wait(jobs)

        done = history.get(started.id)
        assert done is not None
        assert (done.status, done.progress.total, done.progress.done) == ("completed", 2, 2)
        assert done.report is not None
        assert done.report.notes.indexed == 2

    async def test_records_an_aborted_run(
        self, jobs: IngestJobs, history: JobStore, embedder: FakeEmbedder, vault: Vault, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        jobs.start("incremental")
        await wait(jobs)
        for i in range(3):
            vault.write(f"new-{i}.md", f"# New {i}\ntext")

        async def ollama_down(texts: list[str]) -> list[list[float]]:
            raise UpstreamError("ollama", "ConnectError")

        monkeypatch.setattr(embedder, "embed_documents", ollama_down)
        aborted = jobs.start("incremental")
        await wait(jobs)

        recorded = history.get(aborted.id)
        assert recorded is not None
        assert recorded.status == "aborted"
        assert recorded.report is not None
        assert recorded.report.aborted

    async def test_records_a_stopped_run_as_interrupted(
        self, jobs: IngestJobs, history: JobStore, embedder: FakeEmbedder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        release = asyncio.Event()
        embed = embedder.embed_documents

        async def slow(texts: list[str]) -> list[list[float]]:
            if texts != ["dimension probe"]:
                await release.wait()
            return await embed(texts)

        monkeypatch.setattr(embedder, "embed_documents", slow)
        started = jobs.start("incremental")
        await asyncio.sleep(0.05)

        await jobs.stop()

        stopped = history.get(started.id)
        assert stopped is not None
        assert (stopped.status, stopped.error) == ("interrupted", "the service stopped during the run")
        assert stopped.finished_at is not None
        assert jobs.current is None
