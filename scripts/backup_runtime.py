#!/usr/bin/env python3
"""Backup runtime assets to a manifest-stamped directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data/runtime/app.db"
CHROMA_DIR = ROOT / "data/chroma"
UPLOAD_DIR = ROOT / "data/uploads"
BACKUP_DIR = ROOT / "data/backups"


def _sha256(path: Path, block_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(block_size)
            if not chunk:
                break
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def _sqlite_counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    out: dict[str, int] = {}
    try:
        for row in conn.execute("SELECT COUNT(*) AS n FROM documents"):
            out["documents"] = int(row["n"])
        for row in conn.execute("SELECT COUNT(*) AS n FROM document_versions"):
            out["document_versions"] = int(row["n"])
        for row in conn.execute("SELECT COUNT(*) AS n FROM chunks"):
            out["chunks"] = int(row["n"])
        for row in conn.execute("SELECT COUNT(*) AS n FROM jobs"):
            out["jobs"] = int(row["n"])
        for row in conn.execute("SELECT COUNT(*) AS n FROM messages"):
            out["messages"] = int(row["n"])
        for row in conn.execute("PRAGMA user_version"):
            out["schema_version"] = int(row[0])
    finally:
        conn.close()
    return out


def _chroma_count(chroma_dir: Path) -> int:
    try:
        import chromadb  # type: ignore[import-untyped]
    except ImportError:
        return -1
    client = chromadb.PersistentClient(path=str(chroma_dir))
    try:
        return client.get_or_create_collection("chunks").count()
    except Exception:
        return -1


def _copy_db(src: Path, dst: Path) -> None:
    src_conn = sqlite3.connect(src)
    dst_conn = sqlite3.connect(dst)
    with dst_conn:
        dst_conn.executescript("PRAGMA journal_mode=WAL;")
        src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()


def backup(backup_dir: Path, dry_run: bool = False) -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"backup-{stamp}"
    manifest: dict[str, Any] = {
        "timestamp_utc": stamp,
        "commit": _current_git_sha(),
        "paths": {},
        "counts": {},
        "chroma_count": -1,
        "artifacts": {},
    }
    if dry_run:
        print(f"[dry-run] would backup to {target}")
        return manifest
    target.mkdir(parents=True, exist_ok=False)
    try:
        if DB_PATH.exists():
            dst_db = target / "app.db"
            _copy_db(DB_PATH, dst_db)
            manifest["paths"]["database"] = str(dst_db.relative_to(ROOT))
            manifest["artifacts"]["app.db"] = {"path": str(dst_db), "sha256": _sha256(dst_db)}
            manifest["counts"] = _sqlite_counts(DB_PATH)
        if CHROMA_DIR.exists():
            dst_chroma = target / "chroma"
            shutil.copytree(CHROMA_DIR, dst_chroma)
            manifest["paths"]["chroma"] = str(dst_chroma.relative_to(ROOT))
            manifest["chroma_count"] = _chroma_count(dst_chroma)
            manifest["artifacts"]["chroma"] = {"path": str(dst_chroma)}
        if UPLOAD_DIR.exists():
            dst_uploads = target / "uploads"
            shutil.copytree(UPLOAD_DIR, dst_uploads)
            manifest["paths"]["uploads"] = str(dst_uploads.relative_to(ROOT))
            manifest["artifacts"]["uploads"] = {"path": str(dst_uploads)}
        manifest_path = target / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"backup -> {target}\nmanifest -> {manifest_path}")
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return manifest


def _current_git_sha() -> str | None:
    try:
        import subprocess  # noqa: F401
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Backup runtime assets with manifest")
    ap.add_argument("--backup-dir", type=Path, default=BACKUP_DIR, help="Directory to store backups")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    try:
        backup(backup_dir=args.backup_dir, dry_run=args.dry_run)
    except Exception as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
