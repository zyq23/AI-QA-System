from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.db import Database
from app.repositories import Repository
from app.parsers.service import DocumentParserService
from app.services.chat import ChatService
from app.services.evaluation import EvaluationService
from app.services.chunker import ChunkerService
from app.services.ingestion import IngestionService
from app.services.llm import LlmService
from app.services.ml import EmbeddingService, RerankerService
from app.services.ragflow_sync import RagflowSyncService
from app.services.retrieval import RetrievalService
from app.services.vector_store import VectorStoreService
from app.services.version_cleanup import VersionCleanupService


@dataclass(slots=True)
class ServiceContainer:
    settings: Settings
    db: Database
    repository: Repository
    parser_service: DocumentParserService
    chunker_service: ChunkerService
    embedding_service: EmbeddingService
    reranker_service: RerankerService
    vector_store: VectorStoreService
    retrieval_service: RetrievalService
    llm_service: LlmService
    evaluation_service: EvaluationService
    ingestion_service: IngestionService
    chat_service: ChatService
    ragflow_sync_service: RagflowSyncService | None = None
    version_cleanup_service: VersionCleanupService | None = None
