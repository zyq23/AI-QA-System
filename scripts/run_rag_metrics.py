"""Enterprise-grade RAG quality metrics over a hard-eval dataset.

Judges a retrieval result stream (per question top-k hits) plus the final answer
payload against the dataset's expected_evidence (file + page_or_slide + keywords).

Metrics:
- Recall@3 / @5 / @10: an expected evidence entry counts as recalled when a hit
  matches the SAME file AND SAME page_or_slide AND at least one keyword of that
  entry appears in the hit text. Judged per evidence entry (macro over entries).
- MRR@10 / nDCG@10 over the same evidence matching rule.
- Answer accuracy: answer_pass / (answer_pass + wrong_release) — wrong_release is
  a hallucinated release (grounded answer given for a must_block question, or a
  must_answer question answered without its expected keywords).
- Per-bucket breakdown for every difficulty category.

Usage (offline, direct against chat service):
  EVAL_API_BASE_URL= RETRIEVAL_BACKEND=local ./.venv/bin/python \
    scripts/run_rag_metrics.py --dataset data/evals/hard_eval_v1.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import build_container  # noqa: E402

INSUFFICIENT_MARKERS = (
    "当前知识库没有直接证据",
    "当前知识库中没有找到",
    "未提及",
    "无法确认",
    "无法给出",
    "资料不足",
)


def hit_matches_evidence(hit: dict, evidence: dict) -> bool:
    """file + page double condition, then a keyword inside the hit text."""
    if hit.get("file_name") != evidence["file_name"]:
        return False
    if evidence.get("page_or_slide") and hit.get("page_or_slide") != evidence["page_or_slide"]:
        return False
    text = (hit.get("plain_text") or hit.get("snippet") or "").lower()
    return any(kw.lower() in text for kw in evidence.get("keywords", []))


def judge_retrieval(citations: list[dict], expected_evidence: list[dict]) -> dict:
    """Per-question retrieval judgement against all expected evidence entries."""
    if not expected_evidence:
        return {"recall_3": None, "recall_5": None, "recall_10": None, "mrr": None, "ndcg": None, "first_rank": None}
    recalls = {3: [], 5: [], 10: []}
    rrs: list[float] = []
    dcgs: list[float] = []
    idcgs: list[float] = []
    for ev in expected_evidence:
        first_rank = None
        for rank, hit in enumerate(citations[:10], start=1):
            if hit_matches_evidence(hit, ev):
                first_rank = rank
                break
        for k in recalls:
            recalls[k].append(1.0 if first_rank is not None and first_rank <= k else 0.0)
        rrs.append(1.0 / first_rank if first_rank else 0.0)
        dcg = sum(
            1.0 / math.log2(rank + 1)
            for rank, hit in enumerate(citations[:10], start=1)
            if hit_matches_evidence(hit, ev)
        )
        idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(citations), 10) + 1))
        dcgs.append(dcg)
        idcgs.append(idcg if idcg > 0 else 1.0)
    return {
        "recall_3": sum(recalls[3]) / len(recalls[3]),
        "recall_5": sum(recalls[5]) / len(recalls[5]),
        "recall_10": sum(recalls[10]) / len(recalls[10]),
        "mrr": sum(rrs) / len(rrs),
        "ndcg": sum(d / i for d, i in zip(dcgs, idcgs)) / len(dcgs),
        "first_rank": min((rr for rr in (1.0 / r if r else None for r in rrs) if rr), default=None),
    }


def is_insufficient(text: str) -> bool:
    return any(marker in text for marker in INSUFFICIENT_MARKERS)


def judge_answer(case: dict, payload: dict) -> str:
    """formal bucket: answer_pass / correct_block / wrong_release / wrong_block."""
    answer = str(payload.get("answer") or "")
    grounded = bool(payload.get("grounded"))
    mode = case.get("expected_result_mode")
    if mode == "must_block":
        if grounded and not is_insufficient(answer):
            return "wrong_release"
        return "correct_block"
    # must_answer family
    keywords = case.get("expected_answer_keywords") or []
    keyword_ok = all(kw in answer for kw in keywords) if keywords else True
    files_ok = True
    if case.get("expected_files"):
        cited = {c.get("file_name") for c in payload.get("citations") or []}
        files_ok = any(f in cited for f in case["expected_files"])
    if grounded and not is_insufficient(answer) and keyword_ok and files_ok:
        return "answer_pass"
    if not grounded or is_insufficient(answer):
        return "wrong_block"
    # grounded release that misses keywords/citations: count as wrong_release
    # only when keywords exist (claim not actually delivered); otherwise wrong_block
    return "wrong_release" if keywords and not keyword_ok else "wrong_block"


def mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), 4) if present else None


def _filter_cases(
    cases: list[dict],
    *,
    categories: list[str] | None = None,
    case_ids: list[str] | None = None,
    limit: int | None = None,
) -> list[dict]:
    category_set = {item.strip() for item in (categories or []) if item.strip()}
    id_set = {item.strip() for item in (case_ids or []) if item.strip()}
    selected = [
        case for case in cases
        if (not category_set or case.get("category") in category_set)
        and (not id_set or str(case.get("id")) in id_set)
    ]
    return selected[:limit] if limit else selected


def run(
    dataset_path: Path,
    output_dir: Path,
    top_k: int = 10,
    limit: int | None = None,
    backend: str = "chat",
    categories: list[str] | None = None,
    case_ids: list[str] | None = None,
) -> dict:
    container = build_container()
    cases = _filter_cases(
        json.loads(dataset_path.read_text(encoding="utf-8")),
        categories=categories,
        case_ids=case_ids,
        limit=limit,
    )

    per_case: list[dict] = []
    started = time.perf_counter()
    for index, case in enumerate(cases, start=1):
        question = case["question"]
        try:
            if backend == "chat":
                payload_obj = container.chat_service.answer(question, top_k=top_k)
                payload = {
                    "answer": payload_obj.answer,
                    "grounded": payload_obj.grounded,
                    "citations": [
                        {
                            "file_name": h.file_name,
                            "page_or_slide": h.page_or_slide,
                            "plain_text": h.plain_text,
                            "snippet": h.snippet,
                            "rerank_score": h.rerank_score,
                        }
                        for h in payload_obj.citations
                    ],
                    "latency_ms": payload_obj.latency_ms,
                    "question_type": payload_obj.question_type,
                }
            else:
                raise ValueError(f"unknown backend {backend}")
        except Exception as exc:  # keep the sweep alive on single-question failures
            payload = {"answer": f"ERROR: {exc}", "grounded": False, "citations": [], "latency_ms": -1}
        retrieval = judge_retrieval(payload.get("citations") or [], case.get("expected_evidence") or [])
        bucket = judge_answer(case, payload)
        per_case.append(
            {
                "id": case["id"],
                "category": case.get("category"),
                "expected_result_mode": case.get("expected_result_mode"),
                "bucket": bucket,
                "retrieval": retrieval,
                "answer": payload.get("answer"),
                "grounded": payload.get("grounded"),
                "latency_ms": payload.get("latency_ms"),
                "citations": [
                    {"file_name": c.get("file_name"), "page_or_slide": c.get("page_or_slide")}
                    for c in (payload.get("citations") or [])[:10]
                ],
            }
        )
        print(
            f"[{index}/{len(cases)}] {case['id']} {bucket} "
            f"R@5={retrieval['recall_5']} elapsed={int(time.perf_counter() - started)}s",
            flush=True,
        )

    def bucket_stats(subset: list[dict]) -> dict:
        buckets = {"answer_pass": 0, "correct_block": 0, "wrong_release": 0, "wrong_block": 0}
        for item in subset:
            buckets[item["bucket"]] += 1
        total = len(subset)
        answerable = buckets["answer_pass"] + buckets["wrong_release"]
        accuracy = round(buckets["answer_pass"] / answerable, 4) if answerable else None
        no_answer = [i for i in subset if i["expected_result_mode"] == "must_block"]
        correct_refusal = sum(1 for i in no_answer if i["bucket"] == "correct_block")
        return {
            **buckets,
            "total": total,
            "accuracy": accuracy,
            "hallucination_rate": round(buckets["wrong_release"] / total, 4) if total else None,
            "correct_refusal_rate": round(correct_refusal / len(no_answer), 4) if no_answer else None,
            "recall_3": mean([i["retrieval"]["recall_3"] for i in subset]),
            "recall_5": mean([i["retrieval"]["recall_5"] for i in subset]),
            "recall_10": mean([i["retrieval"]["recall_10"] for i in subset]),
            "mrr": mean([i["retrieval"]["mrr"] for i in subset]),
            "ndcg": mean([i["retrieval"]["ndcg"] for i in subset]),
            "avg_latency_ms": round(sum(i["latency_ms"] for i in subset if i["latency_ms"] >= 0) / max(1, len(subset)), 1),
        }

    overall = bucket_stats(per_case)
    by_category = {
        category: bucket_stats([item for item in per_case if item["category"] == category])
        for category in sorted({item["category"] for item in per_case})
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"rag_metrics_{timestamp}.json"
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "dataset": str(dataset_path),
        "targets": {
            "recall_5": 0.85,
            "recall_10": 0.92,
            "accuracy": 0.90,
            "correct_refusal_rate": 0.95,
            "hallucination_rate": 0.05,
        },
        "overall": overall,
        "by_category": by_category,
        "per_case": per_case,
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== RAG Metrics Summary ===")
    print(json.dumps({"overall": overall, "by_category": by_category}, ensure_ascii=False, indent=2))
    print(f"saved: {out_path}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Enterprise RAG quality metrics (Recall@k, accuracy, MRR, nDCG).")
    parser.add_argument("--dataset", default="data/evals/hard_eval_v1.json")
    parser.add_argument("--output-dir", default="data/evals/results")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--limit", type=int, default=None, help="Only run the first N cases (smoke).")
    parser.add_argument(
        "--category",
        action="append",
        dest="categories",
        help="Only run cases in this category; repeat for multiple categories.",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        dest="case_ids",
        help="Only run this case id; repeat for multiple ids.",
    )
    args = parser.parse_args()
    run(
        Path(args.dataset),
        Path(args.output_dir),
        top_k=args.top_k,
        limit=args.limit,
        categories=args.categories,
        case_ids=args.case_ids,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
