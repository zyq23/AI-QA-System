"""Fast iteration harness for the multi-part hard questions.

Runs ONLY the cross_document + multi_hop must_answer questions through
chat_service.answer() and prints the matrix claims + final answer + judged
bucket. This lets us iterate on claim_matrix patterns and answer trimming in
seconds instead of waiting ~15 min for the full 130-question sweep.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import build_container
from app.services.claim_matrix import compose_multi_part_answer, extract_claims
from scripts.run_rag_metrics import judge_answer

DATASET = ROOT / "data/evals/hard_eval_v1.json"
INTEREST = {
    "hard-cross-01", "hard-cross-02", "hard-cross-03", "hard-cross-04",
    "hard-cross-05", "hard-cross-06", "hard-cross-07", "hard-cross-08",
    "hard-cross-09", "hard-cross-11", "hard-cross-12", "hard-cross-13",
    "hard-multihop-01", "hard-multihop-03", "hard-multihop-06", "hard-multihop-07",
    "hard-multihop-08", "hard-multihop-09", "hard-multihop-13", "hard-multihop-15",
}


def main(limit: int = 0) -> None:
    container = build_container()
    chat = container.chat_service
    cases = [c for c in json.loads(DATASET.read_text(encoding="utf-8")) if c["id"] in INTEREST]
    if limit:
        cases = cases[:limit]
    for case in cases:
        q = case["question"]
        claims = extract_claims(q)
        result = chat.answer(q, top_k=10)
        payload = {
            "answer": result.answer,
            "grounded": result.grounded,
            "citations": [
                {"file_name": h.file_name, "page_or_slide": h.page_or_slide}
                for h in (result.citations or [])[:10]
            ],
        }
        bucket = judge_answer(case, payload)
        kws = " / ".join(case.get("expected_answer_keywords") or [])
        print(f"[{case['id']}] bucket={bucket}")
        print(f"   Q: {q}")
        print(f"   claims={claims}")
        print(f"   exp_kw: {kws}")
        print(f"   ans: {result.answer[:220]}")
        if len(result.answer) > 220:
            print(f"        ...{result.answer[220:440]}")
        print()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    main(args.limit)