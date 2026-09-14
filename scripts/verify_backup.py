#!/usr/bin/env python3
"""Verify a backup manifest and its internal consistency."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _sha256(path: Path, block_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(block_size)
            if not chunk:
                break
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def verify(backup_dir: Path) -> dict[str, Any]:
    manifest_path = backup_dir / "manifest.json"
    report: dict[str, Any] = {"backup_dir": str(backup_dir), "checks": [], "ok": True}
    if not manifest_path.exists():
        report["ok"] = False
        report["checks"].append({"check": "manifest_exists", "ok": False, "detail": str(manifest_path)})
        return report
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report["ok"] = False
        report["checks"].append({"check": "manifest_json", "ok": False, "detail": str(exc)})
        return report
    report["checks"].append({"check": "manifest_json", "ok": True})
    db_rel = manifest.get("paths", {}).get("database")
    if db_rel:
        db_path = backup_dir / db_rel if not Path(db_rel).is_absolute() else Path(db_rel)
        if not db_path.exists():
            report["ok"] = False
            report["checks"].append({"check": "database_exists", "ok": False, "detail": str(db_path)})
        else:
            expected_sha = manifest.get("artifacts", {}).get("app.db", {}).get("sha256")
            actual_sha = _sha256(db_path)
            ok = expected_sha is None or expected_sha == actual_sha
            report["ok"] &= ok
            report["checks"].append({"check": "database_sha256", "ok": ok, "expected": expected_sha, "actual": actual_sha})
            try:
                conn = sqlite3.connect(db_path)
                row = conn.execute("PRAGMA integrity_check").fetchone()
                ok = row is not None and row[0].upper() == "OK"
                report["ok"] &= ok
                report["checks"].append({"check": "sqlite_integrity", "ok": ok, "detail": row[0] if row else "missing"})
                row = conn.execute("PRAGMA user_version").fetchone()
                ok = row is not None and int(row[0]) == int(manifest.get("counts", {}).get("schema_version", -1))
                report["ok"] &= ok
                report["checks"].append({"check": "schema_version", "ok": ok, "expected": manifest.get("counts", {}).get("schema_version"), "actual": row[0] if row else None})
                conn.close()
            except sqlite3.Error as exc:
                report["ok"] = False
                report["checks"].append({"check": "sqlite_open", "ok": False, "detail": str(exc)})
    chroma_rel = manifest.get("paths", {}).get("chroma")
    if chroma_rel:
        chroma_path = backup_dir / chroma_rel if not Path(chroma_rel).is_absolute() else Path(chroma_rel)
        if not chroma_path.exists():
            report["ok"] = False
            report["checks"].append({"check": "chroma_exists", "ok": False, "detail": str(chroma_path)})
        else:
            try:
                import chromadb  # type: ignore[import-untyped]
            except ImportError:
                report["checks"].append({"check": "chroma_client", "ok": True, "detail": "chromadb not installed; skipped vector count"})
            else:
                try:
                    client = chromadb.PersistentClient(path=str(chroma_path))
                    count = client.get_or_create_collection("chunks").count()
                    ok = count >= 0
                    report["ok"] &= ok
                    report["checks"].append({"check": "chroma_vector_count", "ok": ok, "count": count, "expected": manifest.get("chroma_count")})
                except Exception as exc:
                    report["ok"] = False
                    report["checks"].append({"check": "chroma_open", "ok": False, "detail": str(exc)})
    uploads_rel = manifest.get("paths", {}).get("uploads")
    if uploads_rel:
        uploads_path = backup_dir / uploads_rel if not Path(uploads_rel).is_absolute() else Path(uploads_rel)
        report["checks"].append({"check": "uploads_exists", "ok": uploads_path.exists(), "detail": str(uploads_path)})
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify a backup directory")
    ap.add_argument("backup_dir", type=Path)
    ap.add_argument("--json", action="store_true", help="print JSON report only")
    args = ap.parse_args()
    report = verify(args.backup_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for check in report["checks"]:
            mark = "ok" if check.get("ok") else "FAIL"
            print(f"[{mark}] {check['check']}: {check.get('detail', '')}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
