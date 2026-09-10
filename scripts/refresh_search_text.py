"""Refresh the FTS search_text column for all chunks with the current tokenizer.

Tokenization changes (e.g. the jieba compound-noun merge) change the FTS contract;
this re-derives search_text from the stored plain_text without re-parsing or
re-embedding anything. The chunks_au trigger keeps chunks_fts in sync on UPDATE.

Usage:
  ./.venv/bin/python scripts/refresh_search_text.py --dry-run
  ./.venv/bin/python scripts/refresh_search_text.py
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.utils import build_search_text, tokenize  # noqa: E402


def chunk_search_text(plain_text: str, file_name: str) -> str:
    """The FTS index covers chunk body text plus the document title tokens.

    Product docs often never repeat their own name in the body (e.g. the
    协作式机械臂 manual never says 机械臂), so title tokens are indexed per
    chunk to keep "机械臂" queries recallable."""
    body_tokens = tokenize(plain_text)
    title_tokens = tokenize(file_name)
    return " ".join(dict.fromkeys([*title_tokens, *body_tokens]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="count changes without writing")
    parser.add_argument("--batch", type=int, default=500)
    args = parser.parse_args()

    settings = get_settings()
    conn = sqlite3.connect(settings.database_path, timeout=60)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("SELECT id, file_name, plain_text, search_text FROM chunks").fetchall()
    updates: list[tuple[str, str]] = []
    for row in rows:
        new_text = chunk_search_text(row["plain_text"], row["file_name"])
        if new_text != (row["search_text"] or ""):
            updates.append((row["id"], new_text))

    print(f"{len(updates)}/{len(rows)} chunks need search_text refresh")
    if args.dry_run:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    for index in range(0, len(updates), args.batch):
        batch = updates[index : index + args.batch]
        conn.executemany(
            "UPDATE chunks SET search_text = ? WHERE id = ?",
            [(text, chunk_id) for chunk_id, text in batch],
        )
        conn.commit()
        print(f"  updated {min(index + args.batch, len(updates))}/{len(updates)}", flush=True)
    conn.close()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
