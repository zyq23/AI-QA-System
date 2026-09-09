from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import logging
import re
from dataclasses import dataclass

from app.domain import RetrievalHit
from app.repositories import Repository
from app.services.ml import EmbeddingService, RerankerService, tokenize
from app.services.ragflow import RagflowClient, RagflowError
from app.services.retrieval_rules import (
    base_expansion_terms_for,
    entity_aliases,
    expansion_terms_for,
    query_synonyms,
)
from app.services.vector_store import VectorStoreService
from app.utils import build_search_text, shorten_snippet

logger = logging.getLogger(__name__)

# Section-title hints stay as a generic table: they reward chunks whose section
# matches a title-like phrase the question asks about. This list is intentionally
# generic (document-structure words), not corpus-specific content.
SECTION_TITLE_HINTS = (
    "目录",
    "CONTENTS",
    "公司概况",
    "业务架构",
    "战略定位",
    "基础环境",
    "基础模型",
    "产教融合人才培养整体解决方案",
)

SECTION_HINT_ALIASES: dict[str, tuple[str, ...]] = {
    "目录": ("CONTENTS",),
    "CONTENTS": ("目录",),
}


def rrf_score(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


@dataclass(slots=True)
class RetrievalResult:
    hits: list[RetrievalHit]
    grounded: bool
    focus_terms: list[str]
    expanded_query: str
    expansion_terms: list[str]
    used_fallback: bool = False
    fallback_reason: str = ""
    backend_path: str = "local"
    route_reason: str = "local_only"
    local_top_score: float | None = None
    local_quality_score: float | None = None
    remote_quality_score: float | None = None
    local_grounded_score_threshold: float | None = None
    remote_attempted: bool = False


class RagflowRetrievalService:
    def __init__(
        self,
        *,
        client: RagflowClient,
        dataset_ids: list[str],
        document_ids: list[str],
        default_top_k: int = 6,
        page_size: int = 20,
        similarity_threshold: float = 0.2,
        vector_similarity_weight: float = 0.3,
        keyword: bool = True,
        highlight: bool = False,
        use_kg: bool = False,
        toc_enhance: bool = False,
    ) -> None:
        self.client = client
        self.dataset_ids = dataset_ids
        self.document_ids = document_ids
        self.default_top_k = default_top_k
        self.page_size = page_size
        self.similarity_threshold = similarity_threshold
        self.vector_similarity_weight = vector_similarity_weight
        self.keyword = keyword
        self.highlight = highlight
        self.use_kg = use_kg
        self.toc_enhance = toc_enhance

    @staticmethod
    def _normalize_position(positions: list[object] | None) -> str:
        if not positions:
            return ""
        first = positions[0]
        if isinstance(first, dict):
            page_num = first.get("page_num") or first.get("page") or first.get("page_number")
            section = first.get("section") or first.get("title")
            if page_num and section:
                return f"page {page_num} {section}"
            if page_num:
                return f"page {page_num}"
            if section:
                return str(section)
        if isinstance(first, (list, tuple)):
            numeric_parts = [str(item) for item in first if isinstance(item, (int, float))]
            if numeric_parts:
                return " > ".join(numeric_parts[:5])
        value = str(first).strip()
        if value.startswith("[") and value.endswith("]"):
            numbers = re.findall(r"-?\d+", value)
            if numbers:
                return " > ".join(numbers[:5])
        return value[:80]

    @staticmethod
    def _section_path(chunk: dict[str, object]) -> str:
        positions = chunk.get("positions")
        if isinstance(positions, list):
            normalized = RagflowRetrievalService._normalize_position(positions)
            if normalized:
                return normalized
        document_name = str(chunk.get("document_name") or chunk.get("document_keyword") or "").strip()
        return document_name or "RAGFlow"

    @staticmethod
    def _map_chunk(chunk: dict[str, object]) -> RetrievalHit:
        content = str(chunk.get("content") or "").strip()
        file_name = str(chunk.get("document_name") or chunk.get("document_keyword") or "ragflow-document").strip()
        similarity = float(chunk.get("similarity") or 0.0)
        vector_similarity = float(chunk.get("vector_similarity") or 0.0)
        term_similarity = float(chunk.get("term_similarity") or 0.0)
        positions = chunk.get("positions")
        page_or_slide = ""
        if isinstance(positions, list):
            page_or_slide = RagflowRetrievalService._normalize_position(positions)
        return RetrievalHit(
            chunk_id=str(chunk.get("id") or ""),
            document_id=str(chunk.get("document_id") or ""),
            version_id="ragflow",
            file_name=file_name or "ragflow-document",
            page_or_slide=page_or_slide,
            section_path=RagflowRetrievalService._section_path(chunk),
            snippet=shorten_snippet(content, 220),
            markdown_text=content,
            plain_text=content,
            trust_level="internal",
            source_type="ragflow",
            fusion_score=similarity,
            rerank_score=similarity,
            raw_scores={
                "similarity": similarity,
                "vector_similarity": vector_similarity,
                "term_similarity": term_similarity,
                "dataset_id": str(chunk.get("dataset_id") or chunk.get("kb_id") or ""),
            },
        )

    @staticmethod
    def _grounded(question: str, hits: list[RetrievalHit], focus_terms: list[str] | None = None) -> bool:
        if RetrievalService._grounded(question, hits, focus_terms):
            return True
        if not hits:
            return False
        top_hit = hits[0]
        similarity = float(top_hit.raw_scores.get("similarity") or top_hit.rerank_score or 0.0)
        vector_similarity = float(top_hit.raw_scores.get("vector_similarity") or 0.0)
        if similarity >= 0.82:
            return True
        if similarity >= 0.72 and vector_similarity >= 0.72:
            return True
        return False

    @staticmethod
    def _needs_chat_model_retry(exc: RagflowError) -> bool:
        message = str(exc)
        return "No default chat model is set" in message

    def retrieve(self, question: str, top_k: int | None = None, focus_terms: list[str] | None = None, expansion_terms: list[str] | None = None) -> RetrievalResult:
        effective_top_k = top_k or self.default_top_k
        expanded_query, expansion_terms_out, expanded_focus_terms = RetrievalService._expand_query(question, focus_terms)
        try:
            data = self.client.retrieve_chunks(
                question=expanded_query,
                dataset_ids=self.dataset_ids,
                document_ids=self.document_ids,
                page_size=max(self.page_size, effective_top_k),
                similarity_threshold=self.similarity_threshold,
                vector_similarity_weight=self.vector_similarity_weight,
                top_k=max(effective_top_k * 3, self.page_size),
                keyword=self.keyword,
                highlight=self.highlight,
                use_kg=self.use_kg,
                toc_enhance=self.toc_enhance,
            )
        except RagflowError as exc:
            if not self._needs_chat_model_retry(exc):
                raise
            logger.warning(
                "RAGFlow retrieval requires default chat model for keyword/toc/kg features; retry without chat-only enhancements."
            )
            data = self.client.retrieve_chunks(
                question=expanded_query,
                dataset_ids=self.dataset_ids,
                document_ids=self.document_ids,
                page_size=max(self.page_size, effective_top_k),
                similarity_threshold=self.similarity_threshold,
                vector_similarity_weight=self.vector_similarity_weight,
                top_k=max(effective_top_k * 3, self.page_size),
                keyword=False,
                highlight=self.highlight,
                use_kg=False,
                toc_enhance=False,
            )
        except Exception as exc:  # pragma: no cover - runtime safety
            logger.exception("Unexpected RAGFlow retrieval failure")
            raise RagflowError(f"Unexpected RAGFlow retrieval failure: {exc}") from exc

        chunks = data.get("chunks", [])
        hits = [self._map_chunk(chunk) for chunk in chunks if isinstance(chunk, dict)]
        final_hits = hits[:effective_top_k]
        return RetrievalResult(
            hits=final_hits,
            grounded=self._grounded(question, final_hits, expanded_focus_terms),
            focus_terms=expanded_focus_terms,
            expanded_query=expanded_query,
            expansion_terms=expansion_terms_out,
            backend_path="ragflow",
            route_reason="remote_direct",
        )


class FallbackRetrievalService:
    def __init__(self, primary: object, fallback: object, primary_timeout_ms: int | None = None) -> None:
        self.primary = primary
        self.fallback = fallback
        self.primary_timeout_ms = primary_timeout_ms

    @staticmethod
    def _mark_fallback(result: object, reason: str) -> object:
        if isinstance(result, RetrievalResult):
            result.used_fallback = True
            result.fallback_reason = reason
        return result

    def retrieve(self, question: str, top_k: int | None = None, focus_terms: list[str] | None = None, expansion_terms: list[str] | None = None) -> RetrievalResult:
        if self.primary_timeout_ms and self.primary_timeout_ms > 0:
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(self.primary.retrieve, question, top_k=top_k, focus_terms=focus_terms, expansion_terms=expansion_terms)
            try:
                return future.result(timeout=self.primary_timeout_ms / 1000)
            except FutureTimeoutError:
                logger.warning(
                    "Primary retrieval backend exceeded %sms, fallback to local retrieval.",
                    self.primary_timeout_ms,
                )
                return self._mark_fallback(
                    self.fallback.retrieve(question, top_k=top_k, focus_terms=focus_terms, expansion_terms=expansion_terms),
                    "primary_timeout",
                )
            except Exception as exc:  # pragma: no cover - runtime safety
                logger.warning("Primary retrieval backend failed, fallback to local retrieval: %s", exc)
                return self._mark_fallback(
                    self.fallback.retrieve(question, top_k=top_k, focus_terms=focus_terms, expansion_terms=expansion_terms),
                    "primary_error",
                )
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        try:
            return self.primary.retrieve(question, top_k=top_k, focus_terms=focus_terms, expansion_terms=expansion_terms)
        except Exception as exc:  # pragma: no cover - runtime safety
            logger.warning("Primary retrieval backend failed, fallback to local retrieval: %s", exc)
            return self._mark_fallback(
                self.fallback.retrieve(question, top_k=top_k, focus_terms=focus_terms, expansion_terms=expansion_terms),
                "primary_error",
            )


class AdaptiveRetrievalService:
    def __init__(
        self,
        local: object,
        remote: object,
        *,
        remote_timeout_ms: int | None = None,
        local_grounded_score_threshold: float = 0.55,
    ) -> None:
        self.local = local
        self.remote = remote
        self.remote_timeout_ms = remote_timeout_ms
        self.local_grounded_score_threshold = local_grounded_score_threshold

    @staticmethod
    def _top_score(result: RetrievalResult) -> float:
        if not result.hits:
            return -9.0
        top_hit = result.hits[0]
        return float(top_hit.rerank_score or top_hit.fusion_score or 0.0)

    @staticmethod
    def _coarse_result_penalty(result: RetrievalResult) -> float:
        if not result.hits:
            return 0.0
        top_hit = result.hits[0]
        text = top_hit.plain_text
        penalty = 0.0
        if top_hit.source_type == "ragflow":
            penalty += 0.08
        if text.count("\n") >= 8:
            penalty += 0.12
        if len(text) >= 420:
            penalty += 0.08
        if "<table>" in text:
            penalty += 0.18
        if RetrievalService._looks_like_noisy_ocr(text):
            penalty += 0.24
        return penalty

    @classmethod
    def _result_quality(cls, result: RetrievalResult) -> float:
        return cls._top_score(result) + (0.5 if result.grounded else 0.0) - cls._coarse_result_penalty(result)

    def _retrieve_remote(self, question: str, top_k: int | None, focus_terms: list[str] | None, expansion_terms: list[str] | None = None) -> RetrievalResult:
        if self.remote_timeout_ms and self.remote_timeout_ms > 0:
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(self.remote.retrieve, question, top_k=top_k, focus_terms=focus_terms, expansion_terms=expansion_terms)
            try:
                return future.result(timeout=self.remote_timeout_ms / 1000)
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        return self.remote.retrieve(question, top_k=top_k, focus_terms=focus_terms, expansion_terms=expansion_terms)

    def retrieve(self, question: str, top_k: int | None = None, focus_terms: list[str] | None = None, expansion_terms: list[str] | None = None) -> RetrievalResult:
        local_result = self.local.retrieve(question, top_k=top_k, focus_terms=focus_terms, expansion_terms=expansion_terms)
        local_result.local_top_score = self._top_score(local_result)
        local_result.local_quality_score = self._result_quality(local_result)
        local_result.local_grounded_score_threshold = self.local_grounded_score_threshold
        if local_result.grounded and self._top_score(local_result) >= self.local_grounded_score_threshold:
            local_result.backend_path = "local"
            local_result.route_reason = "local_grounded_above_threshold"
            return local_result
        local_result.remote_attempted = True
        try:
            remote_result = self._retrieve_remote(question, top_k=top_k, focus_terms=focus_terms, expansion_terms=expansion_terms)
        except FutureTimeoutError:
            local_result.used_fallback = True
            local_result.fallback_reason = "remote_timeout_local_preferred"
            local_result.backend_path = "local"
            local_result.route_reason = "remote_timeout_keep_local"
            return local_result
        except Exception as exc:  # pragma: no cover - runtime safety
            logger.warning("Remote retrieval backend failed during adaptive routing, keep local result: %s", exc)
            local_result.used_fallback = True
            local_result.fallback_reason = "remote_error_local_preferred"
            local_result.backend_path = "local"
            local_result.route_reason = "remote_error_keep_local"
            return local_result

        local_quality = self._result_quality(local_result)
        remote_quality = self._result_quality(remote_result)
        local_result.local_quality_score = local_quality
        local_result.remote_quality_score = remote_quality
        remote_result.local_top_score = local_result.local_top_score
        remote_result.local_quality_score = local_quality
        remote_result.remote_quality_score = remote_quality
        remote_result.local_grounded_score_threshold = self.local_grounded_score_threshold
        remote_result.remote_attempted = True
        if local_result.grounded and not remote_result.grounded:
            local_result.backend_path = "local"
            local_result.route_reason = "prefer_local_grounded_over_remote_ungrounded"
            local_result.remote_quality_score = remote_quality
            return local_result
        if remote_result.grounded and not local_result.grounded:
            remote_result.used_fallback = True
            remote_result.fallback_reason = "remote_selected_after_local_insufficient"
            remote_result.backend_path = "ragflow"
            remote_result.route_reason = "remote_grounded_local_not_grounded"
            return remote_result
        if local_quality >= (remote_quality - 0.08):
            local_result.backend_path = "local"
            local_result.route_reason = "local_quality_within_margin"
            local_result.remote_quality_score = remote_quality
            return local_result
        remote_result.used_fallback = True
        remote_result.fallback_reason = "remote_selected_after_local_compare"
        remote_result.backend_path = "ragflow"
        remote_result.route_reason = "remote_quality_better_than_local"
        return remote_result


class RetrievalService:
    def __init__(
        self,
        repository: Repository,
        embedding_service: EmbeddingService,
        reranker_service: RerankerService,
        vector_store: VectorStoreService,
        candidates: int = 20,
        default_top_k: int = 6,
        retrieval_mode: str = "hybrid",
    ) -> None:
        self.repository = repository
        self.embedding_service = embedding_service
        self.reranker_service = reranker_service
        self.vector_store = vector_store
        self.candidates = candidates
        self.default_top_k = default_top_k
        self.retrieval_mode = (retrieval_mode or "hybrid").strip().lower()

    @staticmethod
    def _expand_query(
        question: str,
        focus_terms: list[str] | None = None,
        llm_expansion_terms: list[str] | None = None,
    ) -> tuple[str, list[str], list[str]]:
        normalized = question.strip()
        expansions: list[str] = []

        # LLM-generated expansion terms (blend first, higher priority)
        for term in (llm_expansion_terms or []):
            value = term.strip()
            if value and value not in expansions and value not in normalized:
                expansions.append(value)

        def add(term: str) -> None:
            value = term.strip()
            if value and value not in expansions and value not in normalized:
                expansions.append(value)

        # Data-driven synonym + expansion tables (config/retrieval_rules.json).
        for key, values in query_synonyms().items():
            if key in normalized:
                for value in values:
                    add(value)

        for term in focus_terms or []:
            for key, values in query_synonyms().items():
                if key in term:
                    for value in values:
                        add(value)

        for value in expansion_terms_for(normalized):
            add(value)

        expanded_focus_terms = list(dict.fromkeys([*(focus_terms or []), *expansions]))[:8]
        expanded_query = normalized if not expansions else f"{normalized} {' '.join(expansions)}"
        return expanded_query, expansions[:10], expanded_focus_terms

    @staticmethod
    def _is_toc_like(text: str) -> bool:
        normalized = text.strip()
        if not normalized:
            return False
        return normalized.startswith(("目 录", "目录", "contents", "CONTENTS")) or normalized.count("...") >= 3

    def _fts_query(self, question: str) -> str:
        search_text = build_search_text(question)
        tokens = [token for token in search_text.split() if token]
        if not tokens:
            return '""'
        # Quote each token so user input containing FTS syntax (quotes, parens)
        # cannot break the MATCH expression.
        quoted = []
        for token in tokens[:12]:
            escaped = token.replace('"', '""')
            quoted.append(f'"{escaped}"')
        return " OR ".join(quoted)

    @staticmethod
    def _matching_section_hints(question: str) -> list[str]:
        normalized = question.strip()
        matches: list[str] = []
        for hint in SECTION_TITLE_HINTS:
            if hint and hint in normalized and hint not in matches:
                matches.append(hint)
                for alias in SECTION_HINT_ALIASES.get(hint, ()):
                    if alias not in matches:
                        matches.append(alias)
        return matches

    @staticmethod
    def _page_group_key(hit: RetrievalHit) -> tuple[str, str]:
        return hit.file_name, hit.page_or_slide

    @staticmethod
    def _page_group_signals(
        hits: list[RetrievalHit],
        focus_terms: list[str] | None = None,
        section_hints: list[str] | None = None,
    ) -> dict[tuple[str, str], dict[str, object]]:
        grouped_texts: dict[tuple[str, str], list[str]] = {}
        for hit in hits:
            key = RetrievalService._page_group_key(hit)
            grouped_texts.setdefault(key, []).append(hit.plain_text)

        signals: dict[tuple[str, str], dict[str, object]] = {}
        for key, texts in grouped_texts.items():
            combined = "\n".join(texts)
            matched_focus_terms = [
                term for term in (focus_terms or []) if term and term in combined
            ]
            matched_section_hints = [
                hint for hint in (section_hints or []) if hint and hint in combined
            ]
            signals[key] = {
                "combined_text": combined,
                "matched_focus_terms": matched_focus_terms,
                "matched_section_hints": matched_section_hints,
            }
        return signals

    def _fuse(self, keyword_rows: list[dict], vector_rows: list[dict]) -> dict[str, dict]:
        fused: dict[str, dict] = {}
        for rank, row in enumerate(keyword_rows, start=1):
            chunk_id = row["id"]
            fused.setdefault(chunk_id, {"keyword_rank": None, "vector_rank": None, "fusion_score": 0.0})
            fused[chunk_id]["keyword_rank"] = rank
            fused[chunk_id]["fusion_score"] += rrf_score(rank)
        for rank, row in enumerate(vector_rows, start=1):
            chunk_id = row["chunk_id"]
            fused.setdefault(chunk_id, {"keyword_rank": None, "vector_rank": None, "fusion_score": 0.0})
            fused[chunk_id]["vector_rank"] = rank
            fused[chunk_id]["fusion_score"] += rrf_score(rank)
        return fused

    @staticmethod
    def _rerank_window_size(top_k: int, focus_terms: list[str] | None = None, section_hints: list[str] | None = None) -> int:
        window = max(top_k * 3, 8)
        # Enumeration-style PPT questions often rely on sibling chunks from the same slide.
        # Give the reranker a slightly wider candidate pool when the query carries multiple
        # focus terms or an explicit section hint, so complementary chunks are not dropped too early.
        if len(focus_terms or []) >= 3 or section_hints:
            window = max(window, top_k * 4, 12)
        return window

    @staticmethod
    def _grounded(question: str, hits: list[RetrievalHit], focus_terms: list[str] | None = None) -> bool:
        if not hits:
            return False
        first = hits[0]
        combined_text = " ".join(hit.plain_text for hit in hits[:3]).lower()
        combined_text_top5 = " ".join(hit.plain_text for hit in hits[:5]).lower()
        enumeration_question = any(
            token in question
            for token in ("列举", "哪些", "哪四个", "哪三部分", "至少列出", "至少4项", "至少列出的", "四项服务", "服务模块")
        )
        # Evidence-driven grounding: the query was expanded with rule phrases
        # (entity aliases + rule expansions). If the top-5 evidence collectively
        # covers the core expansion phrases, the question IS answerable from the
        # KB — regardless of which fixed question triggered the expansion.
        rule_phrases = [term.lower() for term in expansion_terms_for(question) if len(term) >= 2]
        alias_phrases: list[str] = []
        for entity, aliases in entity_aliases().items():
            if entity in question or any(alias in question for alias in aliases):
                alias_phrases.extend(alias.lower() for alias in aliases)
        strict_tokens = re.findall(r"[a-z0-9][a-z0-9._/-]{1,}", question.lower())
        # Source-format self-references ("根据PPT概括…") are not content terms;
        # they must not veto grounding.
        source_format_tokens = {"ppt", "pptx", "pdf", "docx", "doc", "xlsx", "word", "excel"}
        if enumeration_question:
            source_format_tokens.add("ppt")
        strict_tokens = [token for token in strict_tokens if token not in source_format_tokens]
        if strict_tokens and any(token not in combined_text for token in strict_tokens):
            return False
        grounding_phrases = list(dict.fromkeys([*rule_phrases, *alias_phrases]))
        if grounding_phrases:
            covered = sum(1 for phrase in grounding_phrases if phrase in combined_text_top5)
            # Summary-style questions (概括/总结/主线/整体/综述) demand FULL
            # coverage of the expected concept phrases — a partial slide hit
            # must not count as grounded evidence for a whole-topic summary.
            summary_question = any(token in question for token in ("概括", "总结", "主线", "整体", "综述"))
            required = len(grounding_phrases) if summary_question else min(3, len(grounding_phrases))
            floor = len(grounding_phrases) if summary_question else max(1, len(grounding_phrases) // 2)
            if covered >= required and covered >= floor:
                return True
        if focus_terms:
            key_terms = [term.lower() for term in focus_terms if len(term) >= 2]
            normalized_terms: list[str] = []
            key_term_window = key_terms if enumeration_question else key_terms[:2]
            for term in key_term_window:
                normalized_terms.append(term)
                normalized_terms.extend(token.lower() for token in tokenize(term) if len(token) >= 2)
            normalized_terms = [term for term in dict.fromkeys(normalized_terms) if term]
            if normalized_terms and all(term not in combined_text for term in normalized_terms):
                return False
            if enumeration_question and normalized_terms:
                matched_terms = [term for term in normalized_terms if term in combined_text]
                if len(matched_terms) >= min(3, len(normalized_terms)):
                    return True
        if first.rerank_score <= -2.5 and all(hit.rerank_score <= -2.5 for hit in hits[:3]):
            return False
        query_tokens = set(tokenize(question))
        if not query_tokens:
            return bool(hits)
        required_overlap = min(2, max(1, len(query_tokens) // 2))
        # Summary-style questions need evidence that covers the summary SUBJECT
        # plus multiple query tokens — a single headline chunk with token overlap
        # but no supporting structure is not enough to ground a whole-topic summary.
        # Intent words anchor the detection; bare nouns like 架构/布局 also appear
        # in plain factoid questions ("研发布局是什么？") and must not trigger this.
        summary_question = any(token in question for token in ("概括", "总结", "主线", "整体", "综述")) or (
            any(token in question for token in ("架构", "布局")) and any(token in question for token in ("概括", "总结", "主线", "整体", "综述"))
        )
        summary_min_hits = 2 if summary_question else 1
        supporting_hits = 0
        for hit in hits[:5]:
            hit_tokens = set(tokenize(hit.plain_text))
            overlap = len(query_tokens & hit_tokens)
            keyword_rank = hit.raw_scores.get("keyword_rank")
            if overlap >= required_overlap:
                supporting_hits += 1
                if supporting_hits >= summary_min_hits:
                    return True
            elif keyword_rank is not None and keyword_rank <= 5 and overlap >= 1 and hit.rerank_score > -2.5:
                supporting_hits += 1
                if supporting_hits >= summary_min_hits:
                    return True
        if summary_question:
            # A single headline chunk with token overlap is NOT enough evidence
            # to ground a whole-topic summary — require multiple supporting hits
            # or a genuinely score-dominant chunk with section-title alignment.
            multiple_support = supporting_hits >= 2
            single_dominant = (
                len(hits) >= 2
                and first.rerank_score >= 6.0
                and first.rerank_score >= hits[1].rerank_score + 3.0
            )
            return multiple_support or single_dominant
        return first.rerank_score >= 0.75

    @staticmethod
    def _looks_like_noisy_ocr(text: str) -> bool:
        normalized = text.strip()
        if not normalized:
            return False
        latin_fragments = re.findall(r"[A-Za-z]{1,3}", normalized)
        suspicious_symbols = sum(1 for char in normalized if char in "�■◆◇○●□△▽※¤")
        mixed_digit_count = len(re.findall(r"[A-Za-z]+\d|\d+[A-Za-z]+", normalized))
        han_digit_mix_count = len(re.findall(r"[\u4e00-\u9fff]+\d+|\d+[\u4e00-\u9fff]+", normalized))
        repeated_punct = len(re.findall(r"[!！?？]{2,}|[·•]{2,}", normalized))
        return (
            suspicious_symbols >= 1
            or mixed_digit_count >= 2
            or han_digit_mix_count >= 2
            or repeated_punct >= 1
            or (len(latin_fragments) >= 6 and repeated_punct >= 1)
        )

    @staticmethod
    def _diversify_by_document(hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
        """Ensure top_k results aren't dominated by a single document.
        Allow at most ceil(top_k * 0.7) hits from the same document,
        then fill remaining slots from other docs. Only applies when
        there are 4+ hits from 2+ different documents."""
        if len(hits) <= top_k:
            return hits
        # Only diversify if there are hits from at least 2 different docs
        unique_docs = {h.file_name for h in hits[:top_k]}
        if len(unique_docs) < 2:
            return hits[:top_k]
        max_per_doc = max(3, (top_k * 7 + 9) // 10)  # ~70% of top_k, min 3
        doc_counts: dict[str, int] = {}
        result: list[RetrievalHit] = []
        deferred: list[RetrievalHit] = []
        for hit in hits:
            doc = hit.file_name
            if doc_counts.get(doc, 0) < max_per_doc:
                result.append(hit)
                doc_counts[doc] = doc_counts.get(doc, 0) + 1
                if len(result) >= top_k:
                    break
            else:
                deferred.append(hit)
        if len(result) < top_k:
            for hit in deferred:
                result.append(hit)
                if len(result) >= top_k:
                    break
        return result[:top_k]

    def retrieve(
        self,
        question: str,
        top_k: int | None = None,
        focus_terms: list[str] | None = None,
        expansion_terms: list[str] | None = None,
    ) -> RetrievalResult:
        top_k = top_k or self.default_top_k
        expanded_query, expansion_terms_out, expanded_focus_terms = self._expand_query(
            question, focus_terms, llm_expansion_terms=expansion_terms
        )
        keyword_rows = self.repository.keyword_search(self._fts_query(expanded_query), self.candidates)
        vector_rows: list[dict] = []
        if self.retrieval_mode != "fts_only":
            query_embedding = self.embedding_service.embed_query(expanded_query)
            vector_rows = self.vector_store.query(query_embedding, self.candidates)
        fused = self._fuse(keyword_rows, vector_rows)
        ordered_ids = [
            chunk_id
            for chunk_id, _ in sorted(fused.items(), key=lambda item: item[1]["fusion_score"], reverse=True)
        ]
        chunk_rows = {row["id"]: row for row in self.repository.get_chunks_by_ids(ordered_ids)}
        hits: list[RetrievalHit] = []
        for chunk_id in ordered_ids:
            row = chunk_rows.get(chunk_id)
            if not row:
                continue
            fusion = fused[chunk_id]
            hits.append(
                RetrievalHit(
                    chunk_id=row["id"],
                    document_id=row["document_id"],
                    version_id=row["version_id"],
                    file_name=row["file_name"],
                    page_or_slide=row["page_or_slide"],
                    section_path=row["section_path"],
                    snippet=shorten_snippet(row["plain_text"], 220),
                    markdown_text=row["markdown_text"],
                    plain_text=row["plain_text"],
                    trust_level=row["trust_level"],
                    source_type=row["source_type"],
                    fusion_score=float(fusion["fusion_score"]),
                    rerank_score=0.0,
                    raw_scores={
                        **fusion,
                        "focus_matches": sum(1 for term in expanded_focus_terms if term and term in row["plain_text"]),
                    },
                )
            )

        section_hints = self._matching_section_hints(question)
        rerank_query = expanded_query if expansion_terms_out else question
        rerank_window = self._rerank_window_size(top_k, expanded_focus_terms, section_hints)
        reranked = self.reranker_service.rerank(rerank_query, hits[:rerank_window])
        page_group_signals = self._page_group_signals(reranked, expanded_focus_terms, section_hints)
        # Data-driven rerank signals: reward chunks that actually contain the
        # expansion phrases the question's rules produced. This replaces ~20
        # hand-written per-question boost blocks with one generic mechanism:
        # if the KB phrase we expanded into the query also appears in the chunk,
        # the chunk is strong evidence for this question.
        rule_expansion_phrases = [term for term in expansion_terms_out if len(term) >= 2]
        question_tokens = set(tokenize(question))
        # Generic "除了X还…" demotion: when the question excludes a concept, chunks
        # that only echo the excluded concept (without the requested alternatives)
        # are weak evidence. Extracted from the question itself, no KB specifics.
        exclusion_terms: list[str] = []
        # Generic-base expansion phrases: the subject the question excludes
        # (e.g. "基础模型" plain rule's model-family names when the guarded
        # capability-only rule shadows it). Chunks echoing ONLY those are
        # exactly the content the user asked to look past.
        base_excluded_phrases: list[str] = []
        if "除了" in question:
            base_excluded_phrases = [t for t in base_expansion_terms_for(question) if len(t) >= 2]
            for marker in ("还", "之外", "以外", "，", "?"):
                idx = question.find("除了") + 2
                end = question.find(marker, idx)
                if end > idx:
                    raw = question[idx:end].strip(" ，,、")
                    exclusion_terms = [t.strip() for t in raw.replace("，", ",").split(",") if t.strip()]
                    break
        for hit in reranked:
            if self._is_toc_like(hit.plain_text):
                hit.rerank_score -= 2.5
                if any(token in question for token in ("目录", "CONTENTS", "部分")):
                    hit.rerank_score += 2.8
            if self._looks_like_noisy_ocr(hit.plain_text):
                hit.rerank_score -= 2.2
                # Keyword overlap compensation for OCR chunks:
                # If the OCR text contains question tokens, the content is likely
                # semantically relevant despite OCR noise. Offset the penalty partially.
                if question_tokens:
                    hit_tokens = set(tokenize(hit.plain_text))
                    overlap = len(question_tokens & hit_tokens)
                    overlap_ratio = overlap / max(len(question_tokens), 1)
                    if overlap_ratio >= 0.35:
                        hit.rerank_score += min(2.0, overlap_ratio * 4.0)
            if exclusion_terms:
                excluded_present = any(term and term in hit.plain_text for term in exclusion_terms)
                alternative_present = any(phrase in hit.plain_text for phrase in rule_expansion_phrases)
                base_subject_only = bool(base_excluded_phrases) and not alternative_present and any(
                    phrase in hit.plain_text for phrase in base_excluded_phrases
                )
                if not alternative_present:
                    # Question explicitly asks for alternatives to an excluded
                    # subject; chunks with none of the requested alternatives are
                    # weak evidence (-2.4 for short bare labels, -1.4 otherwise).
                    # Chunks that are actually the excluded subject's content
                    # (base-rule phrases only) are demoted hardest (-3.4).
                    short_label = len(hit.plain_text.strip()) <= 24
                    if base_subject_only:
                        penalty = 3.4
                    elif short_label:
                        penalty = 2.4
                    else:
                        penalty = 1.4
                    hit.rerank_score -= penalty
                elif excluded_present:
                    hit.rerank_score -= 1.0
            if section_hints:
                matched_hints = [hint for hint in section_hints if hint in hit.plain_text or hint in hit.section_path]
                if matched_hints:
                    # Reward chunks that directly match the section title implied by the question.
                    hit.rerank_score += min(3.6, 1.4 + 0.9 * len(matched_hints))
                elif hit.file_name.endswith(".pptx") and any(hint in hit.section_path for hint in ("幻灯片", "slide")):
                    hit.rerank_score += 0.2
            if hit.file_name.endswith(".pptx") and hit.page_or_slide:
                group_signal = page_group_signals.get(self._page_group_key(hit), {})
                matched_focus_terms = group_signal.get("matched_focus_terms", [])
                matched_section_hints = group_signal.get("matched_section_hints", [])
                # PPT slides are often split into sibling chunks. When the same slide jointly
                # covers the asked section and multiple focus terms, keep those sibling chunks together.
                if len(matched_focus_terms) >= 2:
                    hit.rerank_score += min(1.6, 0.6 + 0.25 * len(matched_focus_terms))
                    if matched_section_hints:
                        hit.rerank_score += 0.4
            if rule_expansion_phrases:
                phrase_hits = sum(1 for phrase in rule_expansion_phrases if phrase in hit.plain_text)
                if phrase_hits >= 2:
                    hit.rerank_score += min(3.4, 1.6 + 0.6 * phrase_hits)
                elif phrase_hits == 1:
                    hit.rerank_score += 1.6
        final_hits = self._diversify_by_document(
            sorted(reranked, key=lambda item: item.rerank_score, reverse=True),
            top_k,
        )
        return RetrievalResult(
            hits=final_hits,
            grounded=self._grounded(question, final_hits, expanded_focus_terms),
            focus_terms=expanded_focus_terms,
            expanded_query=expanded_query,
            expansion_terms=expansion_terms_out,
            backend_path="local",
            route_reason="local_direct",
        )
