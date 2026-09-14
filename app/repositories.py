from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from app.db import Database
from app.domain import AnswerRunRecord, ChunkRecord, RetrievalHit


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonicalize_name(filename: str) -> str:
    stem = Path(filename).stem.strip().lower()
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "-", stem).strip("-") or uuid4().hex


class Repository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create_or_get_document(self, title: str, filename: str, source_type: str, trust_level: str) -> dict[str, Any]:
        canonical_name = canonicalize_name(filename)
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE canonical_name = ?", (canonical_name,)).fetchone()
            now = utc_now()
            if row:
                conn.execute(
                    """
                    UPDATE documents
                    SET title = ?, source_type = ?, trust_level = ?, updated_at = ?, disabled_at = NULL
                    WHERE id = ?
                    """,
                    (title, source_type, trust_level, now, row["id"]),
                )
                row = conn.execute("SELECT * FROM documents WHERE id = ?", (row["id"],)).fetchone()
                return dict(row)

            document_id = uuid4().hex
            conn.execute(
                """
                INSERT INTO documents (id, title, canonical_name, source_type, trust_level, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (document_id, title, canonical_name, source_type, trust_level, now, now),
            )
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
            return dict(row)

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
            return dict(row) if row else None

    def list_documents(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    d.id AS document_id,
                    d.title,
                    d.source_type,
                    d.trust_level,
                    d.current_version_id AS current_version,
                    v.original_filename,
                    v.parser_status,
                    v.index_status,
                    COALESCE(v.chunk_count, 0) AS chunk_count,
                    d.created_at,
                    d.updated_at,
                    d.disabled_at
                FROM documents d
                LEFT JOIN document_versions v ON v.id = d.current_version_id
                ORDER BY d.updated_at DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def create_document_version(
        self,
        document_id: str,
        original_filename: str,
        stored_path: str,
        file_size: int,
        sha256: str,
    ) -> dict[str, Any]:
        with self.db.connect() as conn:
            next_version = conn.execute(
                "SELECT COALESCE(MAX(version_number), 0) + 1 FROM document_versions WHERE document_id = ?",
                (document_id,),
            ).fetchone()[0]
            version_id = uuid4().hex
            now = utc_now()
            conn.execute(
                """
                INSERT INTO document_versions (
                    id, document_id, version_number, original_filename, stored_path, file_size, sha256,
                    parser_status, index_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 'queued', ?, ?)
                """,
                (version_id, document_id, next_version, original_filename, stored_path, file_size, sha256, now, now),
            )
            conn.execute(
                "UPDATE documents SET current_version_id = ?, updated_at = ?, disabled_at = NULL WHERE id = ?",
                (version_id, now, document_id),
            )
            row = conn.execute("SELECT * FROM document_versions WHERE id = ?", (version_id,)).fetchone()
            return dict(row)

    def update_version_storage_path(self, version_id: str, stored_path: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE document_versions SET stored_path = ?, updated_at = ? WHERE id = ?",
                (stored_path, utc_now(), version_id),
            )

    def get_version(self, version_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT v.*, d.title, d.source_type, d.trust_level, d.id AS document_id
                FROM document_versions v
                JOIN documents d ON d.id = v.document_id
                WHERE v.id = ?
                """,
                (version_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_current_version_by_stored_path(self, document_id: str, stored_path: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT v.*, d.title, d.source_type, d.trust_level, d.id AS document_id
                FROM documents d
                JOIN document_versions v ON v.id = d.current_version_id
                WHERE d.id = ? AND v.stored_path = ?
                """,
                (document_id, stored_path),
            ).fetchone()
            return dict(row) if row else None

    def get_version_by_stored_path(self, document_id: str, stored_path: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT v.*, d.title, d.source_type, d.trust_level, d.id AS document_id
                FROM document_versions v
                JOIN documents d ON d.id = v.document_id
                WHERE v.document_id = ? AND v.stored_path = ?
                ORDER BY v.version_number DESC
                LIMIT 1
                """,
                (document_id, stored_path),
            ).fetchone()
            return dict(row) if row else None

    def set_current_version(self, document_id: str, version_id: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE documents SET current_version_id = ?, updated_at = ?, disabled_at = NULL WHERE id = ?",
                (version_id, utc_now(), document_id),
            )

    def list_ragflow_duplicate_versions(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    d.id AS document_id,
                    d.title,
                    d.current_version_id,
                    v.id AS version_id,
                    v.version_number,
                    v.stored_path,
                    v.parser_name,
                    v.chunk_count,
                    v.created_at
                FROM document_versions v
                JOIN documents d ON d.id = v.document_id
                WHERE v.parser_name = 'ragflow_import'
                ORDER BY d.title ASC, v.stored_path ASC, v.version_number DESC
                """
            ).fetchall()
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            item = dict(row)
            key = (item["document_id"], item["stored_path"])
            grouped.setdefault(key, []).append(item)
        duplicates: list[dict[str, Any]] = []
        for versions in grouped.values():
            if len(versions) <= 1:
                continue
            keep = versions[0]
            for stale in versions[1:]:
                duplicates.append(
                    {
                        "document_id": stale["document_id"],
                        "title": stale["title"],
                        "stored_path": stale["stored_path"],
                        "keep_version_id": keep["version_id"],
                        "keep_version_number": keep["version_number"],
                        "stale_version_id": stale["version_id"],
                        "stale_version_number": stale["version_number"],
                        "current_version_id": stale["current_version_id"],
                    }
                )
        return duplicates

    def delete_document_version(self, version_id: str) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM document_versions WHERE id = ?", (version_id,))

    def get_current_versions(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT v.*, d.title, d.source_type, d.trust_level, d.id AS document_id
                FROM documents d
                JOIN document_versions v ON v.id = d.current_version_id
                WHERE d.disabled_at IS NULL
                ORDER BY d.updated_at DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def update_version_status(
        self,
        version_id: str,
        *,
        parser_status: str | None = None,
        index_status: str | None = None,
        parser_name: str | None = None,
        ocr_used: bool | None = None,
        warning_text: str | None = None,
        chunk_count: int | None = None,
    ) -> None:
        assignments: list[str] = ["updated_at = ?"]
        values: list[Any] = [utc_now()]
        if parser_status is not None:
            assignments.append("parser_status = ?")
            values.append(parser_status)
        if index_status is not None:
            assignments.append("index_status = ?")
            values.append(index_status)
        if parser_name is not None:
            assignments.append("parser_name = ?")
            values.append(parser_name)
        if ocr_used is not None:
            assignments.append("ocr_used = ?")
            values.append(1 if ocr_used else 0)
        if warning_text is not None:
            assignments.append("warning_text = ?")
            values.append(warning_text)
        if chunk_count is not None:
            assignments.append("chunk_count = ?")
            values.append(chunk_count)
        values.append(version_id)
        with self.db.connect() as conn:
            conn.execute(
                f"UPDATE document_versions SET {', '.join(assignments)} WHERE id = ?",
                tuple(values),
            )

    def replace_chunks(self, version_id: str, chunks: Iterable[ChunkRecord]) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM chunks WHERE version_id = ?", (version_id,))
            conn.executemany(
                """
                INSERT INTO chunks (
                    id, document_id, version_id, file_name, source_type, trust_level, page_or_slide,
                    section_path, chunk_index, chunk_hash, markdown_text, plain_text, search_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.version_id,
                        chunk.file_name,
                        chunk.source_type,
                        chunk.trust_level,
                        chunk.page_or_slide,
                        chunk.section_path,
                        chunk.chunk_index,
                        chunk.chunk_hash,
                        chunk.markdown_text,
                        chunk.plain_text,
                        chunk.search_text,
                    )
                    for chunk in chunks
                ],
            )

    def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[dict[str, Any]]:
        if not chunk_ids:
            return []
        placeholders = ",".join("?" for _ in chunk_ids)
        with self.db.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT c.*, d.current_version_id, d.disabled_at
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.id IN ({placeholders})
                """,
                tuple(chunk_ids),
            ).fetchall()
            mapping = {row["id"]: dict(row) for row in rows}
            return [mapping[chunk_id] for chunk_id in chunk_ids if chunk_id in mapping]

    def keyword_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.*,
                    bm25(chunks_fts) AS bm25_score
                FROM chunks_fts
                JOIN chunks c ON c.rowid = chunks_fts.rowid
                JOIN documents d ON d.id = c.document_id
                WHERE chunks_fts MATCH ? AND d.current_version_id = c.version_id AND d.disabled_at IS NULL
                ORDER BY bm25_score
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def disable_document(self, document_id: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE documents SET disabled_at = ?, updated_at = ? WHERE id = ?",
                (utc_now(), utc_now(), document_id),
            )

    def list_queued_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = 'queued' AND cancelled_at IS NULL ORDER BY created_at LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._job_dict(row) for row in rows]

    @staticmethod
    def _job_dict(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        item["result"] = json.loads(item.pop("result_json") or "{}")
        return item

    def job_is_cancelled(self, job_id: str) -> bool:
        with self.db.connect() as conn:
            row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return row is None or row["status"] == "cancelled"

    def requeue_job(self, job_id: str, *, message: str, not_before_seconds: float = 0.0) -> None:
        # not_before is recorded in the message for the current SQLite worker;
        # a future queue backend can promote it to a dedicated column.
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'queued', owner = NULL, heartbeat_at = NULL, message = ?, updated_at = ? WHERE id = ?",
                (message, utc_now(), job_id),
            )

    def create_job(self, job_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        job_id = uuid4().hex
        now = utc_now()
        payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        with self.db.connect() as conn:
            # Idempotency: a new queue request for the same (job_type, payload)
            # supersedes any still-active duplicate instead of stacking two
            # jobs that would process the same target twice.
            conn.execute(
                """
                UPDATE jobs
                SET status = 'cancelled', message = 'superseded by a newer identical job', cancelled_at = ?, updated_at = ?
                WHERE job_type = ? AND payload_json = ? AND status IN ('queued', 'running')
                """,
                (now, now, job_type, payload_json),
            )
            conn.execute(
                """
                INSERT INTO jobs (id, job_type, status, payload_json, created_at, updated_at, attempt, max_attempts)
                VALUES (?, ?, 'queued', ?, ?, ?, 0, 3)
                """,
                (job_id, job_type, payload_json, now, now),
            )
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return self._job_dict(row)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                return None
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            item["result"] = json.loads(item.pop("result_json") or "{}")
            return item

    def claim_job(self, job_id: str, *, owner: str, max_attempts: int | None = None) -> dict[str, Any] | None:
        """Atomically take ownership of a job for execution.

        Claimable when queued, or when running with a stale lease and attempts
        left (crash recovery). Returns None if the job is missing, terminal,
        cancelled, still freshly owned, or out of attempts.
        """
        now = utc_now()
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                return None
            job = dict(row)
            attempts_cap = max_attempts if max_attempts is not None else int(job.get("max_attempts") or 3)
            if job["attempt"] >= attempts_cap:
                return None
            stale_before = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            result = conn.execute(
                """
                UPDATE jobs
                SET status = 'running', attempt = attempt + 1, owner = ?, heartbeat_at = ?,
                    max_attempts = ?, message = NULL, updated_at = ?
                WHERE id = ?
                  AND (
                        (status = 'queued' AND cancelled_at IS NULL)
                        OR (status = 'running' AND cancelled_at IS NULL
                            AND COALESCE(heartbeat_at, updated_at) < ?)
                  )
                """,
                (owner, now, attempts_cap, now, job_id, stale_before),
            )
            if result.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return self._job_dict(row)

    def heartbeat_job(self, job_id: str, *, owner: str) -> bool:
        with self.db.connect() as conn:
            result = conn.execute(
                "UPDATE jobs SET heartbeat_at = ?, updated_at = ? WHERE id = ? AND owner = ? AND status = 'running'",
                (utc_now(), utc_now(), job_id, owner),
            )
            return result.rowcount > 0

    def complete_job(
        self,
        job_id: str,
        *,
        owner: str,
        message: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        self._finish_owned_job(job_id, owner=owner, status="completed", message=message, result=result)

    def fail_job(self, job_id: str, *, owner: str, message: str | None = None) -> None:
        self._finish_owned_job(job_id, owner=owner, status="failed", message=message, result=None)

    def _finish_owned_job(
        self,
        job_id: str,
        *,
        owner: str,
        status: str,
        message: str | None,
        result: dict[str, Any] | None,
    ) -> None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT owner FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise RuntimeError(f"job {job_id} not found")
            if (row["owner"] or "") != owner:
                raise RuntimeError(f"job {job_id} is owned by {row['owner']!r}, not {owner!r}")
            conn.execute(
                "UPDATE jobs SET status = ?, message = ?, result_json = ?, heartbeat_at = ?, updated_at = ? WHERE id = ?",
                (status, message, json.dumps(result or {}, ensure_ascii=False), utc_now(), utc_now(), job_id),
            )

    def cancel_job(self, job_id: str) -> bool:
        """Request cancellation of an active job; workers see it via claim_job."""
        now = utc_now()
        with self.db.connect() as conn:
            result = conn.execute(
                "UPDATE jobs SET status = 'cancelled', cancelled_at = ?, updated_at = ? WHERE id = ? AND status IN ('queued', 'running')",
                (now, now, job_id),
            )
            return result.rowcount > 0

    def latest_active_job(self, job_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM jobs
                WHERE job_type = ? AND payload_json = ? AND status IN ('queued', 'running')
                ORDER BY created_at DESC LIMIT 1
                """,
                (job_type, payload_json),
            ).fetchone()
            return dict(row) if row else None

    def reclaim_stale_jobs(self, *, stale_after_seconds: int = 3600) -> list[str]:
        """Recover jobs whose worker died mid-run (running with stale heartbeat).

        With attempts left they go back to 'queued' (owner cleared) for the next
        claimer; exhausted jobs are moved to 'failed' (dead-letter). Returns the
        ids of jobs marked failed.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)).isoformat()
        now = utc_now()
        failed_ids: list[str] = []
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, attempt, max_attempts FROM jobs
                WHERE status = 'running' AND COALESCE(heartbeat_at, updated_at) < ?
                """,
                (cutoff,),
            ).fetchall()
            for row in rows:
                if int(row["attempt"]) >= int(row["max_attempts"] or 3):
                    conn.execute(
                        "UPDATE jobs SET status = 'failed', message = 'attempts exhausted after lost lease', updated_at = ? WHERE id = ?",
                        (now, row["id"]),
                    )
                    failed_ids.append(row["id"])
                else:
                    conn.execute(
                        "UPDATE jobs SET status = 'queued', owner = NULL, message = 'requeued after lost lease', updated_at = ? WHERE id = ?",
                        (now, row["id"]),
                    )
        return failed_ids

    def fail_stale_queued_jobs(self, *, stale_after_seconds: int = 24 * 3600) -> list[str]:
        """Mark queued jobs that were never picked up (e.g. process died before
        BackgroundTasks ran them) as failed, so backlog metrics stay honest."""
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)).isoformat()
        now = utc_now()
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM jobs WHERE status = 'queued' AND updated_at < ?",
                (cutoff,),
            ).fetchall()
            ids = [row["id"] for row in rows]
            for job_id in ids:
                conn.execute(
                    "UPDATE jobs SET status = 'failed', message = 'never picked up (stale queued)', updated_at = ? WHERE id = ?",
                    (now, job_id),
                )
        return ids

    def job_backlog_stats(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with self.db.connect() as conn:
            counts = dict(
                conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall()
            )
            by_type_rows = conn.execute(
                "SELECT job_type, status, COUNT(*) AS n FROM jobs GROUP BY job_type, status"
            ).fetchall()
            oldest = conn.execute(
                "SELECT MIN(created_at) FROM jobs WHERE status = 'queued'"
            ).fetchone()[0]
        by_type: dict[str, dict[str, int]] = {}
        for row in by_type_rows:
            stats = by_type.setdefault(row["job_type"], {})
            stats[row["status"]] = int(row["n"])
        oldest_age = None
        if oldest:
            try:
                oldest_age = max(0, int((now - datetime.fromisoformat(oldest)).total_seconds()))
            except ValueError:
                oldest_age = None
        return {
            "queued": int(counts.get("queued", 0)),
            "running": int(counts.get("running", 0)),
            "completed": int(counts.get("completed", 0)),
            "failed": int(counts.get("failed", 0)),
            "cancelled": int(counts.get("cancelled", 0)),
            "by_type": by_type,
            "oldest_queued_age_seconds": oldest_age,
        }

    def update_job(
        self,
        job_id: str,
        *,
        status: str,
        message: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, message = ?, result_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, message, json.dumps(result or {}, ensure_ascii=False), utc_now(), job_id),
            )

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            payload = []
            for row in rows:
                item = dict(row)
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
                item["result"] = json.loads(item.pop("result_json") or "{}")
                payload.append(item)
            return payload

    def latest_job(self, *, job_type: str, status: str | None = None) -> dict[str, Any] | None:
        query = "SELECT * FROM jobs WHERE job_type = ?"
        params: list[Any] = [job_type]
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC LIMIT 1"
        with self.db.connect() as conn:
            row = conn.execute(query, tuple(params)).fetchone()
            if not row:
                return None
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            item["result"] = json.loads(item.pop("result_json") or "{}")
            return item

    def ensure_conversation(self, conversation_id: str | None = None) -> str:
        if conversation_id:
            with self.db.connect() as conn:
                row = conn.execute("SELECT id FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
                if row:
                    conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (utc_now(), conversation_id))
                    return conversation_id

        new_id = uuid4().hex
        now = utc_now()
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO conversations (id, created_at, updated_at) VALUES (?, ?, ?)",
                (new_id, now, now),
            )
        return new_id

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        grounded: bool | None = None,
        citations: list[dict[str, Any]] | None = None,
    ) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO messages (id, conversation_id, role, content, grounded, citations_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    conversation_id,
                    role,
                    content,
                    None if grounded is None else int(grounded),
                    json.dumps(citations or [], ensure_ascii=False),
                    utc_now(),
                ),
            )
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (utc_now(), conversation_id))

    def get_recent_user_questions(self, conversation_id: str, limit: int) -> list[str]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT content
                FROM messages
                WHERE conversation_id = ? AND role = 'user'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (conversation_id, limit),
            ).fetchall()
            return [row["content"] for row in reversed(rows)]

    def get_recent_turn_context(self, conversation_id: str, turns: int) -> list[dict[str, Any]]:
        message_limit = max(1, turns) * 2
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content, grounded, citations_json, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (conversation_id, message_limit),
            ).fetchall()
            result = []
            for row in reversed(rows):
                payload = dict(row)
                payload["citations"] = json.loads(payload.pop("citations_json") or "[]")
                payload["grounded"] = None if payload["grounded"] is None else bool(payload["grounded"])
                result.append(payload)
            return result

    def get_conversation_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content, grounded, citations_json, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC
                """,
                (conversation_id,),
            ).fetchall()
            result = []
            for row in rows:
                payload = dict(row)
                payload["citations"] = json.loads(payload.pop("citations_json") or "[]")
                payload["grounded"] = None if payload["grounded"] is None else bool(payload["grounded"])
                result.append(payload)
            return result

    def create_answer_run(
        self,
        *,
        conversation_id: str,
        question: str,
        rewritten_query: str,
        question_type: str,
        answer_focus: str,
        retrieval: dict[str, Any],
        draft: dict[str, Any],
        review: dict[str, Any],
        final_answer: str,
        final_grounded_answer: str,
        final_inference_note: str,
        final_grounded: bool,
        stage_status: str,
        failure_stage: str | None,
        latency_total_ms: int,
        latency_retrieval_ms: int,
        latency_generate_ms: int,
        latency_review_ms: int,
    ) -> str:
        answer_run_id = uuid4().hex
        created_at = utc_now()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO answer_runs (
                    id, conversation_id, question, rewritten_query, question_type, answer_focus,
                    retrieval_json, draft_json, review_json, final_answer, final_grounded_answer,
                    final_inference_note, final_grounded, stage_status, failure_stage,
                    latency_total_ms, latency_retrieval_ms, latency_generate_ms, latency_review_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    answer_run_id,
                    conversation_id,
                    question,
                    rewritten_query,
                    question_type,
                    answer_focus,
                    json.dumps(retrieval, ensure_ascii=False),
                    json.dumps(draft, ensure_ascii=False),
                    json.dumps(review, ensure_ascii=False),
                    final_answer,
                    final_grounded_answer,
                    final_inference_note,
                    int(final_grounded),
                    stage_status,
                    failure_stage,
                    latency_total_ms,
                    latency_retrieval_ms,
                    latency_generate_ms,
                    latency_review_ms,
                    created_at,
                ),
            )
        return answer_run_id

    def get_answer_run(self, answer_run_id: str) -> AnswerRunRecord | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM answer_runs WHERE id = ?", (answer_run_id,)).fetchone()
            if not row:
                return None
            return self._row_to_answer_run(row)

    def list_answer_runs(self, limit: int = 20) -> list[AnswerRunRecord]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM answer_runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._row_to_answer_run(row) for row in rows]

    def _row_to_answer_run(self, row: Any) -> AnswerRunRecord:
        payload = dict(row)
        return AnswerRunRecord(
            answer_run_id=payload["id"],
            conversation_id=payload["conversation_id"],
            question=payload["question"],
            rewritten_query=payload["rewritten_query"],
            question_type=payload["question_type"],
            answer_focus=payload["answer_focus"],
            retrieval=json.loads(payload["retrieval_json"] or "{}"),
            draft=json.loads(payload["draft_json"] or "{}"),
            review=json.loads(payload["review_json"] or "{}"),
            final_answer=payload["final_answer"],
            final_grounded_answer=payload["final_grounded_answer"],
            final_inference_note=payload["final_inference_note"],
            final_grounded=bool(payload["final_grounded"]),
            stage_status=payload["stage_status"],
            failure_stage=payload["failure_stage"],
            latency_total_ms=int(payload["latency_total_ms"]),
            latency_retrieval_ms=int(payload["latency_retrieval_ms"]),
            latency_generate_ms=int(payload["latency_generate_ms"]),
            latency_review_ms=int(payload["latency_review_ms"]),
            created_at=payload["created_at"],
        )

    @staticmethod
    def serialize_hit(hit: RetrievalHit) -> dict[str, Any]:
        payload = asdict(hit)
        return payload
