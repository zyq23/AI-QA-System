from __future__ import annotations

"""Schema migration and background-job reliability gates (Phase 3 / WS-Reliability).

Covers: fresh init converges to LATEST_VERSION; pre-versioning databases adopt
the ledger without data loss; per-migration rollback; the v2 job-reliability
columns and their repository semantics (attempt/owner/heartbeat/cancel/backlog).
"""

import sqlite3
from pathlib import Path

import pytest

from app.db import Database
from app.migrations import LATEST_VERSION, MIGRATIONS, applied_versions, get_current_version, migration_status, run_migrations
from app.repositories import Repository


def _db(tmp_path: Path, name: str = "app.db") -> Database:
    return Database(tmp_path / name)


def test_fresh_initialize_reaches_latest_version(tmp_path: Path):
    db = _db(tmp_path)
    db.initialize()
    with db.connect() as conn:
        assert get_current_version(conn) == LATEST_VERSION
        assert applied_versions(conn) == [m.version for m in MIGRATIONS]


def test_initialize_is_idempotent(tmp_path: Path):
    db = _db(tmp_path)
    db.initialize()
    db.initialize()  # must not raise or double-apply
    with db.connect() as conn:
        assert get_current_version(conn) == LATEST_VERSION
        assert len(applied_versions(conn)) == len(MIGRATIONS)


def test_legacy_database_adopts_ledger_without_data_loss(tmp_path: Path):
    """Simulates a pre-versioning DB (old inline DDL, user_version=0) with data."""
    path = tmp_path / "app.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, canonical_name TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL, trust_level TEXT NOT NULL, current_version_id TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, disabled_at TEXT
            );
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY, job_type TEXT NOT NULL, status TEXT NOT NULL, message TEXT,
                payload_json TEXT, result_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO documents (id, title, canonical_name, source_type, trust_level, created_at, updated_at) "
            "VALUES ('doc-1', 'T', 't', 'upload', 'internal', 'x', 'x')"
        )
        conn.execute(
            "INSERT INTO jobs (id, job_type, status, created_at, updated_at) VALUES ('job-1', 'evaluation', 'completed', 'x', 'x')"
        )
        conn.commit()

    db = Database(path)
    db.initialize()

    with db.connect() as conn:
        assert get_current_version(conn) == LATEST_VERSION
        # original rows survive
        assert conn.execute("SELECT title FROM documents WHERE id='doc-1'").fetchone()[0] == "T"
        assert conn.execute("SELECT status FROM jobs WHERE id='job-1'").fetchone()[0] == "completed"
        # v2 columns exist with defaults backfilled
        row = conn.execute("SELECT attempt, max_attempts, owner, heartbeat_at, cancelled_at FROM jobs WHERE id='job-1'").fetchone()
        assert row[0] == 0 and row[1] == 3 and row[2] is None and row[3] is None and row[4] is None


def test_migration_failure_rolls_back_and_preserves_previous_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A failing migration must not advance user_version and must not corrupt state."""
    db = _db(tmp_path)
    db.initialize()

    def bad_migration(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE broken_marker (id TEXT PRIMARY KEY)")
        raise RuntimeError("migration exploded")

    broken = MIGRATIONS + [type(MIGRATIONS[-1])(version=LATEST_VERSION + 1, name="bad", apply=bad_migration)]
    monkeypatch.setattr("app.migrations.MIGRATIONS", broken)
    with pytest.raises(RuntimeError, match="migration exploded"):
        run_migrations(db)

    with db.connect() as conn:
        assert get_current_version(conn) == LATEST_VERSION
        # Note: the explicit transaction ensures the version didn't bump; SQLite
        # DDL inside BEGIN IMMEDIATE rolls back on exception.
        assert LATEST_VERSION + 1 not in applied_versions(conn)


def test_second_migration_failure_keeps_first_applied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Each migration commits independently: v1 stays applied if v2 fails."""
    db = _db(tmp_path)  # not initialized yet

    class Boom(Exception):
        pass

    def boom(conn: sqlite3.Connection) -> None:
        raise Boom("v2 refused")

    patched = [MIGRATIONS[0], type(MIGRATIONS[1])(version=MIGRATIONS[1].version, name=MIGRATIONS[1].name, apply=boom)]
    monkeypatch.setattr("app.migrations.MIGRATIONS", patched)
    with pytest.raises(Boom):
        run_migrations(db)

    with db.connect() as conn:
        assert get_current_version(conn) == 1
        assert applied_versions(conn) == [1]
        # v2 columns must not exist
        assert not any(row[1] == "attempt" for row in conn.execute("PRAGMA table_info(jobs)"))


def test_status_reports_pending_after_partial_apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = _db(tmp_path)
    monkeypatch.setattr("app.migrations.MIGRATIONS", MIGRATIONS[:1])
    db.initialize()  # applies only v1
    monkeypatch.undo()  # restore the full migration set for status inspection
    status = migration_status(db)
    assert status["current_version"] == 1
    assert [item["version"] for item in status["pending"]] == [m.version for m in MIGRATIONS[1:]]


# --- job reliability semantics (v2 columns) --------------------------------


def _repo(tmp_path: Path) -> Repository:
    db = _db(tmp_path)
    db.initialize()
    return Repository(db)


def test_job_lifecycle_sets_attempt_owner_heartbeat(tmp_path: Path):
    repo = _repo(tmp_path)
    job = repo.create_job("ingest_document", {"version_id": "v1"})
    assert job["attempt"] == 0
    assert job["max_attempts"] == 3
    assert job["status"] == "queued"

    claimed = repo.claim_job(job["id"], owner="worker-a")
    assert claimed is not None
    assert claimed["status"] == "running"
    assert claimed["attempt"] == 1
    assert claimed["owner"] == "worker-a"
    assert claimed["heartbeat_at"]

    repo.heartbeat_job(job["id"], owner="worker-a")
    repo.complete_job(job["id"], owner="worker-a", message="done", result={"ok": True})
    finished = repo.get_job(job["id"])
    assert finished["status"] == "completed"
    assert finished["attempt"] == 1


def test_claim_is_single_owner_under_contention(tmp_path: Path):
    repo = _repo(tmp_path)
    job = repo.create_job("evaluation", {})
    first = repo.claim_job(job["id"], owner="worker-a")
    second = repo.claim_job(job["id"], owner="worker-b")
    assert first is not None
    assert second is None  # already owned while fresh heartbeat
    # wrong owner cannot complete
    with pytest.raises(RuntimeError):
        repo.complete_job(job["id"], owner="worker-b")
    assert repo.get_job(job["id"])["status"] == "running"


def test_duplicate_active_job_is_superseded(tmp_path: Path):
    """Same job_type+payload: a new queue request supersedes the stale active one
    instead of stacking duplicate active jobs."""
    repo = _repo(tmp_path)
    old = repo.create_job("reindex_document", {"version_id": "v9"})
    new = repo.create_job("reindex_document", {"version_id": "v9"})
    old_row = repo.get_job(old["id"])
    assert old_row["status"] == "cancelled"
    assert new["status"] == "queued"
    # latest_active_job returns the newest only
    active = repo.latest_active_job("reindex_document", {"version_id": "v9"})
    assert active is not None and active["id"] == new["id"]


def test_lost_lease_is_reclaimable_and_exhaustion_fails(tmp_path: Path):
    repo = _repo(tmp_path)
    job = repo.create_job("ingest_document", {"version_id": "v1"})
    repo.claim_job(job["id"], owner="dead-worker", max_attempts=2)
    # simulate a lease lost long ago
    with repo.db.connect() as conn:
        conn.execute("UPDATE jobs SET heartbeat_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (job["id"],))

    reclaimed = repo.claim_job(job["id"], owner="worker-b", max_attempts=2)
    assert reclaimed is not None and reclaimed["owner"] == "worker-b" and reclaimed["attempt"] == 2

    # attempt exhausted: next reclaim moves it to failed, not running
    with repo.db.connect() as conn:
        conn.execute("UPDATE jobs SET status='running', heartbeat_at='2000-01-01T00:00:00+00:00' WHERE id = ?", (job["id"],))
    assert repo.claim_job(job["id"], owner="worker-c", max_attempts=2) is None
    failed = repo.reclaim_stale_jobs(stale_after_seconds=0)
    assert job["id"] in failed
    assert repo.get_job(job["id"])["status"] == "failed"


def test_cancelled_job_refuses_claim(tmp_path: Path):
    repo = _repo(tmp_path)
    job = repo.create_job("evaluation", {})
    assert repo.cancel_job(job["id"]) is True
    assert repo.claim_job(job["id"], owner="worker-a") is None
    assert repo.get_job(job["id"])["cancelled_at"]


def test_job_worker_executes_handler_and_records_completion(tmp_path: Path):
    from app.services.job_worker import JobWorker

    repo = _repo(tmp_path)
    job = repo.create_job("unit", {"value": 42})
    seen: list[dict] = []
    worker = JobWorker(repo, owner="worker-1", heartbeat_interval_seconds=1)

    def handler(payload, context):
        context.check_cancelled()
        seen.append(payload)

    worker.register("unit", handler)
    assert worker.run_one(job["id"]) == "completed"
    assert seen == [{"value": 42}]
    assert repo.get_job(job["id"])["status"] == "completed"


def test_worker_preserves_handler_reported_status(tmp_path: Path):
    """Handlers that self-report must retain their rich result payload."""
    from app.services.job_worker import JobWorker

    repo = _repo(tmp_path)
    job = repo.create_job("self_report", {})
    worker = JobWorker(repo, owner="worker-1", heartbeat_interval_seconds=1)

    def handler(payload, context):
        repo.update_job(context.job_id, status="completed", message="rich message", result={"chunks": 7})

    worker.register("self_report", handler)
    assert worker.run_one(job["id"]) == "completed"
    stored = repo.get_job(job["id"])
    assert stored["message"] == "rich message"
    assert stored["result"] == {"chunks": 7}


def test_ingestion_background_adapter_uses_durable_worker(tmp_path: Path):
    """BackgroundTasks delegates to the worker, which claims and completes the job."""
    from app.services.ingestion import IngestionService
    from app.services.job_worker import JobWorker

    repo = _repo(tmp_path)

    class Parser:
        def parse(self, path):
            from app.domain import ParsedDocument, SourceBlock
            return ParsedDocument(title="t", blocks=[SourceBlock(page_or_slide="p1", section_path="s", content="hello")], raw_markdown="hello", parser_name="stub")

    class Chunker:
        target_size = 100
        overlap = 10
        def chunk(self, parsed, context):
            from app.domain import ChunkRecord
            return [ChunkRecord("c1", context.document_id, context.version_id, context.file_name, context.source_type, context.trust_level, "p1", "s", 0, "h", "hello", "hello", "hello")]

    class Embed:
        def embed_documents(self, texts): return [[0.0] for _ in texts]

    class Store:
        def delete_version(self, version_id): pass
        def upsert_chunks(self, chunks, embeddings): pass

    service = IngestionService(repo, Parser(), Chunker(), Embed(), Store(), tmp_path / "up")
    worker = JobWorker(repo, owner="worker-test", heartbeat_interval_seconds=1)
    worker.register("ingest_document", service.process_job)
    worker.register("reindex_document", service.process_job)
    service.attach_worker(worker)
    doc = repo.create_or_get_document("T", "t.txt", "upload", "internal")
    version_id, _ = service._persist_upload(doc["id"], "t.txt", b"hello")

    class Background:
        tasks = []
        def add_task(self, fn, *args): self.tasks.append((fn, args))

    bg = Background()
    service.reindex_version(version_id, background_tasks=bg)
    fn, args = bg.tasks[-1]
    fn(*args)
    latest = repo.latest_job(job_type="reindex_document")
    assert latest["status"] == "completed"
    assert latest["attempt"] == 1
    assert latest["owner"] == "worker-test"
