"""Dump top citation plain_text for a set of questions (read-only debug).

Usage:
  EVAL_API_BASE_URL= RETRIEVAL_BACKEND=local ./.venv/bin/python \
    scripts/dump_wr_citations.py hard-cross-04 hard-synonym-01 ...
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import build_container  # noqa: E402

if __name__ == "__main__":
    ids = sys.argv[1:]
    dataset = json.loads(Path("data/evals/hard_eval_v1.json").read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in dataset}
    container = build_container()
    for cid in ids:
        case = cases[cid]
        q = case["question"]
        print(f"\n{'='*100}")
        print(f"### {cid}: {q}")
        print(f"expected_keywords: {case.get('expected_answer_keywords')}")
        payload = container.chat_service.answer(q, top_k=8)
        print(f"ANSWER(grounded={payload.grounded}): {payload.answer[:300]}")
        for i, h in enumerate(payload.citations[:8]):
            text = (h.plain_text or h.snippet or "").replace("\n", " ")[:400]
            print(f"  [{i}] {h.file_name[:50]} | {h.page_or_slide} | {h.section_path[:40]}")
            print(f"      {text}")
