"""Re-index all active documents with updated parsers and chunkers.

Looks for actual files in data/uploads/ (ignoring virtual ragflow: paths).
"""
from __future__ import annotations

import time
from pathlib import Path
from app.config import get_settings
from app.db import Database
from app.repositories import Repository
from app.parsers.service import DocumentParserService
from app.services.chunker import ChunkerService, ChunkingContext
from app.services.ml import EmbeddingService
from app.services.vector_store import VectorStoreService

settings = get_settings()
db = Database(settings.database_path)
db.initialize()
repo = Repository(db)

print("Loading services...")
parser_service = DocumentParserService(
    enable_ocr_fallback=settings.enable_ocr_fallback,
    ocr_language=settings.ocr_language,
)
chunker = ChunkerService(target_size=settings.chunk_target_size, overlap=settings.chunk_overlap)
embedding_service = EmbeddingService(settings.resolved_embedding_model, use_stub=False)
vector_store = VectorStoreService(str(settings.chroma_dir))

versions = repo.get_current_versions()
print(f"Re-indexing {len(versions)} versions...")
print(f"OCR enabled: {settings.enable_ocr_fallback}")

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
        # Try to find the file in the upload directory
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

    start = time.perf_counter()
    try:
        # Parse
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

        # Chunk
        chunks = chunker.chunk(parsed, context)

        # Embed
        embeddings = []
        if chunks:
            embeddings = embedding_service.embed_documents([c.plain_text for c in chunks])

        # Replace in DB and vector store
        repo.replace_chunks(vid, chunks)
        vector_store.delete_version(vid)
        if chunks and embeddings:
            vector_store.upsert_chunks(chunks, embeddings)

        # Update version status
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
