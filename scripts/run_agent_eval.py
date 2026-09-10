"""Agent-mode evaluation over the hard set + comparison against the single-turn link.

Runs the hard_eval_v1 questions through AgentService (chat path with routing:
simple -> fast path, complex -> agent loop) and produces the same enterprise
metric buckets as run_rag_metrics.py plus a side-by-side comparison against the
latest single-turn rag_metrics report.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# Local retrieval only (D-034: RAGFlow observations are phenomenon records).
os.environ.setdefault("RETRIEVAL_BACKEND", "local")

from run_rag_metrics import judge_answer, judge_retrieval  # noqa: E402

from app.main import build_container  # noqa: E402


def latest_rag_metrics(output_dir: Path) -> dict | None:
    files = sorted(glob.glob(str(output_dir / "rag_metrics_*.json")))
    if not files:
        return None
    return json.loads(Path(files[-1]).read_text(encoding="utf-8"))


def summarize(per_case: list[dict]) -> dict:
    buckets = {"answer_pass": 0, "correct_block": 0, "wrong_release": 0, "wrong_block": 0}
    for item in per_case:
        buckets[item["bucket"]] += 1
    total = len(per_case)
    answerable = buckets["answer_pass"] + buckets["wrong_release"]
    no_answer = [i for i in per_case if i["expected_result_mode"] == "must_block"]
    refused = sum(1 for i in no_answer if i["bucket"] == "correct_block")
    by_cat: dict[str, dict] = {}
    for item in per_case:
        cat = item["category"]
        stats = by_cat.setdefault(cat, {"total": 0, "answer_pass": 0, "wrong_release": 0, "wrong_block": 0, "correct_block": 0})
        stats["total"] += 1
        stats[item["bucket"]] += 1
    return {
        **buckets,
        "total": total,
        "accuracy": round(buckets["answer_pass"] / answerable, 4) if answerable else None,
        "hallucination_rate": round(buckets["wrong_release"] / total, 4) if total else None,
        "correct_refusal_rate": round(refused / len(no_answer), 4) if no_answer else None,
        "by_category": by_cat,
        "avg_latency_ms": round(sum(i["latency_ms"] for i in per_case if i["latency_ms"] >= 0) / max(1, len(per_case)), 1),
    }


def run(dataset_path: Path, output_dir: Path, limit: int | None = None, force_agent: bool = False) -> dict:
    container = build_container()
    agent_service = container.agent_service
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    if limit:
        cases = cases[:limit]

    per_case: list[dict] = []
    started = time.perf_counter()
    for index, case in enumerate(cases, start=1):
        question = case["question"]
        try:
            result = agent_service.query(question, force_agent=force_agent, persist=False)
            citations = result.citations or []
            answer_text = result.answer or ""
            grounded = bool(result.grounded)
            latency = result.latency_ms
            tools_used = result.tools_used
            steps = result.steps
        except Exception as exc:
            citations, answer_text, grounded, latency, tools_used, steps = [], f"ERROR: {exc}", False, -1, [], []
        retrieval = judge_retrieval(citations, case.get("expected_evidence") or [])
        bucket = judge_answer(case, {"answer": answer_text, "grounded": grounded, "citations": citations})
        per_case.append(
            {
                "id": case["id"],
                "category": case.get("category"),
                "expected_result_mode": case.get("expected_result_mode"),
                "bucket": bucket,
                "retrieval": retrieval,
                "answer": answer_text,
                "grounded": grounded,
                "latency_ms": latency,
                "tools_used": tools_used,
                "steps": steps,
                "citations": [{"file_name": c.get("file_name"), "page_or_slide": c.get("page_or_slide")} for c in citations[:10]],
            }
        )
        print(
            f"[{index}/{len(cases)}] {case['id']} {bucket} tools={','.join(tools_used[:2])} "
            f"{latency}ms elapsed={int(time.perf_counter() - started)}s",
            flush=True,
        )

    summary = summarize(per_case)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"agent_eval_{timestamp}.json"
    comparison = None
    baseline = latest_rag_metrics(output_dir)
    if baseline:
        base_overall = baseline.get("overall") or {}
        comparison = {
            "baseline_report": baseline.get("generated_at"),
            "baseline_single_turn": {
                "accuracy": base_overall.get("accuracy"),
                "hallucination_rate": base_overall.get("hallucination_rate"),
                "correct_refusal_rate": base_overall.get("correct_refusal_rate"),
                "recall_5": base_overall.get("recall_5"),
                "recall_10": base_overall.get("recall_10"),
                "mrr": base_overall.get("mrr"),
                "avg_latency_ms": base_overall.get("avg_latency_ms"),
            },
            "agent_mode": {k: v for k, v in summary.items() if k != "by_category"},
        }
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "dataset": str(dataset_path),
        "mode": "agent_forced" if force_agent else "agent_routed",
        "summary": summary,
        "comparison_with_single_turn": comparison,
        "per_case": per_case,
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== Agent Eval Summary ===")
    print(json.dumps({"summary": summary, "comparison": comparison}, ensure_ascii=False, indent=2)[:3000])
    print(f"saved: {out_path}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent-mode eval over the hard set with single-turn comparison.")
    parser.add_argument("--dataset", default="data/evals/hard_eval_v1.json")
    parser.add_argument("--output-dir", default="data/evals/results")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force-agent", action="store_true", help="Skip fast-path routing, run the agent loop for every question.")
    args = parser.parse_args()
    run(Path(args.dataset), Path(args.output_dir), limit=args.limit, force_agent=args.force_agent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
