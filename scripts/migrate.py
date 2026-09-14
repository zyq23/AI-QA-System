"""Manual migration runner + status viewer.

Usage:
  ./.venv/bin/python scripts/migrate.py [--db path [--dry-run]] status
  ./.venv/bin/python scripts/migrate.py [--db path] up

Without --db, uses DATABASE_PATH env or app settings default.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.migrations import LATEST_VERSION, migration_status, run_migrations  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage SQLite schema migrations.")
    parser.add_argument("action", choices=("status", "up"))
    parser.add_argument("--db", default=None, help="path to the SQLite database")
    parser.add_argument("--dry-run", action="store_true", help="print planned actions without applying")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else get_settings().database_path
    db = Database(db_path)

    if args.action == "status":
        status = migration_status(db)
        print(f"current : v{status['current_version']} (latest v{LATEST_VERSION})")
        for item in status["applied"]:
            print(f"  applied v{item['version']}: {item['name']} @ {item['applied_at']}")
        if not status["applied"]:
            print("  (no migrations recorded)")
        pending = status["pending"]
        print(f"pending : {len(pending)}")
        for item in pending:
            print(f"  v{item['version']}: {item['name']}")
        return 0

    status = migration_status(db)
    if not status["pending"]:
        print(f"Database is already at latest migration v{LATEST_VERSION}.")
        return 0

    if args.dry_run:
        print(f"Would apply {len(status['pending'])} migration(s):")
        for item in status["pending"]:
            print(f"  v{item['version']}: {item['name']}")
        return 0

    applied = run_migrations(db)
    for version in applied:
        print(f"Applied migration v{version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())