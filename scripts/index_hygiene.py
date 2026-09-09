"""Index hygiene: reconcile SQLite chunks, Chroma vectors, and job states.

What it does (in order):
1. Backs up data/runtime/app.db and data/chroma (unless --no-backup).
2. Deletes chunks belonging to superseded document versions (stale chunks that
   pollute FTS/vector retrieval).
3. Marks permanently running/queued jobs older than --stuck-hours as failed.
4. Deletes Chroma vectors whose chunk ids no longer exist in SQLite, then prunes
   the empty `chunks_test` collection and orphaned HNSW segment directories.
5. VACUUMs the SQLite database.

Run with --dry-run first to preview every action.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data/runtime/app.db"
CHROMA_DIR = ROOT / "data/chroma"
BACKUP_DIR = ROOT / "data/backups"


def backup(db_path: Path, chroma_dir: Path, backup_dir: Path) -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        target = backup_dir / f"app-{stamp}.db"
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(target)
        with dst:
            dst.executescript("PRAGMA journal_mode=WAL;")
            src.backup(dst)
        src.close()
        dst.close()
        print(f"backup db -> {target}")
    if chroma_dir.exists():
        target = backup_dir / f"chroma-{stamp}"
        shutil.copytree(chroma_dir, target, ignore=shutil.ignore_patterns("*.lock"))
        print(f"backup chroma -> {target}")


def delete_stale_chunks(conn: sqlite3.Connection, dry_run: bool) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) FROM chunks c
        LEFT JOIN document_versions v ON c.version_id = v.id
        LEFT JOIN documents d ON v.document_id = d.id
        WHERE v.id IS NULL OR d.id IS NULL OR v.id <> d.current_version_id
        """
    ).fetchone()
    stale = row[0]
    print(f"stale chunks (not in current versions): {stale}")
    if stale and not dry_run:
        conn.execute(
            """
            DELETE FROM chunks WHERE rowid IN (
                SELECT c.rowid FROM chunks c
                LEFT JOIN document_versions v ON c.version_id = v.id
                LEFT JOIN documents d ON v.document_id = d.id
                WHERE v.id IS NULL OR d.id IS NULL OR v.id <> d.current_version_id
            )
            """
        )
    return stale


def fail_stuck_jobs(conn: sqlite3.Connection, stuck_hours: float, dry_run: bool) -> int:
    now = datetime.now(timezone.utc).timestamp()
    rows = conn.execute(
        "SELECT id, job_type, status, created_at FROM jobs WHERE status IN ('running','queued')"
    ).fetchall()
    stuck = []
    for r in rows:
        try:
            created = datetime.fromisoformat(r["created_at"]).timestamp()
        except (ValueError, TypeError):
            continue
        if now - created > stuck_hours * 3600:
            stuck.append(r)
    for r in stuck:
        print(f"stuck job {r['id'][:8]} type={r['job_type']} status={r['status']} since {r['created_at']} -> failed")
        if not dry_run:
            conn.execute(
                "UPDATE jobs SET status='failed', message='reclaimed by index_hygiene (stuck)', updated_at=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), r["id"]),
            )
    return len(stuck)


def vacuum(conn: sqlite3.Connection, dry_run: bool) -> None:
    if dry_run:
        return
    conn.execute("VACUUM")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def clean_chroma(chroma_dir: Path, dry_run: bool) -> None:
    try:
        import chromadb
    except ImportError:
        print("chromadb not importable; skipping vector cleanup")
        return

    client = chromadb.PersistentClient(path=str(chroma_dir))
    names = [c.name for c in client.list_collections()]
    print("collections:", names)

    con = sqlite3.connect(f"file:{chroma_dir / 'chroma.sqlite3'}?mode=ro", uri=True)
    try:
        # The external (chunk) id lives in embedding_metadata under 'chunk_id'.
        rows = con.execute(
            """
            SELECT em.string_value FROM embedding_metadata em
            JOIN embeddings e ON em.id = e.id
            WHERE em.key = 'chunk_id'
            """
        ).fetchall()
        valid_chunk_ids = {r[0] for r in rows}
    finally:
        con.close()

    live = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        db_chunk_ids = {r[0] for r in live.execute("SELECT id FROM chunks")}
    finally:
        live.close()

    orphans = valid_chunk_ids - db_chunk_ids
    print(f"chroma embeddings: {len(valid_chunk_ids)}, sqlite chunks: {len(db_chunk_ids)}, orphan vectors: {len(orphans)}")
    if orphans and "chunks" in names and not dry_run:
        col = client.get_collection("chunks")
        id_list = list(orphans)
        for start in range(0, len(id_list), 500):
            col.delete(ids=id_list[start : start + 500])
        print(f"deleted {len(orphans)} orphan vectors from 'chunks'")

    if "chunks_test" in names:
        print("dropping unused collection 'chunks_test'")
        if not dry_run:
            client.delete_collection("chunks_test")


def prune_orphan_segments(chroma_dir: Path, dry_run: bool) -> None:
    meta = sqlite3.connect(f"file:{chroma_dir / 'chroma.sqlite3'}?mode=ro", uri=True)
    try:
        referenced = {r[0] for r in meta.execute("SELECT id FROM segments")}
    finally:
        meta.close()
    for entry in chroma_dir.iterdir():
        if entry.is_dir() and entry.name not in referenced:
            size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
            print(f"orphan segment dir {entry.name} ({size/1024/1024:.1f} MB)")
            if not dry_run:
                shutil.rmtree(entry)


def report(conn: sqlite3.Connection) -> None:
    total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    current = conn.execute(
        """
        SELECT COUNT(*) FROM chunks c
        JOIN document_versions v ON c.version_id = v.id
        JOIN documents d ON v.document_id = d.id
        WHERE v.id = d.current_version_id
        """
    ).fetchone()[0]
    jobs = conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall()
    print(f"chunks total={total} current={current}")
    print("jobs:", {r[0]: r[1] for r in jobs})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="preview actions without writing")
    ap.add_argument("--no-backup", action="store_true", help="skip the DB/Chroma backup step")
    ap.add_argument("--stuck-hours", type=float, default=24.0, help="jobs older than this are failed (default 24)")
    ap.add_argument("--skip-chroma", action="store_true", help="only touch SQLite")
    args = ap.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"database not found: {DB_PATH}")

    if not args.no_backup and not args.dry_run:
        backup(DB_PATH, CHROMA_DIR, BACKUP_DIR)
    elif args.dry_run:
        print("(dry-run: backup skipped)")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        print("== before ==")
        report(conn)
        stale = delete_stale_chunks(conn, args.dry_run)
        stuck = fail_stuck_jobs(conn, args.stuck_hours, args.dry_run)
        if not args.dry_run:
            conn.commit()
        if not args.skip_chroma:
            clean_chroma(CHROMA_DIR, args.dry_run)
            prune_orphan_segments(CHROMA_DIR, args.dry_run)
        print("== vacuum ==")
        vacuum(conn, args.dry_run)
        print("== after ==")
        report(conn)
        print(f"(dry_run={args.dry_run}, stale_deleted={stale if not args.dry_run else 0}, stuck_failed={stuck if not args.dry_run else 0})")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
