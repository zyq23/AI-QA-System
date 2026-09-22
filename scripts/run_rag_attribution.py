"""Run RAG cases with an evidence-first attribution trace.

Unlike the score-only runner, this records the decision path needed to tell
retrieval misses from rerank misses, claim extraction failures, and answer
finalization blocks. It intentionally does not modify the production database
or answer-run history.

Usage:
  EVAL_API_BASE_URL= RETRIEVAL_BACKEND=local ./.venv/bin/python \
    scripts/run_rag_attribution.py --dataset data/evals/harder_eval_v1.json \
    --category cross_document --limit 20
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import build_container  # noqa: E402
from app.services.claim_matrix import extract_claims  # noqa: E402
from scripts.run_rag_metrics import judge_answer, judge_retrieval  # noqa: E402


def _hit_record(hit: Any, rank: int | None = None) -> dict[str, Any]:
    raw_scores = dict(getattr(hit, "raw_scores", {}) or {})
    return {
        "rank": rank,
        "chunk_id": getattr(hit, "chunk_id", ""),
        "file_name": getattr(hit, "file_name", ""),
        "page_or_slide": getattr(hit, "page_or_slide", ""),
        "section_path": getattr(hit, "section_path", ""),
        "fusion_score": getattr(hit, "fusion_score", 0.0),
        "rerank_score": getattr(hit, "rerank_score", 0.0),
        "ocr_quality": getattr(hit, "ocr_quality", 1.0),
        "raw_scores": raw_scores,
        "plain_text": (getattr(hit, "plain_text", "") or "")[:1200],
    }


def _analysis_record(analysis: Any) -> dict[str, Any]:
    return {
        "rewritten_query": getattr(analysis, "rewritten_query", ""),
        "question_type": getattr(analysis, "question_type", ""),
        "answer_focus": getattr(analysis, "answer_focus", ""),
        "focus_terms": list(getattr(analysis, "focus_terms", []) or []),
        "expansion_terms": list(getattr(analysis, "expansion_terms", []) or []),
        "used_fallback": bool(getattr(analysis, "used_fallback", False)),
    }


def _result_record(result: Any) -> dict[str, Any]:
    return {
        "grounded": bool(getattr(result, "grounded", False)),
        "expanded_query": getattr(result, "expanded_query", ""),
        "focus_terms": list(getattr(result, "focus_terms", []) or []),
        "expansion_terms": list(getattr(result, "expansion_terms", []) or []),
        "backend_path": getattr(result, "backend_path", ""),
        "route_reason": getattr(result, "route_reason", ""),
        "hits": [_hit_record(hit, rank) for rank, hit in enumerate(getattr(result, "hits", []) or [], 1)],
    }


def _draft_record(draft: Any) -> dict[str, Any]:
    return {
        "answer": getattr(draft, "answer", ""),
        "grounded_answer": getattr(draft, "grounded_answer", ""),
        "inference_note": getattr(draft, "inference_note", ""),
        "grounded": bool(getattr(draft, "grounded", False)),
        "confidence_note": getattr(draft, "confidence_note", ""),
        "used_fallback": bool(getattr(draft, "used_fallback", False)),
        "raw_payload": getattr(draft, "raw_payload", {}) or {},
    }


def _review_record(review: Any) -> dict[str, Any]:
    return {
        "passed": bool(getattr(review, "passed", False)),
        "issues": list(getattr(review, "issues", []) or []),
        "risk_level": getattr(review, "risk_level", ""),
        "reviewer_intervened": bool(getattr(review, "reviewer_intervened", False)),
        "revised_answer": getattr(review, "revised_answer", ""),
        "raw_payload": getattr(review, "raw_payload", {}) or {},
    }


def _final_record(final: dict[str, Any]) -> dict[str, Any]:
    return {
        "answer": final.get("answer", ""),
        "grounded_answer": final.get("grounded_answer", ""),
        "inference_note": final.get("inference_note", ""),
        "grounded": bool(final.get("grounded", False)),
        "question_type": final.get("question_type", ""),
        "review_issues": list(final.get("review_issues", []) or []),
        "reviewer_intervened": bool(final.get("reviewer_intervened", False)),
        "fallback_used": bool(final.get("fallback_used", False)),
        "claims": list(final.get("claims", []) or []),
        "evidence_ids": list(final.get("evidence_ids", []) or []),
    }


def _classify_trace(trace: dict[str, Any], case: dict[str, Any]) -> str:
    """Produce a coarse attribution label; raw evidence remains authoritative."""
    retrieval = trace["retrieval"]
    final = trace["final"]
    expected = case.get("expected_evidence") or []
    if expected and (trace["scores"].get("recall_10") or 0.0) == 0.0:
        return "retrieval_no_expected_evidence"
    claims = final.get("claims") or []
    if len(claims) >= 2 and not all(bool(c.get("covered")) for c in claims):
        return "claim_coverage_incomplete"
    if retrieval.get("hits") and not final.get("grounded"):
        return "finalize_or_grounding_block"
    if final.get("grounded") and trace["scores"].get("bucket") in {"wrong_release", "wrong_block"}:
        return "generation_or_answer_contract"
    if retrieval.get("hits") and not trace["scores"].get("recall_5", 0.0):
        return "rerank_or_candidate_window"
    return "none_or_needs_review"


def run(dataset_path: Path, output_dir: Path, *, limit: int | None = None, categories: list[str] | None = None, case_ids: list[str] | None = None) -> Path:
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    category_set = {x.strip() for x in (categories or []) if x.strip()}
    id_set = {x.strip() for x in (case_ids or []) if x.strip()}
    cases = [
        c for c in cases
        if (not category_set or c.get("category") in category_set)
        and (not id_set or str(c.get("id")) in id_set)
    ]
    if limit:
        cases = cases[:limit]

    container = build_container()
    chat = container.chat_service
    traces: list[dict[str, Any]] = []
    started = time.perf_counter()

    for index, case in enumerate(cases, 1):
        question = case["question"]
        case_started = time.perf_counter()
        try:
            conversation_id = chat.repository.ensure_conversation(None)
            history = chat.repository.get_recent_turn_context(conversation_id, chat.history_turns)
            analysis = chat.llm_service.rewrite_query(question, history)
            primary = chat.retrieval_service.retrieve(
                analysis.rewritten_query,
                top_k=None,
                focus_terms=analysis.focus_terms,
                expansion_terms=analysis.expansion_terms,
            )
            sub_queries = chat._decompose_question(question, analysis)
            hits, grounded = chat._multi_query_retrieve(question, analysis, None)
            hits = chat._augment_multi_part_evidence(question, hits, None)
            draft = chat.llm_service.generate_answer(question, analysis, hits, grounded)
            review = chat.llm_service.review_answer(question, analysis, hits, draft)
            final = chat.llm_service.finalize_answer(question, analysis, hits, draft, review)
            payload = {
                "answer": final.get("answer", ""),
                "grounded": bool(final.get("grounded", False)),
                "citations": [_hit_record(hit, rank) for rank, hit in enumerate(hits, 1)],
            }
            scores = judge_retrieval(payload["citations"], case.get("expected_evidence") or {})
            scores["bucket"] = judge_answer(case, payload)
            trace = {
                "id": case["id"],
                "question": question,
                "category": case.get("category"),
                "expected_files": case.get("expected_files", []),
                "expected_answer_keywords": case.get("expected_answer_keywords", []),
                "expected_evidence": case.get("expected_evidence", []),
                "analysis": _analysis_record(analysis),
                "claims_extracted": [list(pair) for pair in extract_claims(question)],
                "primary_retrieval": _result_record(primary),
                "sub_queries": sub_queries,
                "retrieval": {
                    "grounded": grounded,
                    "hits": payload["citations"],
                },
                "draft": _draft_record(draft),
                "review": _review_record(review),
                "final": _final_record(final),
                "scores": scores,
                "attribution": "",
                "latency_ms": round((time.perf_counter() - case_started) * 1000, 1),
            }
            trace["attribution"] = _classify_trace(trace, case)
        except Exception as exc:  # keep the trace usable after one case failure
            trace = {
                "id": case.get("id"),
                "question": question,
                "category": case.get("category"),
                "error": {"type": type(exc).__name__, "message": str(exc)},
                "attribution": "runtime_error",
                "latency_ms": round((time.perf_counter() - case_started) * 1000, 1),
            }
        traces.append(trace)
        print(f"[{index}/{len(cases)}] {case.get('id')} {trace.get('scores', {}).get('bucket', 'ERROR')} {trace.get('attribution')}", flush=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"rag_attribution_{stamp}.json"
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "dataset": str(dataset_path),
        "case_count": len(traces),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "traces": traces,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output-dir", default="data/evals/results")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--category", action="append", dest="categories")
    parser.add_argument("--case-id", action="append", dest="case_ids")
    args = parser.parse_args()
    run(Path(args.dataset), Path(args.output_dir), limit=args.limit, categories=args.categories, case_ids=args.case_ids)


if __name__ == "__main__":
    main()
