#!/usr/bin/env python3
"""Check SQLite, FTS5, Chroma, and uploaded-source consistency.

Exit status is suitable for CI/cron: 0 means all checked invariants hold; 1
means at least one mismatch or missing required asset was found. The command is
read-only and never repairs or deletes data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _db_check(db_path: Path, upload_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": True, "checks": [], "counts": {}}
    if not db_path.exists():
        return {"ok": False, "checks": [{"name": "database_exists", "ok": False, "detail": str(db_path)}], "counts": {}}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        ok = integrity.lower() == "ok"
        result["ok"] &= ok
        result["checks"].append({"name": "sqlite_integrity", "ok": ok, "detail": integrity})
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        ok = not fk
        result["ok"] &= ok
        result["checks"].append({"name": "foreign_keys", "ok": ok, "violations": len(fk)})
        for table in ("documents", "document_versions", "chunks", "chunks_fts", "messages", "jobs", "answer_runs"):
            try:
                result["counts"][table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            except sqlite3.Error as exc:
                result["ok"] = False
                result["checks"].append({"name": f"table_{table}", "ok": False, "detail": str(exc)})
        chunks = result["counts"].get("chunks", 0)
        fts = result["counts"].get("chunks_fts", 0)
        ok = chunks == fts
        result["ok"] &= ok
        result["checks"].append({"name": "fts_chunk_count", "ok": ok, "chunks": chunks, "fts": fts})
        rows = conn.execute(
            """
            SELECT v.id, v.stored_path, v.sha256, v.parser_status, v.index_status,
                   d.current_version_id
            FROM document_versions v JOIN documents d ON d.id = v.document_id
            WHERE d.current_version_id = v.id
            """
        ).fetchall()
        missing: list[str] = []
        changed: list[str] = []
        for row in rows:
            source = Path(row["stored_path"]) if row["stored_path"] else None
            if source is None or not source.exists():
                missing.append(row["id"])
                continue
            if row["sha256"] and _sha256(source) != row["sha256"]:
                changed.append(row["id"])
        ok = not missing and not changed
        result["ok"] &= ok
        result["checks"].append({"name": "current_source_hashes", "ok": ok, "missing": missing, "changed": changed})
        orphan_chunks = conn.execute(
            """
            SELECT COUNT(*) FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE d.current_version_id != c.version_id
            """
        ).fetchone()[0]
        ok = int(orphan_chunks) == 0
        result["ok"] &= ok
        result["checks"].append({"name": "current_version_chunks", "ok": ok, "orphan_chunks": int(orphan_chunks)})
        active_without_version = conn.execute(
            """
            SELECT COUNT(*) FROM jobs j
            WHERE j.status IN ('queued','running')
              AND json_extract(j.payload_json, '$.version_id') IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM document_versions v
                WHERE v.id = json_extract(j.payload_json, '$.version_id')
              )
            """
        ).fetchone()[0]
        ok = int(active_without_version) == 0
        result["ok"] &= ok
        result["checks"].append({"name": "active_job_versions", "ok": ok, "missing_versions": int(active_without_version)})
    finally:
        conn.close()
    return result


def _chroma_check(chroma_dir: Path, sqlite_chunk_count: int | None) -> dict[str, Any]:
    if not chroma_dir.exists():
        return {"ok": False, "checks": [{"name": "chroma_exists", "ok": False, "detail": str(chroma_dir)}]}
    try:
        import chromadb  # type: ignore[import-untyped]
    except ImportError:
        return {"ok": False, "checks": [{"name": "chroma_import", "ok": False, "detail": "chromadb is not installed"}]}
    try:
        client = chromadb.PersistentClient(path=str(chroma_dir))
        collection = client.get_or_create_collection("chunks")
        count = int(collection.count())
        # Exact count is the default invariant. A deployment can set
        # CHROMA_COUNT_CHECK=skip only for a planned partial-reindex window.
        ok = sqlite_chunk_count is None or count == sqlite_chunk_count
        return {"ok": ok, "checks": [{"name": "chroma_chunk_count", "ok": ok, "chroma": count, "sqlite": sqlite_chunk_count}]}
    except Exception as exc:  # noqa: BLE001 - diagnostic boundary
        return {"ok": False, "checks": [{"name": "chroma_open", "ok": False, "detail": str(exc)}]}


def check(db_path: Path, chroma_dir: Path, upload_dir: Path) -> dict[str, Any]:
    db_result = _db_check(db_path, upload_dir)
    sqlite_count = db_result.get("counts", {}).get("chunks")
    chroma_result = _chroma_check(chroma_dir, sqlite_count)
    checks = db_result.get("checks", []) + chroma_result.get("checks", [])
    return {
        "ok": bool(db_result.get("ok") and chroma_result.get("ok")),
        "database": db_result,
        "chroma": chroma_result,
        "checks": checks,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only runtime consistency check")
    ap.add_argument("--db", type=Path, default=ROOT / "data/runtime/app.db")
    ap.add_argument("--chroma", type=Path, default=ROOT / "data/chroma")
    ap.add_argument("--uploads", type=Path, default=ROOT / "data/uploads")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = check(args.db, args.chroma, args.uploads)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for item in report["checks"]:
            print(f"[{ 'ok' if item.get('ok') else 'FAIL' }] {item['name']}")
        print(f"overall: {'ok' if report['ok'] else 'FAIL'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
