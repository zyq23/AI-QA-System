from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


QuestionType = Literal["factoid", "enumeration", "procedure", "followup", "out_of_scope", "unknown"]


@dataclass(slots=True)
class SourceBlock:
    page_or_slide: str
    section_path: str
    content: str
    kind: str = "paragraph"
    quality_score: float = 1.0


@dataclass(slots=True)
class ParsedDocument:
    title: str
    blocks: list[SourceBlock]
    raw_markdown: str
    parser_name: str
    ocr_used: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ChunkRecord:
    chunk_id: str
    document_id: str
    version_id: str
    file_name: str
    source_type: str
    trust_level: str
    page_or_slide: str
    section_path: str
    chunk_index: int
    chunk_hash: str
    markdown_text: str
    plain_text: str
    search_text: str


@dataclass(slots=True)
class RetrievalHit:
    chunk_id: str
    document_id: str
    version_id: str
    file_name: str
    page_or_slide: str
    section_path: str
    snippet: str
    markdown_text: str
    plain_text: str
    trust_level: str
    source_type: str
    fusion_score: float
    rerank_score: float
    raw_scores: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class QueryAnalysis:
    rewritten_query: str
    question_type: QuestionType
    answer_focus: str
    focus_terms: list[str] = field(default_factory=list)
    expansion_terms: list[str] = field(default_factory=list)
    used_fallback: bool = False


@dataclass(slots=True)
class DraftAnswer:
    answer: str
    grounded_answer: str
    inference_note: str
    question_type: QuestionType
    answer_focus: str
    grounded: bool
    confidence_note: str = ""
    used_fallback: bool = False
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReviewResult:
    passed: bool
    issues: list[str]
    revised_answer: str
    revised_grounded_answer: str
    revised_inference_note: str
    risk_level: str
    reviewer_intervened: bool
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AnswerRunRecord:
    answer_run_id: str
    conversation_id: str
    question: str
    rewritten_query: str
    question_type: QuestionType
    answer_focus: str
    retrieval: dict[str, Any]
    draft: dict[str, Any]
    review: dict[str, Any]
    final_answer: str
    final_grounded_answer: str
    final_inference_note: str
    final_grounded: bool
    stage_status: str
    failure_stage: str | None
    latency_total_ms: int
    latency_retrieval_ms: int
    latency_generate_ms: int
    latency_review_ms: int
    created_at: str


@dataclass(slots=True)
class AnswerPayload:
    conversation_id: str
    answer: str
    grounded_answer: str
    inference_note: str
    grounded: bool
    citations: list[RetrievalHit]
    rewritten_query: str
    latency_ms: int
    question_type: QuestionType = "unknown"
    answer_focus: str = ""
    answer_run_id: str | None = None
    review_issues: list[str] = field(default_factory=list)
    reviewer_intervened: bool = False
    fallback_used: bool = False
