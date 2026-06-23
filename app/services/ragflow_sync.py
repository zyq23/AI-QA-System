from __future__ import annotations

from pathlib import Path

from app.domain import ChunkRecord
from app.repositories import Repository
from app.services.ragflow import RagflowClient
from app.services.vector_store import VectorStoreService
from app.services.ml import EmbeddingService
from app.utils import build_search_text, normalize_text, sanitize_filename, sha256_text


class RagflowSyncService:
    def __init__(
        self,
        *,
        repository: Repository,
        ragflow_client: RagflowClient,
        embedding_service: EmbeddingService,
        vector_store: VectorStoreService,
        upload_dir: Path,
    ) -> None:
        self.repository = repository
        self.ragflow_client = ragflow_client
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.upload_dir = upload_dir

    @staticmethod
    def _map_chunk(
        *,
        document_id: str,
        version_id: str,
        original_filename: str,
        chunk: dict,
        chunk_index: int,
        trust_level: str,
    ) -> ChunkRecord | None:
        content = normalize_text(str(chunk.get("content") or ""))
        if not content:
            return None
        chunk_hash = sha256_text(f"ragflow:{version_id}:{chunk.get('id') or chunk_index}:{content}")
        positions = chunk.get("positions") or []
        page_or_slide = ""
        if isinstance(positions, list) and positions:
            page_or_slide = str(positions[0])[:80]
        if not page_or_slide:
            page_or_slide = "ragflow"
        section_path = page_or_slide
        return ChunkRecord(
            chunk_id=chunk_hash[:32],
            document_id=document_id,
            version_id=version_id,
            file_name=original_filename,
            source_type="ragflow_import",
            trust_level=trust_level,
            page_or_slide=page_or_slide,
            section_path=section_path,
            chunk_index=chunk_index,
            chunk_hash=chunk_hash,
            markdown_text=content,
            plain_text=content,
            search_text=build_search_text(content),
        )

    def sync_dataset(self, dataset_id: str, *, trust_level: str = "internal") -> dict[str, int]:
        documents = self.ragflow_client.list_dataset_documents(dataset_id)
        synced_documents = 0
        synced_chunks = 0
        for document in documents:
            ragflow_document_id = str(document.get("id") or "").strip()
            if not ragflow_document_id:
                continue
            original_filename = str(document.get("name") or document.get("filename") or ragflow_document_id).strip()
            title = Path(original_filename).stem or ragflow_document_id
            stored_path = f"ragflow://{dataset_id}/{ragflow_document_id}/{sanitize_filename(original_filename)}"
            local_document = self.repository.create_or_get_document(
                title=title,
                filename=original_filename,
                source_type="official_import",
                trust_level=trust_level,
            )
            version = self.repository.get_version_by_stored_path(local_document["id"], stored_path)
            if version is None:
                version = self.repository.create_document_version(
                    document_id=local_document["id"],
                    original_filename=original_filename,
                    stored_path=stored_path,
                    file_size=0,
                    sha256=sha256_text(f"ragflow:{dataset_id}:{ragflow_document_id}"),
                )
            elif local_document.get("current_version") != version["id"]:
                self.repository.set_current_version(local_document["id"], version["id"])
            chunks_raw = self.ragflow_client.list_document_chunks(dataset_id, ragflow_document_id)
            chunks: list[ChunkRecord] = []
            for chunk_index, chunk in enumerate(chunks_raw):
                mapped = self._map_chunk(
                    document_id=local_document["id"],
                    version_id=version["id"],
                    original_filename=original_filename,
                    chunk=chunk,
                    chunk_index=chunk_index,
                    trust_level=trust_level,
                )
                if mapped is not None:
                    chunks.append(mapped)
            embeddings = self.embedding_service.embed_documents([chunk.plain_text for chunk in chunks]) if chunks else []
            self.repository.replace_chunks(version["id"], chunks)
            self.vector_store.delete_version(version["id"])
            if chunks:
                self.vector_store.upsert_chunks(chunks, embeddings)
            self.repository.update_version_status(
                version["id"],
                parser_status="completed",
                index_status="completed",
                parser_name="ragflow_import",
                ocr_used=False,
                warning_text="",
                chunk_count=len(chunks),
            )
            synced_documents += 1
            synced_chunks += len(chunks)
        return {"document_count": synced_documents, "chunk_count": synced_chunks}
