"""Versioned SQLite schema migrations.

The schema evolves through ordered migrations stamped onto the database via
``PRAGMA user_version`` plus a ``schema_migrations`` log table. New databases
apply every migration in order; existing databases (created by the old
``CREATE TABLE IF NOT EXISTS`` bootstrap, user_version=0) are safe because the
baseline migration re-applies the same idempotent DDL before stamping.

Conventions:
- Versions are strictly increasing integers; never renumber a shipped migration.
- Each migration runs inside its own transaction, so a failure rolls back and
  leaves the previous version intact.
- Add new schema changes as a new migration at the end of MIGRATIONS; do not
  edit shipped migrations.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from app.db import Database


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _baseline(conn: sqlite3.Connection) -> None:
    # The historical schema, previously created inline in Database.initialize().
    # Kept idempotent (IF NOT EXISTS) so pre-versioning databases can adopt the
    # migration ledger without losing anything.
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            canonical_name TEXT NOT NULL UNIQUE,
            source_type TEXT NOT NULL,
            trust_level TEXT NOT NULL,
            current_version_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            disabled_at TEXT
        );

        CREATE TABLE IF NOT EXISTS document_versions (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL,
            original_filename TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            parser_status TEXT NOT NULL,
            index_status TEXT NOT NULL,
            parser_name TEXT,
            ocr_used INTEGER NOT NULL DEFAULT 0,
            warning_text TEXT,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(document_id, version_number)
        );

        CREATE TABLE IF NOT EXISTS chunks (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            version_id TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
            file_name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            trust_level TEXT NOT NULL,
            page_or_slide TEXT NOT NULL,
            section_path TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            chunk_hash TEXT NOT NULL,
            markdown_text TEXT NOT NULL,
            plain_text TEXT NOT NULL,
            search_text TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            search_text,
            content='chunks',
            content_rowid='rowid',
            tokenize='unicode61'
        );

        CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(rowid, search_text) VALUES (new.rowid, new.search_text);
        END;

        CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, search_text) VALUES('delete', old.rowid, old.search_text);
        END;

        CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, search_text) VALUES('delete', old.rowid, old.search_text);
            INSERT INTO chunks_fts(rowid, search_text) VALUES (new.rowid, new.search_text);
        END;

        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            grounded INTEGER,
            citations_json TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL,
            message TEXT,
            payload_json TEXT,
            result_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS answer_runs (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            question TEXT NOT NULL,
            rewritten_query TEXT NOT NULL,
            question_type TEXT NOT NULL,
            answer_focus TEXT NOT NULL,
            retrieval_json TEXT NOT NULL,
            draft_json TEXT NOT NULL,
            review_json TEXT NOT NULL,
            final_answer TEXT NOT NULL,
            final_grounded_answer TEXT NOT NULL,
            final_inference_note TEXT NOT NULL,
            final_grounded INTEGER NOT NULL,
            stage_status TEXT NOT NULL,
            failure_stage TEXT,
            latency_total_ms INTEGER NOT NULL,
            latency_retrieval_ms INTEGER NOT NULL,
            latency_generate_ms INTEGER NOT NULL,
            latency_review_ms INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_versions_document ON document_versions(document_id, version_number DESC);
        CREATE INDEX IF NOT EXISTS idx_chunks_version ON chunks(version_id);
        CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_answer_runs_conversation ON answer_runs(conversation_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_answer_runs_created_at ON answer_runs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);

        CREATE TABLE IF NOT EXISTS agent_sessions (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            intent TEXT,
            intent_confidence REAL,
            slots_json TEXT,
            used_tools_json TEXT,
            intermediate_json TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agent_steps (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
            step_index INTEGER NOT NULL,
            step_type TEXT NOT NULL,
            tool_name TEXT,
            thought TEXT,
            observation TEXT,
            duration_ms INTEGER,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_agent_sessions_conversation ON agent_sessions(conversation_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_agent_steps_session ON agent_steps(session_id, step_index);
        """
    )


def _job_reliability_columns(conn: sqlite3.Connection) -> None:
    """v2: attempt/owner/heartbeat/cancel columns for reliable background jobs."""
    if not _has_column(conn, "jobs", "attempt"):
        conn.execute("ALTER TABLE jobs ADD COLUMN attempt INTEGER NOT NULL DEFAULT 0")
    if not _has_column(conn, "jobs", "max_attempts"):
        conn.execute("ALTER TABLE jobs ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 3")
    if not _has_column(conn, "jobs", "owner"):
        conn.execute("ALTER TABLE jobs ADD COLUMN owner TEXT")
    if not _has_column(conn, "jobs", "heartbeat_at"):
        conn.execute("ALTER TABLE jobs ADD COLUMN heartbeat_at TEXT")
    if not _has_column(conn, "jobs", "cancelled_at"):
        conn.execute("ALTER TABLE jobs ADD COLUMN cancelled_at TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_type_status ON jobs(job_type, status)")


MIGRATIONS: list[Migration] = [
    Migration(version=1, name="baseline_schema", apply=_baseline),
    Migration(version=2, name="job_reliability_columns", apply=_job_reliability_columns),
]

LATEST_VERSION = MIGRATIONS[-1].version if MIGRATIONS else 0


def _ensure_ledger(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def get_current_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def applied_versions(conn: sqlite3.Connection) -> list[int]:
    _ensure_ledger(conn)
    rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    return [int(row[0]) for row in rows]


def run_migrations(db: Database) -> list[int]:
    """Apply pending migrations; returns the list of versions applied now.

    Each migration runs inside one explicit transaction: Database.connect()
    commits on success and rolls back on exception, and migrations execute in
    non-autocommit mode (sqlite3 defers DDL into the open transaction). A
    failing migration therefore leaves neither schema changes nor a version
    bump behind. The baseline migration uses executescript, whose implicit
    COMMIT is safe: its DDL is IF NOT EXISTS idempotent and re-applying it is
    a no-op.
    """
    applied_now: list[int] = []
    with db.connect() as conn:
        _ensure_ledger(conn)
        current = get_current_version(conn)
        stamped = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    for migration in MIGRATIONS:
        if migration.version <= current or migration.version in stamped:
            continue
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            migration.apply(conn)
            conn.execute(
                "INSERT OR REPLACE INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, datetime.now(timezone.utc).isoformat()),
            )
            conn.execute(f"PRAGMA user_version = {migration.version}")
            applied_now.append(migration.version)
    return applied_now


def migration_status(db: Database) -> dict:
    with db.connect() as conn:
        _ensure_ledger(conn)
        current = get_current_version(conn)
        done = {record["version"]: record for record in _status_records(conn)}
        return {
            "current_version": current,
            "latest_version": MIGRATIONS[-1].version if MIGRATIONS else 0,
            "pending": [
                {"version": m.version, "name": m.name}
                for m in MIGRATIONS
                if m.version > current
            ],
            "applied": sorted(done.values(), key=lambda item: item["version"]),
        }


def _status_records(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
    ).fetchall()
    return [{"version": int(row[0]), "name": row[1], "applied_at": row[2]} for row in rows]
