from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA foreign_keys = ON;

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
                """
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
