from __future__ import annotations

import logging
import re
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

    @staticmethod
    def _is_multi_subject_question(question: str) -> bool:
        """Cross-subject questions (compare/contrast/list-two) need evidence from
        MORE than one document or topic — a single fused top-k often collapses
        onto the subject that matches the most query tokens."""
        markers = ("区别", "分别", "对比", "有什么不同", "各自", "一起列出", "同时给出", "分别是什么", "各是")
        return any(marker in question for marker in markers)

    def _augment_multi_part_evidence(
        self,
        question: str,
        hits: list[RetrievalHit],
        top_k: int | None,
    ) -> list[RetrievalHit]:
        """Mine each decomposed claim independently before finalization.

        A fused query often lets one subject consume the whole candidate window;
        per-claim probes preserve evidence for every subject without changing
        the normal retrieval ranking for simple questions.
        """
        from app.services.claim_matrix import extract_claims, subject_probe_queries

        claims = extract_claims(question)
        if len(claims) < 2:
            return hits
        seen = {h.chunk_id for h in hits}
        extra: list[RetrievalHit] = []
        for subject, attribute in claims[:3]:
            queries = subject_probe_queries(subject) or [f"{subject} {attribute}".strip()]
            # Always include the natural claim query after alias-aware probes.
            queries.append(f"{subject} {attribute}".strip())
            # For experiment-environment-type attributes, also include the canonical
            # keyword (e.g. 'Jupyter Notebook') to surface document-specific chunks.
            for probe in queries[:6]:
                try:
                    sub = self.retrieval_service.retrieve(
                        probe,
                        top_k=max(4, min(6, (top_k or 10) // 2)),
                        focus_terms=None,
                    )
                    for hit in sub.hits:
                        if hit.chunk_id not in seen:
                            seen.add(hit.chunk_id)
                            extra.append(hit)
                except Exception as exc:
                    logger.debug("Claim probe failed for %s: %s", probe[:40], exc)
        if not extra:
            return hits
        # Append claim-probe evidence, preserving the primary ranking first.
        # The final matrix verifies each claim against the union and citations
        # retain file/page provenance for downstream evaluation.
        return list(hits) + extra[: max(0, (top_k or 10) * 4)]

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
        decompose = not primary.grounded or len(primary.hits) < 3 or self._is_multi_subject_question(question)
        if not decompose:
            return primary.hits, primary.grounded

        # Decompose complex questions into sub-queries
        sub_queries = self._decompose_question(question, analysis)
        if not sub_queries:
            return primary.hits, primary.grounded

        # Collect additional hits from sub-queries. Sub-queries are independent
        # questions: they must NOT inherit the parent's focus terms, otherwise
        # the parent's phrasing biases the reranker away from the sub-topic.
        seen_ids = {h.chunk_id for h in primary.hits}
        extra_hits: list[RetrievalHit] = []
        for sq in sub_queries[:4]:  # limit to 4 sub-queries
            try:
                sub_result = self.retrieval_service.retrieve(
                    sq, top_k=max(4, (top_k or 6) - 1),
                    focus_terms=None,
                )
                for hit in sub_result.hits:
                    if hit.chunk_id not in seen_ids:
                        seen_ids.add(hit.chunk_id)
                        extra_hits.append(hit)
            except Exception as exc:
                logger.warning("Sub-query retrieval failed for '%s': %s", sq[:40], exc)

        if not extra_hits:
            return primary.hits, primary.grounded

        # Multi-subject questions must not let ONE document own the whole top-k:
        # reserve half the slots for sub-query evidence and spread it across
        # documents (round-robin), so each subject's own evidence survives.
        if self._is_multi_subject_question(question):
            from app.services.retrieval_rules import expansion_terms_for
            rule_phrases = [p for p in expansion_terms_for(question) if len(p) >= 2]

            def merge_key(hit: RetrievalHit) -> tuple[float, float]:
                phrase_matches = sum(1 for p in rule_phrases if p.lower() in hit.plain_text.lower())
                return (hit.rerank_score + 1.2 * phrase_matches, hit.rerank_score)

            quota = max(2, (top_k or 6) // 2)
            merged = list(primary.hits[:quota])
            by_doc: dict[str, list[RetrievalHit]] = {}
            for hit in sorted(extra_hits, key=merge_key, reverse=True):
                by_doc.setdefault(hit.file_name, []).append(hit)
            doc_order = sorted(by_doc, key=lambda d: -merge_key(by_doc[d][0])[0])
            index = 0
            while len(merged) < (top_k or 6):
                added = False
                for doc in doc_order:
                    if index < len(by_doc[doc]):
                        merged.append(by_doc[doc][index])
                        added = True
                        if len(merged) >= (top_k or 6):
                            break
                if not added:
                    break
                index += 1
            # top up from the remaining primary hits if sub-queries were weak
            for hit in primary.hits:
                if len(merged) >= (top_k or 6):
                    break
                if hit.chunk_id not in {m.chunk_id for m in merged}:
                    merged.append(hit)
        else:
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

    # Window-pattern noun phrases worth a dedicated sub-query: "OCR中台页里通用大模型有哪些名称"
    # → group(1) is the subject (page/document window), group(2) the attribute ask.
    # The ATTRIBUTE is what the KB can match, so it becomes the sub-query.
    _SUBJECT_WINDOW_RE = re.compile(
        r"([\u4e00-\u9fffA-Za-z0-9+·]{2,14}?(?:页|中|里|内|文档|手册|方案))"
        r"[^，。？?；]{0,12}?"
        r"([四两三五六七八九\d]*[\u4e00-\u9fff]{0,10}?(?:是什么|有哪些|名称|电话|地址|服务|数量|多少|哪一|哪个|分别))"
    )
    _TAIL_STOP = ("以下", "下列", "以上", "只回答", "跳过", "忽略", "定位", "通读", "不是", "还是")

    @staticmethod
    def _clean_segment(seg: str) -> str:
        cleaned = re.sub(r"(什么|哪些|哪一|哪个|如何|怎么|区别|分别|对比|不同|各是|各自|列出|是多少|名称|信息)", "", seg).strip()
        return cleaned

    @staticmethod
    def _strip_instruction_words(question: str) -> str:
        """Remove navigation instructions (跳过X/只回答Y/忽略Z/定位第N页) that wrap
        hard questions; the remaining content is the actual ask."""
        cleaned = re.sub(r"(跳过|只回答|忽略|定位|通读|在[^，。？?；]{2,12}(?:长文档|文档|手册|方案)中?|第\s*\d+\s*页)", " ", question)
        return re.sub(r"\s+", " ", cleaned).strip(" ，。；、")

    def _decompose_question(self, question: str, analysis: QueryAnalysis) -> list[str]:
        """Decompose a complex question into simpler sub-queries.
        Uses heuristics for speed — no LLM call to avoid latency."""
        sub_queries: list[str] = []
        # Pattern 0-: quoted phrases ('X') are explicit subject hints the user gave.
        for quoted in re.findall(r"[‘'“]([^’'”]{2,20})[’'”]", question):
            if quoted not in sub_queries:
                sub_queries.append(quoted)
        # Pattern 0: cross-subject markers (区别/分别/对比) — split the two subjects
        # apart so each gets its own retrieval pass (fixes cross-document collapse).
        if self._is_multi_subject_question(question):
            # Extract the shared attribute ("核心设备"/"电话"/"配置"…) once so each
            # subject keeps its pairing: "机械臂 核心设备" retrieves the arm doc's
            # equipment chunk that a bare "机械臂" sub-query misses.
            attr_match = re.search(
                r"(核心设备|主要设备|核心组件|设备组成|电话|厂家|配置|参数|课程|专业|服务|价格|架构|定位|名称|指标)",
                question,
            )
            attribute = attr_match.group(1) if attr_match else ""
            # Split on comparison conjunctions and punctuation
            segments = re.split(r"[，,、；;。？?]|和|与|跟|分别|的区别|的对比|还有", question)
            for seg in segments:
                seg = seg.strip(" 的请把一起列出各自")
                if len(re.findall(r"[\u4e00-\u9fff]{2,}", seg)) >= 1 and len(seg) >= 2:
                    cleaned = self._clean_segment(seg)
                    if len(cleaned) >= 2 and cleaned not in sub_queries:
                        sub_queries.append(cleaned)
            # The attribute usually sits in ONE segment ("实训套件的核心设备"); pair it
            # with every OTHER subject segment too, otherwise each subject's dedicated
            # pass loses the attribute the KB chunk actually contains.
            if attribute:
                for seg in segments:
                    subject = self._clean_segment(seg.strip(" 的请把一起列出各自"))
                    if subject and attribute not in subject and subject not in attribute:
                        paired = f"{subject} {attribute}"
                        if paired not in sub_queries and len(paired) >= 4:
                            sub_queries.append(paired)
        # Pattern 0b: "subject(页/中/里) + attribute" long questions — retrieve the
        # attribute noun phrase itself, which is what the KB can actually match.
        for match in self._SUBJECT_WINDOW_RE.finditer(question):
            subject, attribute = match.group(1).strip(), match.group(2).strip()
            subject = self._strip_instruction_words(subject)
            attribute = self._strip_instruction_words(attribute)
            if not subject or not attribute:
                continue
            for phrase in (attribute, subject):
                if len(phrase) >= 2 and phrase not in sub_queries:
                    sub_queries.append(phrase)
            if len(sub_queries) >= 4:
                break
        # Pattern 0c: instruction-wrapped asks (只回答厂家电话 / 跳过目录…)：the
        # de-wrapped remainder is the retrievable ask.
        if not sub_queries:
            remainder = self._strip_instruction_words(question)
            if remainder and remainder != question and len(remainder) >= 3:
                sub_queries.append(remainder)
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
        # Pattern 3: definition-style sub-queries only help when the question is
        # itself a definition ask; for其它 factoid the raw noun phrases above are
        # already better sub-queries than arbitrary "X 是什么" fragments.
        if analysis.question_type == "summary" and len(question) > 15:
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
        hits = self._augment_multi_part_evidence(question, hits, top_k)
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
        focus_terms = self.llm_service._sanitize_focus_terms(
            self.llm_service._extract_focus_terms(question)
        )
        answer_focus = self.llm_service._build_answer_focus(question, question_type, focus_terms)
        return QueryAnalysis(
            rewritten_query=question,
            question_type=question_type,
            answer_focus=answer_focus,
            focus_terms=focus_terms,
            expansion_terms=[],
            used_fallback=True,
        )
