from __future__ import annotations

import logging
from pathlib import Path

from fastapi import BackgroundTasks, UploadFile

from app.repositories import Repository
from app.services.chunker import ChunkerService, ChunkingContext
from app.services.ml import EmbeddingService
from app.services.vector_store import VectorStoreService
from app.parsers.service import DocumentParserService
from app.utils import sanitize_filename, sha256_bytes

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(
        self,
        repository: Repository,
        parser_service: DocumentParserService,
        chunker_service: ChunkerService,
        embedding_service: EmbeddingService,
        vector_store: VectorStoreService,
        upload_dir: Path,
    ) -> None:
        self.repository = repository
        self.parser_service = parser_service
        self.chunker_service = chunker_service
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.upload_dir = upload_dir

    async def register_uploads(
        self,
        files: list[UploadFile],
        source_type: str,
        trust_level: str,
        background_tasks: BackgroundTasks | None = None,
    ) -> dict[str, list[str]]:
        document_ids: list[str] = []
        version_ids: list[str] = []
        job_ids: list[str] = []
        for upload in files:
            raw = await upload.read()
            title = Path(upload.filename or "未命名文档").stem
            document = self.repository.create_or_get_document(title=title, filename=upload.filename or title, source_type=source_type, trust_level=trust_level)
            version_id, job_id = self._persist_upload(document["id"], upload.filename or "upload.bin", raw)
            document_ids.append(document["id"])
            version_ids.append(version_id)
            job_ids.append(job_id)
            if background_tasks is not None:
                background_tasks.add_task(self.process_version, version_id, job_id)
        return {"document_ids": document_ids, "versions": version_ids, "job_ids": job_ids}

    def _persist_upload(self, document_id: str, original_filename: str, raw: bytes) -> tuple[str, str]:
        safe_name = sanitize_filename(original_filename)
        document_dir = self.upload_dir / document_id
        document_dir.mkdir(parents=True, exist_ok=True)
        version = self.repository.create_document_version(
            document_id=document_id,
            original_filename=original_filename,
            stored_path="",
            file_size=len(raw),
            sha256=sha256_bytes(raw),
        )
        version_dir = document_dir / version["id"]
        version_dir.mkdir(parents=True, exist_ok=True)
        final_path = version_dir / safe_name
        final_path.write_bytes(raw)
        self.repository.update_version_storage_path(version["id"], str(final_path))
        self.repository.update_version_status(version["id"], parser_status="queued", index_status="queued")
        job = self.repository.create_job("ingest_document", {"version_id": version["id"]})
        self.repository.update_job(job["id"], status="queued", message="文档已入队")
        return version["id"], job["id"]

    def process_version(self, version_id: str, job_id: str) -> None:
        version = self.repository.get_version(version_id)
        if not version:
            self.repository.update_job(job_id, status="failed", message="版本不存在")
            return

        try:
            self.repository.update_job(job_id, status="running", message="开始解析文档")
            self.repository.update_version_status(version_id, parser_status="processing", index_status="processing")
            path = Path(version["stored_path"])
            parsed = self.parser_service.parse(path)
            context = ChunkingContext(
                document_id=version["document_id"],
                version_id=version_id,
                file_name=version["original_filename"],
                source_type=version["source_type"],
                trust_level=version["trust_level"],
                target_size=self.chunker_service.target_size,
                overlap=self.chunker_service.overlap,
            )
            chunks = self.chunker_service.chunk(parsed, context)
            embeddings = self.embedding_service.embed_documents([chunk.plain_text for chunk in chunks]) if chunks else []
            self.repository.replace_chunks(version_id, chunks)
            self.vector_store.delete_version(version_id)
            if chunks:
                self.vector_store.upsert_chunks(chunks, embeddings)
            self.repository.update_version_status(
                version_id,
                parser_status="completed",
                index_status="completed",
                parser_name=parsed.parser_name,
                ocr_used=parsed.ocr_used,
                warning_text="\n".join(parsed.warnings),
                chunk_count=len(chunks),
            )
            self.repository.update_job(job_id, status="completed", message=f"完成，共 {len(chunks)} 个分块")
        except Exception as exc:  # pragma: no cover - service runtime
            logger.exception("Failed to process version %s", version_id)
            self.repository.update_version_status(version_id, parser_status="failed", index_status="failed", warning_text=str(exc))
            self.repository.update_job(job_id, status="failed", message=str(exc))

    def reindex_version(self, version_id: str, background_tasks: BackgroundTasks | None = None) -> str:
        job = self.repository.create_job("reindex_document", {"version_id": version_id})
        if background_tasks is not None:
            background_tasks.add_task(self.process_version, version_id, job["id"])
        else:
            self.process_version(version_id, job["id"])
        return job["id"]

    def reindex_all(self, background_tasks: BackgroundTasks | None = None) -> list[str]:
        job_ids: list[str] = []
        for version in self.repository.get_current_versions():
            job_ids.append(self.reindex_version(version["id"], background_tasks=background_tasks))
        return job_ids

    def bootstrap_directory(
        self,
        directory: Path,
        *,
        source_type: str,
        trust_level: str,
        background_tasks: BackgroundTasks | None = None,
    ) -> dict[str, list[str]]:
        document_ids: list[str] = []
        version_ids: list[str] = []
        job_ids: list[str] = []
        if not directory.exists():
            return {"document_ids": [], "versions": [], "job_ids": []}

        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix.lower() not in {".pdf", ".docx", ".pptx"}:
                continue
            document = self.repository.create_or_get_document(path.stem, path.name, source_type, trust_level)
            version_id, job_id = self._persist_upload(document["id"], path.name, path.read_bytes())
            document_ids.append(document["id"])
            version_ids.append(version_id)
            job_ids.append(job_id)
            if background_tasks is not None:
                background_tasks.add_task(self.process_version, version_id, job_id)
            else:
                self.process_version(version_id, job_id)
        return {"document_ids": document_ids, "versions": version_ids, "job_ids": job_ids}
