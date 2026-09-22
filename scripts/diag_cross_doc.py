#!/usr/bin/env python3
"""Diagnostic trace for cross-document retrieval failures.

Simulates the full retrieval pipeline (primary → decompose → sub-queries →
claim probes → merge → rerank → diversify → augment) for failing cases
and shows where each expected chunk is lost.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import build_container  # noqa: E402
from app.services.claim_matrix import extract_claims  # noqa: E402
from app.services.retrieval import RetrievalService  # noqa: E402
from app.domain import RetrievalHit  # noqa: E402


def trace_retrieval(question: str, top_k: int = 10, container=None):
    """Trace the full retrieval pipeline for a single question."""
    if container is None:
        container = build_container()

    chat = container.chat_service
    retrieval = container.retrieval_service
    repo = container.repository

    # --- Step 1: Rewrite + primary retrieval ---
    analysis = chat._heuristic_rewrite(question, [])
    print(f"  Rewritten: {analysis.rewritten_query}")
    print(f"  Focus terms: {analysis.focus_terms}")
    print(f"  Expansion terms: {analysis.expansion_terms}")

    primary = retrieval.retrieve(question, top_k=top_k, focus_terms=analysis.focus_terms, expansion_terms=analysis.expansion_terms)
    print(f"\n  Primary hits ({len(primary.hits)}):")
    for i, h in enumerate(primary.hits[:10]):
        print(f"    [{i+1}] {h.file_name} | {h.page_or_slide} | rerank={h.rerank_score:.2f} | fusion={h.fusion_score:.3f} | '{h.plain_text[:60]}'")

    # --- Step 2: Decomposition ---
    is_multi = chat._is_multi_subject_question(question)
    sub_queries = chat._decompose_question(question, analysis) if (is_multi or len(primary.hits) < 3 or not primary.grounded) else []
    print(f"\n  Multi-subject: {is_multi}")
    print(f"  Sub-queries: {sub_queries}")

    # --- Step 3: Sub-query retrieval ---
    sub_results = {}
    for sq in sub_queries[:4]:
        sub_r = retrieval.retrieve(sq, top_k=max(4, (top_k or 6) - 1), focus_terms=None)
        sub_results[sq] = sub_r.hits[:5]
        print(f"\n  Sub-query '{sq}' hits ({len(sub_r.hits)}):")
        for i, h in enumerate(sub_r.hits[:5]):
            print(f"    [{i+1}] {h.file_name} | {h.page_or_slide} | rerank={h.rerank_score:.2f} | fusion={h.fusion_score:.3f} | '{h.plain_text[:60]}'")

    # --- Step 4: Claim matrix ---
    claims = extract_claims(question)
    print(f"\n  Claims: {claims}")
    claim_extra = {}
    if len(claims) >= 2:
        from app.services.claim_matrix import subject_probe_queries, _base_subject_key
        seen_ids = {h.chunk_id for h in primary.hits}
        for sub_query_sq in sub_queries[:4]:
            for hit in sub_results.get(sub_query_sq, []):
                seen_ids.add(hit.chunk_id)

        for subject, attribute in claims[:3]:
            probes = [f"{subject} {attribute}".strip()]
            probes.extend(subject_probe_queries(subject) or [])
            base = _base_subject_key(subject)
            if base != subject:
                probes.append(f"{base} {attribute}".strip())
            probes.append(subject)
            probes = list(dict.fromkeys(q for q in probes if q.strip()))

            claim_extra[subject] = {}
            for probe in probes[:8]:
                try:
                    sub_r = retrieval.retrieve(probe, top_k=max(4, min(6, (top_k or 10) // 2)), focus_terms=None)
                    claim_extra[subject][probe] = sub_r.hits[:4]
                    print(f"\n  Claim probe '{probe}' hits ({len(sub_r.hits)}):")
                    for i, h in enumerate(sub_r.hits[:4]):
                        print(f"    [{i+1}] {h.file_name} | {h.page_or_slide} | rerank={h.rerank_score:.2f} | fusion={h.fusion_score:.3f} | '{h.plain_text[:60]}'")
                except Exception as exc:
                    print(f"    Claim probe '{probe}' ERROR: {exc}")

    # --- Step 5: Full pipeline result ---
    hits, grounded = chat._multi_query_retrieve(question, analysis, top_k)
    print(f"\n  Final hits after merge ({len(hits)}):")
    for i, h in enumerate(hits):
        print(f"    [{i+1}] {h.file_name} | {h.page_or_slide} | rerank={h.rerank_score:.2f} | fusion={h.fusion_score:.3f} | '{h.plain_text[:60]}'")

    # --- Step 6: After augmentation ---
    augmented = chat._augment_multi_part_evidence(question, hits, top_k)
    print(f"\n  After augmentation ({len(augmented)}):")
    for i, h in enumerate(augmented):
        print(f"    [{i+1}] {h.file_name} | {h.page_or_slide} | rerank={h.rerank_score:.2f} | fusion={h.fusion_score:.3f} | '{h.plain_text[:60]}'")

    return {
        "primary": primary.hits,
        "sub_queries": sub_queries,
        "sub_results": sub_results,
        "claims": claims,
        "claim_extra": claim_extra,
        "merged": hits,
        "augmented": augmented,
        "grounded": grounded,
    }


def main():
    failing_cases = [
        "hard-cross-06",
        "hard-cross-09",
        "hard-cross-13",
        "hard-cross-15",
    ]

    # Load expected evidence
    dataset_path = Path("data/evals/cross_doc_eval_v1.json")
    cases = {c["id"]: c for c in json.loads(dataset_path.read_text())}

    container = build_container()

    for case_id in failing_cases:
        case = cases[case_id]
        print(f"\n{'='*80}")
        print(f"  {case_id}: {case['question']}")
        print(f"  Expected files: {case.get('expected_files', [])}")
        print(f"  Expected evidence pages: {[e.get('page_or_slide') for e in case.get('expected_evidence', [])]}")
        print(f"{'='*80}")
        trace_retrieval(case["question"], top_k=10, container=container)


if __name__ == "__main__":
    main()
