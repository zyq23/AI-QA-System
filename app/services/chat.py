from __future__ import annotations

import logging
import time

from app.domain import AnswerPayload, QueryAnalysis, RetrievalHit
from app.repositories import Repository
from app.services.llm import LlmService
from app.services.retrieval import RetrievalService

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(
        self,
        repository: Repository,
        retrieval_service: RetrievalService,
        llm_service: LlmService,
        history_turns: int = 2,
    ) -> None:
        self.repository = repository
        self.retrieval_service = retrieval_service
        self.llm_service = llm_service
        self.history_turns = history_turns

    def _multi_query_retrieve(
        self,
        question: str,
        analysis: QueryAnalysis,
        top_k: int | None,
    ) -> tuple[list[RetrievalHit], bool]:
        """Multi-query retrieval: if primary retrieval is not grounded or
        has low citation diversity, try decomposing the question into
        sub-queries and merge results via dedup + rerank."""
        primary = self.retrieval_service.retrieve(
            analysis.rewritten_query,
            top_k=top_k,
            focus_terms=analysis.focus_terms,
            expansion_terms=analysis.expansion_terms,
        )
        if primary.grounded and len(primary.hits) >= 3:
            return primary.hits, primary.grounded

        # Decompose complex questions into sub-queries
        sub_queries = self._decompose_question(question, analysis)
        if not sub_queries:
            return primary.hits, primary.grounded

        # Collect additional hits from sub-queries
        seen_ids = {h.chunk_id for h in primary.hits}
        extra_hits: list[RetrievalHit] = []
        for sq in sub_queries[:3]:  # limit to 3 sub-queries
            try:
                sub_result = self.retrieval_service.retrieve(
                    sq, top_k=max(3, (top_k or 6) // 2),
                    focus_terms=analysis.focus_terms,
                )
                for hit in sub_result.hits:
                    if hit.chunk_id not in seen_ids:
                        seen_ids.add(hit.chunk_id)
                        extra_hits.append(hit)
            except Exception as exc:
                logger.warning("Sub-query retrieval failed for '%s': %s", sq[:40], exc)

        if not extra_hits:
            return primary.hits, primary.grounded

        # Merge: primary hits first, then extra hits by rerank_score
        merged = list(primary.hits)
        extra_sorted = sorted(extra_hits, key=lambda h: h.rerank_score, reverse=True)
        merged.extend(extra_sorted[: (top_k or 6) - len(merged)])
        # Re-evaluate grounding with merged set
        merged_grounded = primary.grounded
        if not merged_grounded and len(merged) >= 3:
            # Check if merged set has better coverage
            from app.services.retrieval import RetrievalService
            merged_grounded = RetrievalService._grounded(question, merged, analysis.focus_terms)
        return merged, merged_grounded

    def _decompose_question(self, question: str, analysis: QueryAnalysis) -> list[str]:
        """Decompose a complex question into simpler sub-queries.
        Uses heuristics for speed — no LLM call to avoid latency."""
        sub_queries: list[str] = []
        # Pattern 1: questions with "除了...还" (besides X, what else)
        if "除了" in question and ("还" in question or "有" in question):
            # Extract the "besides" part and create a direct query
            parts = question.split("除了", 1)
            if len(parts) == 2:
                after = parts[1].split("还", 1)[0].split("有", 1)[0].strip("，、 ")
                if after and len(after) >= 2:
                    sub_queries.append(after)
        # Pattern 2: questions with multiple focus terms — split by conjunction
        if analysis.focus_terms and len(analysis.focus_terms) >= 3:
            for term in analysis.focus_terms[:3]:
                if term and len(term) >= 2 and term not in question:
                    sub_queries.append(f"{term} 是什么")
        # Pattern 3: summary/concept questions — add a "definition" sub-query
        if analysis.question_type in {"summary", "factoid"} and len(question) > 15:
            # Extract core noun phrase for a definition lookup
            import re
            nouns = re.findall(r"[\u4e00-\u9fff]{3,8}", question)
            for noun in nouns[:2]:
                if noun not in sub_queries:
                    sub_queries.append(f"{noun} 是什么")
        return [sq for sq in sub_queries if sq and len(sq) >= 3][:4]

    def answer(
        self,
        question: str,
        conversation_id: str | None = None,
        top_k: int | None = None,
        *,
        skip_llm_rewrite: bool = False,
        robot_mode: bool = False,
    ) -> AnswerPayload:
        started = time.perf_counter()
        conversation_id = self.repository.ensure_conversation(conversation_id)
        history_messages = self.repository.get_recent_turn_context(conversation_id, self.history_turns)

        if skip_llm_rewrite:
            analysis = self._heuristic_rewrite(question, history_messages)
        else:
            analysis = self.llm_service.rewrite_query(question, history_messages)

        retrieval_started = time.perf_counter()
        hits, grounded = self._multi_query_retrieve(question, analysis, top_k)
        latency_retrieval_ms = int((time.perf_counter() - retrieval_started) * 1000)

        generate_started = time.perf_counter()
        draft = self.llm_service.generate_answer(
            question, analysis, hits, grounded,
            robot_mode=robot_mode,
        )
        latency_generate_ms = int((time.perf_counter() - generate_started) * 1000)

        review_started = time.perf_counter()
        review = self.llm_service.review_answer(
            question, analysis, hits, draft,
            robot_mode=robot_mode,
        )
        latency_review_ms = int((time.perf_counter() - review_started) * 1000)

        llm_payload = self.llm_service.finalize_answer(question, analysis, hits, draft, review)
        latency_ms = int((time.perf_counter() - started) * 1000)

        answer_run_id = self.repository.create_answer_run(
            conversation_id=conversation_id,
            question=question,
            rewritten_query=analysis.rewritten_query,
            question_type=analysis.question_type,
            answer_focus=analysis.answer_focus,
            retrieval={
                "grounded": grounded,
                "focus_terms": analysis.focus_terms,
                "expanded_query": analysis.rewritten_query,
                "expansion_terms": analysis.expansion_terms,
                "used_fallback": False,
                "fallback_reason": "",
                "hits": [self.repository.serialize_hit(hit) for hit in hits],
            },
            draft={
                "answer": draft.answer,
                "grounded_answer": draft.grounded_answer,
                "inference_note": draft.inference_note,
                "question_type": draft.question_type,
                "answer_focus": draft.answer_focus,
                "grounded": draft.grounded,
                "confidence_note": draft.confidence_note,
                "used_fallback": draft.used_fallback,
                "raw_payload": draft.raw_payload,
            },
            review={
                "passed": review.passed,
                "issues": review.issues,
                "revised_answer": review.revised_answer,
                "revised_grounded_answer": review.revised_grounded_answer,
                "revised_inference_note": review.revised_inference_note,
                "risk_level": review.risk_level,
                "reviewer_intervened": review.reviewer_intervened,
                "raw_payload": review.raw_payload,
            },
            final_answer=str(llm_payload["answer"]),
            final_grounded_answer=str(llm_payload["grounded_answer"]),
            final_inference_note=str(llm_payload["inference_note"]),
            final_grounded=bool(llm_payload["grounded"]),
            stage_status="completed",
            failure_stage=None,
            latency_total_ms=latency_ms,
            latency_retrieval_ms=latency_retrieval_ms,
            latency_generate_ms=latency_generate_ms,
            latency_review_ms=latency_review_ms,
        )

        self.repository.add_message(conversation_id, "user", question)
        self.repository.add_message(
            conversation_id,
            "assistant",
            llm_payload["answer"],
            grounded=bool(llm_payload["grounded"]),
            citations=[self.repository.serialize_hit(hit) for hit in hits],
        )
        return AnswerPayload(
            conversation_id=conversation_id,
            answer=str(llm_payload["answer"]),
            grounded_answer=str(llm_payload["grounded_answer"]),
            inference_note=str(llm_payload["inference_note"]),
            grounded=bool(llm_payload["grounded"]),
            citations=hits,
            rewritten_query=analysis.rewritten_query,
            latency_ms=latency_ms,
            question_type=str(llm_payload.get("question_type", analysis.question_type)),
            answer_focus=str(llm_payload.get("answer_focus", analysis.answer_focus)),
            answer_run_id=answer_run_id,
            review_issues=list(llm_payload.get("review_issues", [])),
            reviewer_intervened=bool(llm_payload.get("reviewer_intervened", False)),
            fallback_used=bool(llm_payload.get("fallback_used", False)),
        )

    def _heuristic_rewrite(self, question: str, history_messages: list[dict]) -> QueryAnalysis:
        """Fast heuristic rewrite for robot/voice scenarios — no LLM call."""
        # Delegate to LlmService's existing heuristic methods
        question_type = self.llm_service._infer_question_type(question, history_messages)
        focus_terms = self.llm_service._extract_focus_terms(question)
        answer_focus = self.llm_service._build_answer_focus(question, question_type, focus_terms)
        return QueryAnalysis(
            rewritten_query=question,
            question_type=question_type,
            answer_focus=answer_focus,
            focus_terms=focus_terms,
            expansion_terms=[],
            used_fallback=True,
        )
