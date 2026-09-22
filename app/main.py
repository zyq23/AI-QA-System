from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth import AdminSessionSigner
from app.config import get_settings
from app.container import ServiceContainer
from app.db import Database
from app.parsers.service import DocumentParserService
from app.repositories import Repository
from app.routers import api_admin, api_agent, api_chat, api_robot, pages
from app.services.chat import ChatService
from app.services.evaluation import EvaluationService
from app.services.chunker import ChunkerService
from app.services.ingestion import IngestionService
from app.services.llm import LlmService
from app.services.ml import EmbeddingService, RerankerService
from app.services.ragflow import RagflowClient
from app.services.ragflow_sync import RagflowSyncService
from app.services.retrieval import AdaptiveRetrievalService, FallbackRetrievalService, RagflowRetrievalService, RetrievalService
from app.services.vector_store import VectorStoreService
from app.services.version_cleanup import VersionCleanupService
from app.metrics import metrics as _metrics


# Configure structured JSON logging with request-id support (production-ready)
def setup_logging():
    """Configure root logger for structured JSON output with request-id propagation."""
    from app.log_sanitizer import SanitizeLogFilter

    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z"
    )
    handler.setFormatter(formatter)
    # Filters on the root logger do not run for records propagated from child
    # loggers; attach sanitization to the emitting handler instead.
    handler.addFilter(SanitizeLogFilter())
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)


setup_logging()


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Inject X-Request-ID + record per-request latency/error metrics."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            route = request.scope.get("path", "unknown")
            # Normalize path params so metrics don't explode in cardinality.
            if route.startswith("/api/chat/sessions/"):
                route = "/api/chat/sessions/{conversation_id}"
            _metrics.observe_request(
                f"http.request{route}",
                elapsed_ms,
                is_error=status_code >= 500,
            )


def build_container() -> ServiceContainer:
    settings = get_settings()
    db = Database(settings.database_path)
    db.initialize()
    repository = Repository(db)
    parser_service = DocumentParserService(
        enable_ocr_fallback=settings.enable_ocr_fallback,
        ocr_language=settings.ocr_language,
    )
    chunker_service = ChunkerService(target_size=settings.chunk_target_size, overlap=settings.chunk_overlap)
    embedding_service = EmbeddingService(settings.resolved_embedding_model, use_stub=settings.use_stub_ml)
    # In fts_only mode, a heavyweight reranker adds latency but little value compared to lexical reranking.
    reranker_use_stub = settings.use_stub_ml or settings.retrieval_mode.strip().lower() == "fts_only"
    reranker_service = RerankerService(settings.resolved_reranker_model, use_stub=reranker_use_stub)
    vector_store = VectorStoreService(str(settings.chroma_dir))
    local_retrieval_service = RetrievalService(
        repository=repository,
        embedding_service=embedding_service,
        reranker_service=reranker_service,
        vector_store=vector_store,
        candidates=settings.retrieval_candidates,
        default_top_k=settings.retrieval_context_k,
        retrieval_mode=settings.retrieval_mode,
    )
    if settings.retrieval_backend.strip().lower() == "ragflow":
        if not settings.ragflow_base_url or not settings.ragflow_api_key:
            raise ValueError("RAGFLOW_BASE_URL and RAGFLOW_API_KEY are required when RETRIEVAL_BACKEND=ragflow.")
        ragflow_client = RagflowClient(
            base_url=settings.ragflow_base_url,
            api_key=settings.ragflow_api_key,
            timeout_seconds=settings.ragflow_timeout_seconds,
        )
        ragflow_retrieval_service = RagflowRetrievalService(
            client=ragflow_client,
            dataset_ids=settings.ragflow_dataset_ids,
            document_ids=settings.ragflow_document_ids,
            default_top_k=settings.retrieval_context_k,
            page_size=settings.ragflow_page_size,
            similarity_threshold=settings.ragflow_similarity_threshold,
            vector_similarity_weight=settings.ragflow_vector_similarity_weight,
            keyword=settings.ragflow_keyword,
            highlight=settings.ragflow_highlight,
            use_kg=settings.ragflow_use_kg,
            toc_enhance=settings.ragflow_toc_enhance,
        )
        if settings.ragflow_prefer_local_grounded:
            retrieval_service = AdaptiveRetrievalService(
                local_retrieval_service,
                ragflow_retrieval_service,
                remote_timeout_ms=settings.ragflow_fallback_timeout_ms,
                local_grounded_score_threshold=settings.ragflow_local_grounded_score_threshold,
            )
        elif settings.ragflow_fallback_to_local:
            retrieval_service = FallbackRetrievalService(
                ragflow_retrieval_service,
                local_retrieval_service,
                primary_timeout_ms=settings.ragflow_fallback_timeout_ms,
            )
        else:
            retrieval_service = ragflow_retrieval_service
    else:
        retrieval_service = local_retrieval_service
    ragflow_sync_service = None
    if settings.ragflow_base_url and settings.ragflow_api_key and settings.ragflow_dataset_ids:
        ragflow_sync_service = RagflowSyncService(
            repository=repository,
            ragflow_client=RagflowClient(
                base_url=settings.ragflow_base_url,
                api_key=settings.ragflow_api_key,
                timeout_seconds=settings.ragflow_timeout_seconds,
            ),
            embedding_service=embedding_service,
            vector_store=vector_store,
            upload_dir=settings.upload_dir,
        )
    llm_service = LlmService(
        provider=settings.llm_provider,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        spark_app_id=settings.spark_app_id,
        spark_api_key=settings.spark_api_key,
        spark_api_secret=settings.spark_api_secret,
        spark_api_base=settings.spark_api_base,
        spark_model=settings.spark_model,
        spark_domain=settings.spark_domain,
        spark_temperature=settings.spark_temperature,
        spark_max_tokens=settings.spark_max_tokens,
        spark_thinking_type=settings.spark_thinking_type,
        spark_request_timeout_seconds=settings.spark_request_timeout_seconds,
        spark_uid=settings.spark_uid,
        review_policy=settings.llm_review_policy,
        disabled=settings.disable_llm,
    )
    ingestion_service = IngestionService(
        repository=repository,
        parser_service=parser_service,
        chunker_service=chunker_service,
        embedding_service=embedding_service,
        vector_store=vector_store,
        upload_dir=settings.upload_dir,
    )
    chat_service = ChatService(
        repository=repository,
        retrieval_service=retrieval_service,
        llm_service=llm_service,
        history_turns=settings.conversation_history_turns,
    )
    from app.agent.service import AgentService
    agent_service = AgentService(
        repository=repository,
        chat_service=chat_service,
        llm_service=llm_service,
    )
    evaluation_service = EvaluationService(
        settings=settings,
        repository=repository,
        chat_service=chat_service,
    )
    version_cleanup_service = VersionCleanupService(
        repository=repository,
        vector_store=vector_store,
    )
    from app.services.job_worker import JobWorker
    job_worker = JobWorker(repository, owner=f"api-{os.getpid()}")
    job_worker.register("ingest_document", ingestion_service.process_job)
    job_worker.register("reindex_document", ingestion_service.process_job)
    job_worker.register("evaluation", evaluation_service.process_job)
    ingestion_service.attach_worker(job_worker)
    return ServiceContainer(
        settings=settings,
        db=db,
        repository=repository,
        parser_service=parser_service,
        chunker_service=chunker_service,
        embedding_service=embedding_service,
        reranker_service=reranker_service,
        vector_store=vector_store,
        retrieval_service=retrieval_service,
        llm_service=llm_service,
        evaluation_service=evaluation_service,
        ingestion_service=ingestion_service,
        chat_service=chat_service,
        agent_service=agent_service,
        ragflow_sync_service=ragflow_sync_service,
        version_cleanup_service=version_cleanup_service,
        job_worker=job_worker,
    )


def build_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    templates.env.globals["enumerate"] = enumerate
    return templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.container = build_container()
    app.state.admin_signer = AdminSessionSigner(app.state.container.settings.secret_key)
    # Reclaim jobs stuck in running/queued for over 24h (e.g. after a crash):
    # prevents a stale running job from polluting "latest eval" queries forever.
    import sqlite3
    from datetime import datetime, timedelta, timezone

    repo = app.state.container.repository
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    try:
        with repo.db.connect() as conn:
            stuck = conn.execute(
                "SELECT id FROM jobs WHERE status IN ('running','queued') AND updated_at < ?",
                (cutoff,),
            ).fetchall()
            for row in stuck:
                conn.execute(
                    "UPDATE jobs SET status='failed', message='reclaimed on startup (stuck >24h)' WHERE id=?",
                    (row["id"],),
                )
    except sqlite3.Error:
        pass
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    templates = build_templates()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    
    # Install request-id middleware for tracing and correlation
    app.add_middleware(RequestIdMiddleware)

    @app.get("/live", tags=["health"])
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["health"])
    def ready(request: Request):
        """Readiness probe: verify the initialized SQLite store is queryable."""
        container = getattr(request.app.state, "container", None)
        if container is None:
            return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "container_not_initialized"})
        try:
            with container.db.connect() as conn:
                conn.execute("SELECT 1").fetchone()
            return {"status": "ready", "database": "ok"}
        except Exception:
            return JSONResponse(status_code=503, content={"status": "not_ready", "database": "error"})

    @app.get("/healthz", tags=["health"])
    def healthz(request: Request):
        container = getattr(request.app.state, "container", None)
        if container is None:
            return JSONResponse(status_code=503, content={"status": "unhealthy"})
        return {"status": "ok", "ready": True, "retrieval_backend": container.settings.retrieval_backend}

    @app.get("/metrics", tags=["health"])
    def metrics_endpoint():
        """Expose in-process request metrics (counts, error rate, latency percentiles)."""
        return _metrics.snapshot()

    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app.include_router(pages.build_router(templates))
    app.include_router(api_admin.build_router(templates))
    app.include_router(api_chat.build_router())
    app.include_router(api_robot.build_router())
    app.include_router(api_agent.build_router())
    return app


app = create_app()
