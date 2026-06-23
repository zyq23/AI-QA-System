from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.dependencies import get_container, require_admin
from app.schemas import (
    AnswerRunDetail,
    AnswerRunSummary,
    DocumentRow,
    JobSummary,
    RetrievalDebugHit,
    RetrievalDebugRequest,
    RetrievalDebugResponse,
    RagflowSyncResponse,
    RagflowCleanupResponse,
    UploadResponse,
)

RETRIEVAL_FAILURE_KEYS = {"citation_match", "section_match", "grounded_match"}
REWRITE_FAILURE_KEYS = {"question_type_match"}
ANSWER_FAILURE_KEYS = {
    "keyword_match",
    "forbidden_match",
    "insufficient_match",
    "direct_match",
    "no_leak_match",
    "concise_match",
    "fallback_clean",
}


def _is_content_policy_blocked(run) -> bool:
    return bool(
        run.draft.get("confidence_note") == "content_policy_blocked"
        or run.review.get("raw_payload", {}).get("error_type") == "content_policy_blocked"
    )


def _llm_reviewer_called(run) -> bool:
    raw_payload = run.review.get("raw_payload", {}) if isinstance(run.review, dict) else {}
    if raw_payload.get("llm_review_skipped") is True:
        return False
    return bool(run.latency_review_ms > 0 and raw_payload.get("mode") != "deterministic")


def _failed_checks(report: dict) -> list[str]:
    ordered_keys = [
        "citation_match",
        "section_match",
        "keyword_match",
        "forbidden_match",
        "insufficient_match",
        "grounded_match",
        "question_type_match",
        "direct_match",
        "no_leak_match",
        "concise_match",
        "fallback_clean",
    ]
    return [key for key in ordered_keys if report.get(key) is False]


def _failure_bucket(failed_checks: list[str]) -> str:
    failed_set = set(failed_checks)
    has_retrieval = bool(failed_set & RETRIEVAL_FAILURE_KEYS)
    has_rewrite = bool(failed_set & REWRITE_FAILURE_KEYS)
    has_answer = bool(failed_set & ANSWER_FAILURE_KEYS)
    if sum((has_retrieval, has_rewrite, has_answer)) > 1:
        return "mixed"
    if has_retrieval:
        return "retrieval"
    if has_rewrite:
        return "rewrite"
    return "answer"


def _failure_label(bucket: str) -> str:
    return {
        "retrieval": "检索侧",
        "rewrite": "改写侧",
        "answer": "收口侧",
        "mixed": "混合问题",
    }.get(bucket, "收口侧")


def _latest_eval_failures(latest_eval: dict | None, limit: int = 8) -> list[dict]:
    if not latest_eval:
        return []
    result = latest_eval.get("result") or {}
    reports = result.get("reports") or []
    failures: list[dict] = []
    for report in reports:
        if report.get("passed"):
            continue
        failed_checks = _failed_checks(report)
        bucket = _failure_bucket(failed_checks)
        answer_run_id = report.get("answer_run_id")
        failures.append(
            {
                "case_id": report.get("case_id"),
                "turn_index": report.get("turn_index"),
                "category": report.get("category"),
                "question": report.get("question"),
                "answer": report.get("answer"),
                "top_citation_file": report.get("top_citation_file"),
                "failed_checks": failed_checks,
                "failure_bucket": bucket,
                "failure_label": _failure_label(bucket),
                "answer_run_id": answer_run_id,
                "answer_run_link": f"/api/admin/answer-runs/{answer_run_id}" if answer_run_id else None,
            }
        )
        if len(failures) >= limit:
            break
    return failures


def build_admin_context(request: Request) -> dict:
    container = get_container(request)
    jobs = container.repository.list_jobs()
    latest_eval = container.repository.latest_job(job_type="evaluation", status="completed")
    answer_runs = container.repository.list_answer_runs(limit=12)
    answer_run_stats = {
        "total": len(answer_runs),
        "reviewer_intervened": sum(1 for run in answer_runs if run.review.get("reviewer_intervened")),
        "llm_reviewer_called": sum(1 for run in answer_runs if _llm_reviewer_called(run)),
        "fallback_used": sum(1 for run in answer_runs if run.draft.get("used_fallback") or run.retrieval.get("used_fallback")),
        "content_policy_blocked": sum(1 for run in answer_runs if _is_content_policy_blocked(run)),
        "avg_latency_ms": round(sum(run.latency_total_ms for run in answer_runs) / len(answer_runs), 2)
        if answer_runs
        else 0.0,
    }
    issue_counts: dict[str, int] = {}
    for run in answer_runs:
        for issue in run.review.get("issues", []):
            issue_counts[str(issue)] = issue_counts.get(str(issue), 0) + 1
    top_issues = sorted(issue_counts.items(), key=lambda item: item[1], reverse=True)[:6]
    return {
        "documents": container.repository.list_documents(),
        "jobs": jobs,
        "knowledge_dir": str(container.settings.source_documents_dir),
        "latest_eval": latest_eval,
        "latest_eval_failures": _latest_eval_failures(latest_eval),
        "answer_runs": answer_runs,
        "answer_run_stats": answer_run_stats,
        "top_issues": top_issues,
        "retrieval_debug": None,
    }


def _resolve_eval_dataset(container, dataset: str | None) -> Path:
    if not dataset:
        return container.settings.eval_dataset_path
    candidate = Path(dataset)
    if not candidate.is_absolute():
        candidate = container.settings.data_dir.parent / candidate
    candidate = candidate.resolve()
    eval_root = (container.settings.data_dir / "evals").resolve()
    if eval_root not in candidate.parents:
        raise HTTPException(status_code=400, detail="Evaluation dataset must be under data/evals.")
    if not candidate.exists():
        raise HTTPException(status_code=404, detail="Evaluation dataset not found.")
    return candidate


def _latest_evaluation_job(container) -> dict | None:
    return container.repository.latest_job(job_type="evaluation", status="completed")


def build_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()
    api = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

    @api.post("/documents", response_model=UploadResponse)
    async def upload_documents(
        request: Request,
        background_tasks: BackgroundTasks,
        files: list[UploadFile] = File(...),
        source_type: str = Form("upload"),
        trust_level: str = Form("internal"),
    ):
        container = get_container(request)
        if not files:
            raise HTTPException(status_code=400, detail="No files uploaded.")
        for upload in files:
            if upload.size and upload.size > container.settings.upload_size_limit_bytes:
                raise HTTPException(status_code=413, detail=f"{upload.filename} exceeds upload limit.")
        payload = await container.ingestion_service.register_uploads(files, source_type, trust_level, background_tasks)
        return UploadResponse(**payload)

    @api.get("/documents", response_model=list[DocumentRow])
    def list_documents(request: Request):
        return get_container(request).repository.list_documents()

    @api.post("/documents/{document_id}/reindex")
    def reindex_document(request: Request, document_id: str, background_tasks: BackgroundTasks):
        container = get_container(request)
        document = container.repository.get_document(document_id)
        if not document or not document.get("current_version_id"):
            raise HTTPException(status_code=404, detail="Document not found.")
        job_id = container.ingestion_service.reindex_version(document["current_version_id"], background_tasks)
        return {"document_id": document_id, "job_id": job_id}

    @api.post("/reindex")
    def reindex_all(request: Request, background_tasks: BackgroundTasks):
        job_ids = get_container(request).ingestion_service.reindex_all(background_tasks)
        return {"job_ids": job_ids}

    @api.post("/evals/run")
    def run_evaluations(
        request: Request,
        background_tasks: BackgroundTasks,
        dataset: str | None = Query(default=None),
    ):
        container = get_container(request)
        dataset_path = _resolve_eval_dataset(container, dataset)
        job = container.repository.create_job(
            "evaluation",
            payload={"dataset": str(dataset_path)},
        )
        background_tasks.add_task(container.evaluation_service.run_job, job["id"], dataset_path)
        return {"job_id": job["id"], "status": "queued"}

    @api.post("/evals/run-failures")
    def run_failed_evaluations(request: Request, background_tasks: BackgroundTasks):
        container = get_container(request)
        latest_eval = _latest_evaluation_job(container)
        if not latest_eval or not latest_eval.get("result"):
            raise HTTPException(status_code=400, detail="No completed evaluation result available.")
        rerun_dataset = container.settings.eval_results_dir / "latest_failed_cases.json"
        generated = container.evaluation_service.build_failed_case_dataset(
            latest_eval["result"],
            output_path=rerun_dataset,
        )
        dataset_path = Path(generated["dataset_path"])
        job = container.repository.create_job(
            "evaluation",
            payload={"dataset": str(dataset_path), "mode": "failed_cases"},
        )
        background_tasks.add_task(container.evaluation_service.run_job, job["id"], dataset_path)
        return {"job_id": job["id"], "status": "queued", "dataset": str(dataset_path), "case_count": generated["case_count"]}

    @api.delete("/documents/{document_id}")
    def disable_document(request: Request, document_id: str):
        container = get_container(request)
        if not container.repository.get_document(document_id):
            raise HTTPException(status_code=404, detail="Document not found.")
        container.repository.disable_document(document_id)
        return {"document_id": document_id, "status": "disabled"}

    @api.post("/retrieval/test", response_model=RetrievalDebugResponse)
    def retrieval_test(request: Request, payload: RetrievalDebugRequest):
        container = get_container(request)
        result = container.retrieval_service.retrieve(payload.question, top_k=payload.top_k)
        return RetrievalDebugResponse(
            question=payload.question,
            rewritten_query=payload.question,
            expanded_query=result.expanded_query,
            focus_terms=result.focus_terms,
            expansion_terms=result.expansion_terms,
            grounded=result.grounded,
            used_fallback=result.used_fallback,
            fallback_reason=result.fallback_reason,
            backend_path=result.backend_path,
            route_reason=result.route_reason,
            remote_attempted=result.remote_attempted,
            local_top_score=result.local_top_score,
            local_quality_score=result.local_quality_score,
            remote_quality_score=result.remote_quality_score,
            local_grounded_score_threshold=result.local_grounded_score_threshold,
            hits=[
                RetrievalDebugHit(
                    document_id=hit.document_id,
                    file_name=hit.file_name,
                    page_or_slide=hit.page_or_slide,
                    section_path=hit.section_path,
                    snippet=hit.snippet,
                    trust_level=hit.trust_level,
                    source_type=hit.source_type,
                    score=hit.rerank_score or hit.fusion_score,
                    keyword_rank=hit.raw_scores.get("keyword_rank"),
                    vector_rank=hit.raw_scores.get("vector_rank"),
                    fusion_score=hit.fusion_score,
                    rerank_score=hit.rerank_score,
                    focus_matches=hit.raw_scores.get("focus_matches"),
                )
                for hit in result.hits
            ],
        )

    @api.post("/ragflow/sync", response_model=RagflowSyncResponse)
    def sync_ragflow_dataset(request: Request):
        container = get_container(request)
        if not container.ragflow_sync_service:
            raise HTTPException(status_code=400, detail="RAGFlow sync is not configured.")
        dataset_ids = container.settings.ragflow_dataset_ids
        synced_documents = 0
        synced_chunks = 0
        for dataset_id in dataset_ids:
            result = container.ragflow_sync_service.sync_dataset(dataset_id)
            synced_documents += int(result["document_count"])
            synced_chunks += int(result["chunk_count"])
        return RagflowSyncResponse(
            dataset_ids=dataset_ids,
            synced_documents=synced_documents,
            synced_chunks=synced_chunks,
        )

    @api.post("/ragflow/cleanup", response_model=RagflowCleanupResponse)
    def cleanup_ragflow_versions(request: Request):
        container = get_container(request)
        if not container.version_cleanup_service:
            raise HTTPException(status_code=400, detail="Version cleanup service is not configured.")
        result = container.version_cleanup_service.cleanup_ragflow_duplicates()
        return RagflowCleanupResponse(
            removed_versions=int(result["removed_versions"]),
            affected_documents=int(result["affected_documents"]),
        )

    @api.get("/jobs", response_model=list[JobSummary])
    def list_jobs(request: Request):
        jobs = get_container(request).repository.list_jobs()
        return [
            JobSummary(
                job_id=job["id"],
                status=job["status"],
                job_type=job["job_type"],
                message=job.get("message"),
                created_at=job["created_at"],
                updated_at=job["updated_at"],
            )
            for job in jobs
        ]

    @api.get("/answer-runs", response_model=list[AnswerRunSummary])
    def list_answer_runs(request: Request):
        return [
            AnswerRunSummary(
                answer_run_id=run.answer_run_id,
                conversation_id=run.conversation_id,
                question=run.question,
                rewritten_query=run.rewritten_query,
                expanded_query=str(run.retrieval.get("expanded_query") or ""),
                expansion_terms=[str(term) for term in run.retrieval.get("expansion_terms", [])],
                question_type=run.question_type,
                answer_focus=run.answer_focus,
                final_answer=run.final_answer,
                final_grounded=run.final_grounded,
                content_policy_blocked=_is_content_policy_blocked(run),
                stage_status=run.stage_status,
                failure_stage=run.failure_stage,
                latency_total_ms=run.latency_total_ms,
                latency_retrieval_ms=run.latency_retrieval_ms,
                latency_generate_ms=run.latency_generate_ms,
                latency_review_ms=run.latency_review_ms,
                created_at=run.created_at,
            )
            for run in get_container(request).repository.list_answer_runs(limit=50)
        ]

    @api.get("/answer-runs/{answer_run_id}", response_model=AnswerRunDetail)
    def get_answer_run(request: Request, answer_run_id: str):
        run = get_container(request).repository.get_answer_run(answer_run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Answer run not found.")
        return AnswerRunDetail(
            answer_run_id=run.answer_run_id,
            conversation_id=run.conversation_id,
            question=run.question,
            rewritten_query=run.rewritten_query,
            expanded_query=str(run.retrieval.get("expanded_query") or ""),
            expansion_terms=[str(term) for term in run.retrieval.get("expansion_terms", [])],
            question_type=run.question_type,
            answer_focus=run.answer_focus,
            final_answer=run.final_answer,
            final_grounded=run.final_grounded,
            content_policy_blocked=_is_content_policy_blocked(run),
            stage_status=run.stage_status,
            failure_stage=run.failure_stage,
            latency_total_ms=run.latency_total_ms,
            latency_retrieval_ms=run.latency_retrieval_ms,
            latency_generate_ms=run.latency_generate_ms,
            latency_review_ms=run.latency_review_ms,
            created_at=run.created_at,
            retrieval=run.retrieval,
            draft=run.draft,
            review=run.review,
            final_grounded_answer=run.final_grounded_answer,
            final_inference_note=run.final_inference_note,
        )

    @api.post("/bootstrap")
    def bootstrap_knowledge_base(request: Request, background_tasks: BackgroundTasks):
        container = get_container(request)
        payload = container.ingestion_service.bootstrap_directory(
            container.settings.source_documents_dir,
            source_type="bootstrap",
            trust_level="internal",
            background_tasks=background_tasks,
        )
        return payload

    htmx = APIRouter(prefix="/admin/actions", tags=["admin-ui"])

    def render_admin_shell(request: Request):
        return templates.TemplateResponse(request, "partials/admin_shell.html", build_admin_context(request))

    def render_admin_shell_with_debug(request: Request, retrieval_debug: dict | None):
        context = build_admin_context(request)
        context["retrieval_debug"] = retrieval_debug
        return templates.TemplateResponse(request, "partials/admin_shell.html", context)

    @htmx.get("/documents", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
    def admin_documents_partial(request: Request):
        return render_admin_shell(request)

    @htmx.post("/upload", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
    async def admin_upload_partial(
        request: Request,
        background_tasks: BackgroundTasks,
        files: list[UploadFile] = File(...),
        source_type: str = Form("upload"),
        trust_level: str = Form("internal"),
    ):
        container = get_container(request)
        await container.ingestion_service.register_uploads(files, source_type, trust_level, background_tasks)
        return render_admin_shell(request)

    @htmx.post("/documents/{document_id}/reindex", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
    def admin_reindex_partial(request: Request, document_id: str, background_tasks: BackgroundTasks):
        container = get_container(request)
        document = container.repository.get_document(document_id)
        if document and document.get("current_version_id"):
            container.ingestion_service.reindex_version(document["current_version_id"], background_tasks)
        return render_admin_shell(request)

    @htmx.post("/reindex-all", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
    def admin_reindex_all_partial(request: Request, background_tasks: BackgroundTasks):
        get_container(request).ingestion_service.reindex_all(background_tasks)
        return render_admin_shell(request)

    @htmx.post("/evals/run", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
    def admin_run_evals_partial(
        request: Request,
        background_tasks: BackgroundTasks,
        dataset: str = Form(default="data/evals/knowledge_base_eval_cases.json"),
    ):
        container = get_container(request)
        dataset_path = _resolve_eval_dataset(container, dataset)
        job = container.repository.create_job(
            "evaluation",
            payload={"dataset": str(dataset_path)},
        )
        background_tasks.add_task(container.evaluation_service.run_job, job["id"], dataset_path)
        return render_admin_shell(request)

    @htmx.post("/evals/run-failures", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
    def admin_run_failed_evals_partial(request: Request, background_tasks: BackgroundTasks):
        container = get_container(request)
        latest_eval = _latest_evaluation_job(container)
        if latest_eval and latest_eval.get("result"):
            rerun_dataset = container.settings.eval_results_dir / "latest_failed_cases.json"
            generated = container.evaluation_service.build_failed_case_dataset(
                latest_eval["result"],
                output_path=rerun_dataset,
            )
            dataset_path = Path(generated["dataset_path"])
            job = container.repository.create_job(
                "evaluation",
                payload={"dataset": str(dataset_path), "mode": "failed_cases"},
            )
            background_tasks.add_task(container.evaluation_service.run_job, job["id"], dataset_path)
        return render_admin_shell(request)

    @htmx.post("/documents/{document_id}/disable", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
    def admin_disable_partial(request: Request, document_id: str):
        container = get_container(request)
        if container.repository.get_document(document_id):
            container.repository.disable_document(document_id)
        return render_admin_shell(request)

    @htmx.post("/bootstrap", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
    def admin_bootstrap_partial(request: Request, background_tasks: BackgroundTasks):
        container = get_container(request)
        container.ingestion_service.bootstrap_directory(
            container.settings.source_documents_dir,
            source_type="bootstrap",
            trust_level="internal",
            background_tasks=background_tasks,
        )
        return render_admin_shell(request)

    @htmx.post("/ragflow/sync", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
    def admin_ragflow_sync_partial(request: Request):
        container = get_container(request)
        if container.ragflow_sync_service:
            for dataset_id in container.settings.ragflow_dataset_ids:
                container.ragflow_sync_service.sync_dataset(dataset_id)
        return render_admin_shell(request)

    @htmx.post("/ragflow/cleanup", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
    def admin_ragflow_cleanup_partial(request: Request):
        container = get_container(request)
        if container.version_cleanup_service:
            container.version_cleanup_service.cleanup_ragflow_duplicates()
        return render_admin_shell(request)

    @htmx.post("/retrieval/test", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
    async def admin_retrieval_test_partial(
        request: Request,
        question: str = Form(...),
        top_k: int = Form(6),
    ):
        container = get_container(request)
        result = container.retrieval_service.retrieve(question, top_k=top_k)
        retrieval_debug = {
            "question": question,
            "rewritten_query": question,
            "expanded_query": result.expanded_query,
            "focus_terms": result.focus_terms,
            "expansion_terms": result.expansion_terms,
            "grounded": result.grounded,
            "used_fallback": result.used_fallback,
            "fallback_reason": result.fallback_reason,
            "backend_path": result.backend_path,
            "route_reason": result.route_reason,
            "remote_attempted": result.remote_attempted,
            "local_top_score": result.local_top_score,
            "local_quality_score": result.local_quality_score,
            "remote_quality_score": result.remote_quality_score,
            "local_grounded_score_threshold": result.local_grounded_score_threshold,
            "hits": [
                {
                    "document_id": hit.document_id,
                    "file_name": hit.file_name,
                    "page_or_slide": hit.page_or_slide,
                    "section_path": hit.section_path,
                    "snippet": hit.snippet,
                    "trust_level": hit.trust_level,
                    "source_type": hit.source_type,
                    "score": round(hit.rerank_score or hit.fusion_score, 4),
                    "keyword_rank": hit.raw_scores.get("keyword_rank"),
                    "vector_rank": hit.raw_scores.get("vector_rank"),
                    "fusion_score": round(hit.fusion_score, 4),
                    "rerank_score": round(hit.rerank_score, 4),
                    "focus_matches": hit.raw_scores.get("focus_matches"),
                }
                for hit in result.hits
            ],
        }
        return render_admin_shell_with_debug(request, retrieval_debug)

    router.include_router(api)
    router.include_router(htmx)
    return router
