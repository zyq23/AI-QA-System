from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
import shutil
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.main import build_container


TARGET_FILE = "【公司介绍】轩辕网络公司介绍202606.pptx"
ANOMALY_PATH = Path("docs/thread-parser-anomaly-list.md")
PARSER_UPSTREAM_PAGES = ("slide-27", "slide-33", "slide-74", "slide-79", "slide-80", "slide-89")
ROUTE_PROBE_CASES = (
    {"question_id": "route-probe-p0-01", "question": "这份轩辕网络公司介绍 PPT 的目录分成哪四个部分？", "top_k": 4},
    {"question_id": "route-probe-p0-05", "question": "基础环境页提到了哪些基础设施或平台能力？请列举至少4项。", "top_k": 4},
    {"question_id": "route-probe-p0-06", "question": "基础模型页提到的平台能力包含哪些模型或数据治理能力？", "top_k": 4},
    {"question_id": "route-probe-p1-05", "question": "如果只根据 PPT 内容概括，轩辕网络的业务架构主线是什么？", "top_k": 4},
    {"question_id": "route-probe-p1-06", "question": "战略定位页有没有把轩辕网络定义成“AI+产教融合服务商”？", "top_k": 4},
)
ROUTE_PROBE_TO_DIAGNOSED_CASE_ID = {
    "route-probe-p0-01": "ppt-company-p0-01",
    "route-probe-p0-05": "ppt-company-p0-05",
    "route-probe-p0-06": "ppt-company-p0-06",
    "route-probe-p1-05": "ppt-company-p1-05",
    "route-probe-p1-06": "ppt-company-p1-06",
}


def _load_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _expected_file(case: dict[str, Any]) -> str:
    files = case.get("expected_files") or []
    return str(files[0]) if files else TARGET_FILE


def _section_keywords(case: dict[str, Any]) -> list[str]:
    return [str(item) for item in case.get("expected_section_keywords", []) if str(item).strip()]


def _answer_keywords(case: dict[str, Any]) -> list[str]:
    return [str(item) for item in case.get("expected_answer_keywords", []) if str(item).strip()]


def _hit_to_dict(hit: Any) -> dict[str, Any]:
    return {
        "document_id": hit.document_id,
        "file_name": hit.file_name,
        "page_or_slide": hit.page_or_slide,
        "section_path": hit.section_path,
        "snippet": hit.snippet,
        "trust_level": hit.trust_level,
        "source_type": hit.source_type,
        "score": hit.rerank_score or hit.fusion_score,
        "keyword_rank": hit.raw_scores.get("keyword_rank"),
        "vector_rank": hit.raw_scores.get("vector_rank"),
        "fusion_score": hit.fusion_score,
        "rerank_score": hit.rerank_score,
        "focus_matches": hit.raw_scores.get("focus_matches"),
    }


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword and keyword in text for keyword in keywords)


def _collect_text(hits: list[dict[str, Any]], limit: int) -> str:
    return "\n".join(
        f"{hit['section_path']}\n{hit['snippet']}"
        for hit in hits[:limit]
    )


def _keyword_coverage(text: str, keywords: list[str]) -> tuple[list[str], list[str]]:
    matched = [keyword for keyword in keywords if keyword and keyword in text]
    missing = [keyword for keyword in keywords if keyword and keyword not in text]
    return matched, missing


def _coverage_judgement(case: dict[str, Any], hits: list[dict[str, Any]], target_file_present: bool) -> str:
    question_type = str(case.get("expected_question_type") or "")
    answer_keywords = _answer_keywords(case)
    if question_type != "enumeration":
        return "not_applicable"
    if not target_file_present:
        return "missing_target_file"
    combined = _collect_text(hits[:5], 5)
    matched = sum(1 for keyword in answer_keywords if keyword in combined)
    required = min(2 if len(answer_keywords) < 4 else 3, len(answer_keywords)) if answer_keywords else 0
    if required and matched >= required:
        return "sufficient"
    return "coverage_insufficient"


def _grounded_judgement(case: dict[str, Any], result: Any, hits: list[dict[str, Any]], target_file_present: bool) -> str:
    expected_grounded = case.get("expected_grounded")
    if expected_grounded is False:
        return "correct_negative" if not result.grounded else "false_positive"
    if not result.grounded:
        return "not_grounded"
    if not target_file_present:
        return "grounded_without_target_file"
    combined_top3 = _collect_text(hits[:3], 3)
    answer_keywords = _answer_keywords(case)
    if answer_keywords and not _contains_any(combined_top3, answer_keywords):
        return "fake_grounded"
    if "目录" in str(case.get("question", "")) and combined_top3.count("CONTENTS") and not _contains_any(combined_top3, answer_keywords):
        return "fake_grounded"
    return "grounded_supported"


def _failure_type(case: dict[str, Any], result: Any, hits: list[dict[str, Any]], target_file_present: bool, target_hits: list[dict[str, Any]]) -> str:
    if not target_file_present:
        return "retrieval_candidate_miss"
    if case.get("expected_grounded") is False and result.grounded:
        return "fake_grounded"
    coverage = _coverage_judgement(case, hits, target_file_present)
    if coverage == "coverage_insufficient":
        return "coverage_insufficient"
    grounded = _grounded_judgement(case, result, hits, target_file_present)
    if grounded == "fake_grounded":
        return "fake_grounded"
    top3_target = target_hits[:3]
    if top3_target:
        noisy_pages = {hit["page_or_slide"] for hit in top3_target if hit["page_or_slide"] in PARSER_UPSTREAM_PAGES}
        if noisy_pages:
            return "parser_upstream"
    if target_hits and not any(hit in hits[:3] for hit in target_hits[:1]):
        return "rerank_bias"
    return "none"


def _answer_stage_blocker(
    case: dict[str, Any],
    failure_type: str,
    grounded_judgement: str,
    coverage_judgement: str,
) -> str:
    if case.get("expected_grounded") is False:
        return "none" if grounded_judgement == "correct_negative" else "negative_grounding_mismatch"
    if coverage_judgement == "coverage_insufficient":
        return "coverage_insufficient"
    if grounded_judgement != "grounded_supported":
        if grounded_judgement == "fake_grounded":
            return "fake_grounded"
        return "grounding_insufficient"
    if failure_type != "none":
        return failure_type
    return "none"


def _allow_answer_stage(case: dict[str, Any], failure_type: str, grounded_judgement: str, coverage_judgement: str) -> bool:
    if case.get("expected_grounded") is False:
        return grounded_judgement == "correct_negative"
    return failure_type == "none" and grounded_judgement == "grounded_supported" and coverage_judgement != "coverage_insufficient"


def _expected_hit_pages_or_sections(case: dict[str, Any]) -> list[str]:
    return _section_keywords(case)


def _diagnose_case(case: dict[str, Any], container: Any, dataset_name: str) -> dict[str, Any]:
    result = container.retrieval_service.retrieve(case["question"], top_k=6)
    hits = [_hit_to_dict(hit) for hit in result.hits]
    expected_file = _expected_file(case)
    target_hits = [hit for hit in hits if hit["file_name"] == expected_file]
    target_file_present = bool(target_hits)
    answer_keywords = _answer_keywords(case)
    combined_top5 = _collect_text(hits[:5], 5)
    combined_top3 = _collect_text(hits[:3], 3)
    coverage_matched_keywords, coverage_missing_keywords = _keyword_coverage(combined_top5, answer_keywords)
    grounded_matched_keywords, grounded_missing_keywords = _keyword_coverage(combined_top3, answer_keywords)
    coverage = _coverage_judgement(case, hits, target_file_present)
    grounded = _grounded_judgement(case, result, hits, target_file_present)
    failure_type = _failure_type(case, result, hits, target_file_present, target_hits)
    answer_stage_blocker = _answer_stage_blocker(case, failure_type, grounded, coverage)
    return {
        "dataset": dataset_name,
        "question_id": case["id"],
        "question": case["question"],
        "question_type": case.get("expected_question_type"),
        "expected_file": expected_file,
        "expected_section_keywords": _section_keywords(case),
        "expected_hit_pages_or_sections": _expected_hit_pages_or_sections(case),
        "rewritten_query": case["question"],
        "expanded_query": result.expanded_query,
        "focus_terms": result.focus_terms,
        "expansion_terms": result.expansion_terms,
        "grounded": result.grounded,
        "grounded_judgement": grounded,
        "coverage_judgement": coverage,
        "expected_answer_keywords": answer_keywords,
        "coverage_matched_keywords": coverage_matched_keywords,
        "coverage_missing_keywords": coverage_missing_keywords,
        "grounded_matched_keywords": grounded_matched_keywords,
        "grounded_missing_keywords": grounded_missing_keywords,
        "failure_type": failure_type,
        "answer_stage_blocker": answer_stage_blocker,
        "allow_answer_stage": _allow_answer_stage(case, failure_type, grounded, coverage),
        "used_fallback": result.used_fallback,
        "fallback_reason": result.fallback_reason,
        "backend_path": result.backend_path,
        "route_reason": result.route_reason,
        "remote_attempted": result.remote_attempted,
        "local_top_score": result.local_top_score,
        "local_quality_score": result.local_quality_score,
        "remote_quality_score": result.remote_quality_score,
        "local_grounded_score_threshold": result.local_grounded_score_threshold,
        "top_k_hit_files": [hit["file_name"] for hit in hits],
        "top_k_hit_sections": [hit["section_path"] for hit in hits],
        "top_k_hits": hits,
    }


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _prepare_isolated_env(tmp_root: Path) -> dict[str, str]:
    settings = get_settings()
    runtime_src = Path(settings.runtime_dir)
    chroma_src = Path(settings.chroma_dir)
    data_root = tmp_root / "data"
    runtime_dst = data_root / "runtime"
    chroma_dst = data_root / "chroma"
    uploads_dst = data_root / "uploads"
    evals_dst = data_root / "evals"
    models_dst = data_root / "models"
    kb_dst = tmp_root / "kb"

    runtime_dst.mkdir(parents=True, exist_ok=True)
    uploads_dst.mkdir(parents=True, exist_ok=True)
    evals_dst.mkdir(parents=True, exist_ok=True)
    kb_dst.mkdir(parents=True, exist_ok=True)
    _copy_tree(chroma_src, chroma_dst)
    shutil.copy2(runtime_src / "app.db", runtime_dst / "app.db")
    if models_dst.exists():
        shutil.rmtree(models_dst)
    os.symlink(settings.model_cache_dir.resolve(), models_dst)

    target_path = Path(settings.source_documents_dir) / TARGET_FILE
    if target_path.exists():
        os.symlink(target_path.resolve(), kb_dst / target_path.name)

    env = {
        "DATA_DIR": str(data_root),
        "UPLOAD_DIR": str(uploads_dst),
        "CHROMA_DIR": str(chroma_dst),
        "RUNTIME_DIR": str(runtime_dst),
        "DATABASE_PATH": str(runtime_dst / "app.db"),
        "SOURCE_DOCUMENTS_DIR": str(kb_dst),
        "EVAL_DATASET_PATH": str(evals_dst / "cases.json"),
        "EVAL_RESULTS_DIR": str(evals_dst / "results"),
        "MODEL_CACHE_DIR": str(models_dst),
        "RETRIEVAL_BACKEND": "local",
        "RETRIEVAL_MODE": "hybrid",
        "DISABLE_LLM": "true",
        "ENABLE_OCR_FALLBACK": "false",
    }
    return env


def _with_env(env: dict[str, str]) -> ExitStack:
    stack = ExitStack()
    for key, value in env.items():
        previous = os.environ.get(key)
        os.environ[key] = value
        stack.callback(_restore_env_var, key, previous)
    cache_clear = getattr(get_settings, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()
        stack.callback(cache_clear)
    return stack


def _restore_env_var(key: str, previous: str | None) -> None:
    if previous is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = previous


def _bootstrap_new_ppt(container: Any) -> dict[str, Any]:
    payload = container.ingestion_service.bootstrap_directory(
        container.settings.source_documents_dir,
        source_type="bootstrap",
        trust_level="internal",
        background_tasks=None,
    )
    for doc in container.repository.list_documents():
        if doc["title"] == Path(TARGET_FILE).stem:
            return {"bootstrapped": True, "document_row": doc, "payload": payload}
    return {"bootstrapped": False, "payload": payload}


def _build_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    failure_counts: dict[str, int] = {}
    blocker_counts: dict[str, int] = {}
    answer_ready = 0
    answer_ready_question_ids: list[str] = []
    blocked_question_ids: list[str] = []
    for entry in entries:
        failure_counts[entry["failure_type"]] = failure_counts.get(entry["failure_type"], 0) + 1
        blocker = str(entry.get("answer_stage_blocker") or "none")
        blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
        if entry["allow_answer_stage"]:
            answer_ready += 1
            answer_ready_question_ids.append(str(entry.get("question_id") or ""))
        else:
            blocked_question_ids.append(str(entry.get("question_id") or ""))
    return {
        "total_cases": len(entries),
        "answer_ready_cases": answer_ready,
        "failure_counts": failure_counts,
        "answer_stage_blocker_counts": blocker_counts,
        "answer_ready_question_ids": answer_ready_question_ids,
        "blocked_question_ids": blocked_question_ids,
    }


def _dataset_version_snapshot(p0_source: str, p1_source: str) -> dict[str, str]:
    return {
        "P0": p0_source,
        "P1": p1_source,
    }


def _build_answer_stage_recommendation(datasets: list[dict[str, Any]]) -> dict[str, Any]:
    answer_ready_question_ids: list[str] = []
    blocked_question_ids: list[str] = []
    dataset_breakdown: dict[str, dict[str, list[str]]] = {}
    answer_ready_case_details: list[dict[str, Any]] = []
    blocked_case_details: list[dict[str, Any]] = []
    blocked_by_answer_stage_blocker: dict[str, int] = {}
    blocked_by_failure_type: dict[str, int] = {}
    blocked_question_ids_by_answer_stage_blocker: dict[str, list[str]] = {}
    blocked_question_ids_by_failure_type: dict[str, list[str]] = {}
    for dataset in datasets:
        dataset_name = str(dataset.get("name") or "")
        summary = dataset.get("summary") or {}
        ready = [str(item) for item in summary.get("answer_ready_question_ids", []) if str(item)]
        blocked = [str(item) for item in summary.get("blocked_question_ids", []) if str(item)]
        answer_ready_question_ids.extend(ready)
        blocked_question_ids.extend(blocked)
        if dataset_name:
            dataset_breakdown[dataset_name] = {
                "answer_ready_question_ids": ready,
                "blocked_question_ids": blocked,
            }
        for question in dataset.get("questions", []):
            detail = {
                "dataset": dataset_name,
                "question_id": question.get("question_id"),
                "question": question.get("question"),
                "failure_type": question.get("failure_type"),
                "answer_stage_blocker": question.get("answer_stage_blocker"),
                "grounded_judgement": question.get("grounded_judgement"),
                "coverage_judgement": question.get("coverage_judgement"),
            }
            if question.get("allow_answer_stage") is True:
                answer_ready_case_details.append(detail)
            else:
                blocked_case_details.append(detail)
                blocker = str(question.get("answer_stage_blocker") or "none")
                blocked_by_answer_stage_blocker[blocker] = blocked_by_answer_stage_blocker.get(blocker, 0) + 1
                blocked_question_ids_by_answer_stage_blocker.setdefault(blocker, []).append(str(question.get("question_id") or ""))
                failure_type = str(question.get("failure_type") or "none")
                blocked_by_failure_type[failure_type] = blocked_by_failure_type.get(failure_type, 0) + 1
                blocked_question_ids_by_failure_type.setdefault(failure_type, []).append(str(question.get("question_id") or ""))
    return {
        "answer_ready_question_ids": answer_ready_question_ids,
        "blocked_question_ids": blocked_question_ids,
        "answer_ready_case_count": len(answer_ready_question_ids),
        "blocked_case_count": len(blocked_question_ids),
        "dataset_breakdown": dataset_breakdown,
        "answer_ready_case_details": answer_ready_case_details,
        "blocked_case_details": blocked_case_details,
        "blocked_by_answer_stage_blocker": blocked_by_answer_stage_blocker,
        "blocked_by_failure_type": blocked_by_failure_type,
        "blocked_question_ids_by_answer_stage_blocker": blocked_question_ids_by_answer_stage_blocker,
        "blocked_question_ids_by_failure_type": blocked_question_ids_by_failure_type,
    }


def _runtime_retrieval_config_snapshot(settings: Any) -> dict[str, Any]:
    return {
        "retrieval_backend": settings.retrieval_backend,
        "retrieval_mode": settings.retrieval_mode,
        "ragflow_prefer_local_grounded": settings.ragflow_prefer_local_grounded,
        "ragflow_local_grounded_score_threshold": settings.ragflow_local_grounded_score_threshold,
        "ragflow_fallback_timeout_ms": settings.ragflow_fallback_timeout_ms,
        "ragflow_timeout_seconds": settings.ragflow_timeout_seconds,
    }


def _route_probe_target_file_hits(probe: dict[str, Any]) -> int:
    return sum(1 for file_name in probe.get("hit_files", []) if file_name == TARGET_FILE)


def _build_route_probe_summary(probes: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "total_cases": len(probes),
        "status_counts": {},
        "backend_path_counts": {},
        "remote_selected_cases": 0,
        "remote_selected_old_doc_dominant_cases": 0,
        "target_file_topk_covered_cases": 0,
    }
    for probe in probes:
        status = str(probe.get("status") or "unknown")
        summary["status_counts"][status] = summary["status_counts"].get(status, 0) + 1
        backend_path = str(probe.get("backend_path") or "unknown")
        summary["backend_path_counts"][backend_path] = summary["backend_path_counts"].get(backend_path, 0) + 1
        if backend_path == "ragflow":
            summary["remote_selected_cases"] += 1
            if _route_probe_target_file_hits(probe) == 0:
                summary["remote_selected_old_doc_dominant_cases"] += 1
        if _route_probe_target_file_hits(probe) > 0:
            summary["target_file_topk_covered_cases"] += 1
    return summary


def _index_diagnosed_entries(datasets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for dataset in datasets:
        for question in dataset.get("questions", []):
            question_id = str(question.get("question_id") or "")
            if question_id:
                indexed[question_id] = question
    return indexed


def _build_route_conflict_summary(probes: list[dict[str, Any]], diagnosed_entries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    conflicts: list[dict[str, Any]] = []
    for probe in probes:
        route_question_id = str(probe.get("question_id") or "")
        diagnosed_question_id = ROUTE_PROBE_TO_DIAGNOSED_CASE_ID.get(route_question_id)
        if not diagnosed_question_id:
            continue
        diagnosed = diagnosed_entries.get(diagnosed_question_id)
        if not diagnosed:
            continue
        local_target_top1 = bool(diagnosed.get("top_k_hit_files")) and diagnosed["top_k_hit_files"][0] == TARGET_FILE
        remote_old_doc_dominant = probe.get("backend_path") == "ragflow" and _route_probe_target_file_hits(probe) == 0
        if local_target_top1 and remote_old_doc_dominant:
            conflicts.append(
                {
                    "route_question_id": route_question_id,
                    "diagnosed_question_id": diagnosed_question_id,
                    "question": probe.get("question"),
                    "local_allow_answer_stage": diagnosed.get("allow_answer_stage"),
                    "local_failure_type": diagnosed.get("failure_type"),
                    "local_grounded_judgement": diagnosed.get("grounded_judgement"),
                    "route_backend_path": probe.get("backend_path"),
                    "route_reason": probe.get("route_reason"),
                    "route_fallback_reason": probe.get("fallback_reason"),
                    "route_hit_files": probe.get("hit_files"),
                }
            )
    answer_ready_conflicts = [item for item in conflicts if item.get("local_allow_answer_stage") is True]
    blocked_conflicts = [item for item in conflicts if item.get("local_allow_answer_stage") is not True]
    return {
        "conflict_cases": conflicts,
        "conflict_case_count": len(conflicts),
        "answer_ready_conflicts": answer_ready_conflicts,
        "answer_ready_conflict_count": len(answer_ready_conflicts),
        "blocked_conflicts": blocked_conflicts,
        "blocked_conflict_count": len(blocked_conflicts),
    }


def _route_probe(
    question_id: str,
    question: str,
    top_k: int,
    env: dict[str, str],
    configured_backend: str,
    configured_mode: str,
) -> dict[str, Any]:
    probe_env = dict(env)
    probe_env["RETRIEVAL_BACKEND"] = configured_backend
    probe_env["RETRIEVAL_MODE"] = configured_mode
    with _with_env(probe_env):
        try:
            container = build_container()
            result = container.retrieval_service.retrieve(question, top_k=top_k)
            return {
                "status": "ok",
                "question_id": question_id,
                "question": question,
                "top_k": top_k,
                "backend_path": result.backend_path,
                "route_reason": result.route_reason,
                "used_fallback": result.used_fallback,
                "fallback_reason": result.fallback_reason,
                "remote_attempted": result.remote_attempted,
                "local_top_score": result.local_top_score,
                "local_quality_score": result.local_quality_score,
                "remote_quality_score": result.remote_quality_score,
                "local_grounded_score_threshold": result.local_grounded_score_threshold,
                "grounded": result.grounded,
                "hit_files": [hit.file_name for hit in result.hits[:top_k]],
                "configured_backend": configured_backend,
                "configured_mode": configured_mode,
            }
        except Exception as exc:  # pragma: no cover - runtime probe only
            return {
                "status": "error",
                "question_id": question_id,
                "question": question,
                "top_k": top_k,
                "configured_backend": configured_backend,
                "configured_mode": configured_mode,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run retrieval-only diagnosis for the new PPT in an isolated local environment.")
    parser.add_argument("--p0-dataset", default="data/evals/ppt_company_p0_8.json")
    parser.add_argument("--p1-dataset", default="data/evals/ppt_company_p1_8.json")
    parser.add_argument("--output", default="docs/thread-retrieval-diagnosis.json")
    args = parser.parse_args()

    base_settings = get_settings()
    cases = [("P0", _load_cases(Path(args.p0_dataset))), ("P1", _load_cases(Path(args.p1_dataset)))]
    output: dict[str, Any] = {
        "run_date": None,
        "dataset_version": _dataset_version_snapshot(args.p0_dataset, args.p1_dataset),
        "p0_summary": None,
        "p1_summary": None,
        "answer_stage_recommendation": None,
        "datasets": [],
        "assumptions": [
            "本轮属于能力判断层，不是正式回归验收。",
            "RAGFlow 现象不作为能力结论；本诊断强制使用本地 hybrid 链路。",
            "新增 PPT 当前正式库未入链，本诊断通过隔离运行态 bootstrap 新 PPT 做本地召回验证。",
            "route_probe 仅记录按正式后端配置运行时的选路现象或异常，不把远端现象直接写成能力结论。",
        ],
        "parser_anomaly_source": str(ANOMALY_PATH),
        "official_runtime_has_new_ppt": False,
        "isolation_runtime_bootstrapped_new_ppt": False,
        "runtime_retrieval_config": _runtime_retrieval_config_snapshot(base_settings),
    }

    with tempfile.TemporaryDirectory(prefix="thread-retrieval-") as tmp_dir:
        tmp_root = Path(tmp_dir)
        isolated_env = _prepare_isolated_env(tmp_root)
        with _with_env(isolated_env):
            container = build_container()
            existing_titles = {doc["title"] for doc in container.repository.list_documents()}
            output["official_runtime_has_new_ppt"] = Path(TARGET_FILE).stem in existing_titles
            bootstrap_result = _bootstrap_new_ppt(container)
            output["isolation_runtime_bootstrapped_new_ppt"] = bool(bootstrap_result["bootstrapped"])
            output["bootstrap_payload"] = bootstrap_result["payload"]
            output["bootstrap_document"] = bootstrap_result.get("document_row")

            datasets_output: list[dict[str, Any]] = []
            for dataset_name, dataset_cases in cases:
                entries = [_diagnose_case(case, container, dataset_name) for case in dataset_cases]
                summary = _build_summary(entries)
                datasets_output.append(
                    {
                        "name": dataset_name,
                        "source": args.p0_dataset if dataset_name == "P0" else args.p1_dataset,
                        "summary": summary,
                        "questions": entries,
                    }
                )
                if dataset_name == "P0":
                    output["p0_summary"] = summary
                elif dataset_name == "P1":
                    output["p1_summary"] = summary
            output["datasets"] = datasets_output
            output["answer_stage_recommendation"] = _build_answer_stage_recommendation(datasets_output)

            route_probes = [
                _route_probe(
                    question_id=probe_case["question_id"],
                    question=probe_case["question"],
                    top_k=int(probe_case["top_k"]),
                    env=isolated_env,
                    configured_backend=base_settings.retrieval_backend,
                    configured_mode=base_settings.retrieval_mode,
                )
                for probe_case in ROUTE_PROBE_CASES
            ]
            output["route_probe"] = {
                "summary": _build_route_probe_summary(route_probes),
                "questions": route_probes,
            }
            output["route_probe_vs_local"] = _build_route_conflict_summary(
                route_probes,
                _index_diagnosed_entries(output["datasets"]),
            )
            output["run_date"] = datetime.now().isoformat()

    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": args.output, "datasets": [item["name"] for item in output["datasets"]]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
