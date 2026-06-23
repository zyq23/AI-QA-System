from __future__ import annotations

from app.repositories import Repository
from app.services.vector_store import VectorStoreService


class VersionCleanupService:
    def __init__(self, repository: Repository, vector_store: VectorStoreService) -> None:
        self.repository = repository
        self.vector_store = vector_store

    def cleanup_ragflow_duplicates(self) -> dict[str, int]:
        duplicates = self.repository.list_ragflow_duplicate_versions()
        removed_versions = 0
        affected_documents: set[str] = set()
        for item in duplicates:
            stale_version_id = str(item["stale_version_id"])
            self.repository.delete_document_version(stale_version_id)
            removed_versions += 1
            affected_documents.add(str(item["document_id"]))
        return {
            "removed_versions": removed_versions,
            "affected_documents": len(affected_documents),
        }
