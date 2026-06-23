from __future__ import annotations

from typing import Any

import chromadb
from chromadb.errors import InvalidArgumentError

from app.domain import ChunkRecord


class VectorStoreService:
    def __init__(self, persist_directory: str) -> None:
        self.client = chromadb.PersistentClient(path=persist_directory)
        self.collection = self._get_or_create_collection()

    def _get_or_create_collection(self):
        return self.client.get_or_create_collection(
            name="chunks",
            metadata={"hnsw:space": "cosine"},
        )

    def reset_collection(self) -> None:
        try:
            self.client.delete_collection("chunks")
        except Exception:
            pass
        self.collection = self._get_or_create_collection()

    def delete_version(self, version_id: str) -> None:
        self.collection.delete(where={"version_id": version_id})

    def upsert_chunks(self, chunks: list[ChunkRecord], embeddings: list[list[float]]) -> None:
        if not chunks:
            return
        payload = {
            "ids": [chunk.chunk_id for chunk in chunks],
            "embeddings": embeddings,
            "documents": [chunk.plain_text for chunk in chunks],
            "metadatas": [
                {
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.document_id,
                    "version_id": chunk.version_id,
                    "file_name": chunk.file_name,
                    "page_or_slide": chunk.page_or_slide,
                    "section_path": chunk.section_path,
                    "trust_level": chunk.trust_level,
                    "source_type": chunk.source_type,
                    "chunk_index": chunk.chunk_index,
                }
                for chunk in chunks
            ],
        }
        try:
            self.collection.upsert(**payload)
        except InvalidArgumentError as exc:
            if "dimension" not in str(exc).lower():
                raise
            self.reset_collection()
            self.collection.upsert(**payload)

    def query(self, query_embedding: list[float], n_results: int) -> list[dict[str, Any]]:
        response = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
        ids = response.get("ids", [[]])[0]
        documents = response.get("documents", [[]])[0]
        metadatas = response.get("metadatas", [[]])[0]
        distances = response.get("distances", [[]])[0]
        results = []
        for item_id, document, metadata, distance in zip(ids, documents, metadatas, distances):
            results.append(
                {
                    "chunk_id": item_id,
                    "document": document,
                    "metadata": metadata or {},
                    "distance": float(distance or 0.0),
                }
            )
        return results
