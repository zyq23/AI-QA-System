"""Re-index all active documents with updated parsers and chunkers.

Looks for actual files in data/uploads/ (ignoring virtual ragflow: paths).

Usage:
    python scripts/reindex_all.py                # full rebuild (with backup)
    python scripts/reindex_all.py --dry-run      # preview only, nothing written
    python scripts/reindex_all.py --no-ocr       # parse without OCR fallback
    python scripts/reindex_all.py --no-backup    # skip DB/Chroma backup
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import time
from pathlib import Path

from app.config import get_settings
from app.db import Database
from app.repositories import Repository
from app.parsers.service import DocumentParserService
from app.services.chunker import ChunkerService, ChunkingContext
from app.services.ml import EmbeddingService
from app.services.vector_store import VectorStoreService


def backup_assets(settings) -> None:
    from datetime import datetime

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = settings.data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    if settings.database_path.exists():
        target = backup_dir / f"app-before-reindex-{stamp}.db"
        src = sqlite3.connect(settings.database_path)
        dst = sqlite3.connect(target)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        print(f"backup db -> {target}")

    if settings.chroma_dir.exists():
        target = backup_dir / f"chroma-before-reindex-{stamp}"
        shutil.copytree(settings.chroma_dir, target, ignore=shutil.ignore_patterns("*.lock"))
        print(f"backup chroma -> {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="preview without writing anything")
    parser.add_argument("--no-ocr", action="store_true", help="disable OCR fallback during parse")
    parser.add_argument("--no-backup", action="store_true", help="skip the DB/Chroma backup step")
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="re-index only documents whose original_filename contains this substring (repeatable)",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not args.no_backup and not args.dry_run:
        backup_assets(settings)
    elif args.dry_run:
        print("(dry-run: backup skipped)")

    db = Database(settings.database_path)
    db.initialize()
    repo = Repository(db)

    print("Loading services...")
    parser_service = DocumentParserService(
        enable_ocr_fallback=not args.no_ocr,
        ocr_language=settings.ocr_language,
    )
    chunker = ChunkerService(target_size=settings.chunk_target_size, overlap=settings.chunk_overlap)
    embedding_service = EmbeddingService(settings.resolved_embedding_model, use_stub=False)
    vector_store = VectorStoreService(str(settings.chroma_dir))

    versions = repo.get_current_versions()
    if args.only:
        versions = [v for v in versions if any(tag in v["original_filename"] for tag in args.only)]
        print(f"Filtered to {len(versions)} versions matching {args.only}")
    print(f"Re-indexing {len(versions)} versions...")
    print(f"OCR enabled: {not args.no_ocr}")

    total_start = time.perf_counter()
    total_chunks = 0
    skipped_ragflow = 0
    rebuilt = 0

    for i, version in enumerate(versions, 1):
        vid = version["id"]
        doc_id = version["document_id"]
        filename = version["original_filename"]
        path_str = version["stored_path"]

        if not path_str or path_str.startswith("ragflow:"):
            skipped_ragflow += 1
            upload_candidates = sorted(
                (settings.upload_dir / doc_id).rglob("*"),
                key=lambda p: -p.stat().st_size if p.is_file() else 0,
            )
            actual_path = next(
                (p for p in upload_candidates if p.is_file() and p.suffix.lower() in {".pdf", ".docx", ".pptx"}),
                None,
            )
            if not actual_path:
                print(f"  [{i}/{len(versions)}] {filename} - SKIP (ragflow path, no local file)")
                continue
        else:
            actual_path = Path(path_str)

        if not actual_path.exists():
            print(f"  [{i}/{len(versions)}] {filename} - SKIP (file missing: {actual_path})")
            continue

        if args.dry_run:
            print(f"  [{i}/{len(versions)}] {filename} - dry-run preview (would parse+embed)")
            continue

        start = time.perf_counter()
        try:
            parsed = parser_service.parse(actual_path)

            context = ChunkingContext(
                document_id=doc_id,
                version_id=vid,
                file_name=filename,
                source_type=version["source_type"],
                trust_level=version["trust_level"],
                target_size=chunker.target_size,
                overlap=chunker.overlap,
            )

            chunks = chunker.chunk(parsed, context)

            embeddings = []
            if chunks:
                embeddings = embedding_service.embed_documents([c.plain_text for c in chunks])

            repo.replace_chunks(vid, chunks)
            vector_store.delete_version(vid)
            if chunks and embeddings:
                vector_store.upsert_chunks(chunks, embeddings)

            repo.update_version_status(
                vid,
                parser_status="completed",
                index_status="completed",
                parser_name=parsed.parser_name,
                ocr_used=parsed.ocr_used,
                warning_text="\n".join(parsed.warnings[:5]),
                chunk_count=len(chunks),
            )

            elapsed = int((time.perf_counter() - start) * 1000)
            label = f"ocr={parsed.ocr_used}" if parsed.ocr_used else "no-ocr"
            print(f"  [{i}/{len(versions)}] {filename} -> {len(chunks)} chunks, {label} ({elapsed}ms)")
            total_chunks += len(chunks)
            rebuilt += 1
        except Exception as exc:
            import traceback

            print(f"  [{i}/{len(versions)}] {filename} - FAILED: {exc}")
            traceback.print_exc()

    total_elapsed = int((time.perf_counter() - total_start) * 1000)
    print(f"\nDone. {total_chunks} chunks in {rebuilt}/{len(versions)} versions ({total_elapsed}ms)")
    if skipped_ragflow:
        print(f"({skipped_ragflow} RAGFlow-sourced versions, auto-resolved via upload dir)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
