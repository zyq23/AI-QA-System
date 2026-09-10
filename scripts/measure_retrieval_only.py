"""Retrieval-only A/B measurement on the hard set (no LLM, no ragflow route).

Usage:
  ./.venv/bin/python scripts/measure_retrieval_only.py --out data/evals/results/retrieval_local_only.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# Evidence is measured on the LOCAL index only (D-034: RAGFlow is phenomenon
# record, not capability evidence). Must be set BEFORE app.config import.
import os  # noqa: E402

os.environ["RETRIEVAL_BACKEND"] = "local"

logging.disable(logging.WARNING)

from run_rag_metrics import judge_retrieval  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.repositories import Repository  # noqa: E402
from app.domain import QueryAnalysis  # noqa: E402
from app.services.llm import LlmService  # noqa: E402
from app.services.ml import EmbeddingService, RerankerService  # noqa: E402
from app.services.retrieval import RetrievalService  # noqa: E402
from app.services.vector_store import VectorStoreService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/evals/hard_eval_v1.json")
    parser.add_argument("--out", default="data/evals/results/retrieval_local_only.json")
    parser.add_argument("--use-chat", action="store_true", help="use ChatService multi-query retrieval path")
    args = parser.parse_args()

    from app.main import build_container
    container = build_container()
    if args.use_chat:
        chat = container.chat_service
    else:
        s = get_settings()
        chat = None
        svc = RetrievalService(
            repository=Repository(Database(s.database_path)),
            embedding_service=EmbeddingService(s.resolved_embedding_model, use_stub=False),
            reranker_service=RerankerService(s.resolved_reranker_model, use_stub=False),
            vector_store=VectorStoreService(str(s.chroma_dir)),
            candidates=s.retrieval_candidates,
            default_top_k=10,
            retrieval_mode=s.retrieval_mode,
        )

    cases = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    t0 = time.time()
    per = []
    for i, case in enumerate(cases, 1):
        q = case["question"]
        if chat is not None:
            focus = chat.llm_service._extract_focus_terms(q)
            qtype = LlmService._infer_question_type(chat.llm_service, q)
            analysis = QueryAnalysis(rewritten_query=q, question_type=qtype, answer_focus="", focus_terms=focus)
            hits, grounded = chat._multi_query_retrieve(q, analysis, 10)
        else:
            focus = LlmService._extract_focus_terms(LlmService, q)
            result = svc.retrieve(q, top_k=10, focus_terms=focus)
            hits, grounded = result.hits, result.grounded
        cites = [
            {"file_name": h.file_name, "page_or_slide": h.page_or_slide, "plain_text": h.plain_text}
            for h in hits
        ]
        r = judge_retrieval(cites, case.get("expected_evidence") or [])
        per.append({"id": case["id"], "category": case["category"], "retrieval": r, "grounded": grounded})
        if i % 40 == 0:
            print(f"{i}/{len(cases)} {int(time.time() - t0)}s", flush=True)

    def mean(values):
        present = [v for v in values if v is not None]
        return round(sum(present) / len(present), 4) if present else None

    overall = {k: mean([c["retrieval"][k] for c in per]) for k in ("recall_3", "recall_5", "recall_10", "mrr", "ndcg")}
    by_cat = {}
    for cat in sorted({c["category"] for c in per}):
        sub = [c for c in per if c["category"] == cat]
        by_cat[cat] = {k: mean([c["retrieval"][k] for c in sub]) for k in ("recall_3", "recall_5", "recall_10", "mrr")}
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "retrieval_mode": get_settings().retrieval_mode,
        "path": "chat_multi_query" if chat is not None else "single_query",
        "overall": overall,
        "by_category": by_cat,
        "per_case": per,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"overall": overall, "by_category": by_cat}, ensure_ascii=False, indent=2))
    print(f"saved: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
