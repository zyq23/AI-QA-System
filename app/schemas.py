from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


TrustLevel = Literal["official", "internal"]
SourceType = Literal["upload", "bootstrap", "official_import"]


class JobSummary(BaseModel):
    job_id: str
    status: str
    job_type: str
    message: str | None = None
    created_at: datetime
    updated_at: datetime


class UploadResponse(BaseModel):
    document_ids: list[str]
    job_ids: list[str]
    versions: list[str]


class DocumentRow(BaseModel):
    document_id: str
    title: str
    source_type: str
    trust_level: str
    current_version: str | None = None
    original_filename: str | None = None
    parser_status: str | None = None
    index_status: str | None = None
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime
    disabled_at: datetime | None = None


class CitationModel(BaseModel):
    document_id: str
    file_name: str
    page_or_slide: str
    section_path: str
    snippet: str
    trust_level: str
    score: float


class ChatQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=10)


class ChatQueryResponse(BaseModel):
    answer: str
    grounded_answer: str
    inference_note: str
    citations: list[CitationModel]
    grounded: bool
    conversation_id: str
    latency_ms: int
    answer_run_id: str | None = None
    question_type: str | None = None
    answer_focus: str | None = None
    review_issues: list[str] = Field(default_factory=list)
    reviewer_intervened: bool = False
    fallback_used: bool = False


class RobotQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=10)
    client_id: str | None = Field(default=None, max_length=128)
    voice_session_id: str | None = Field(default=None, max_length=128)


class RobotQueryResponse(BaseModel):
    answer: str
    conversation_id: str
    latency_ms: int
    grounded: bool
    should_speak: bool = True
    tts_text: str
    answer_run_id: str | None = None
    question_type: str | None = None
    answer_focus: str | None = None


class ChatMessageModel(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    grounded: bool | None = None
    citations: list[CitationModel] = Field(default_factory=list)
    created_at: datetime


class SessionResponse(BaseModel):
    conversation_id: str
    messages: list[ChatMessageModel]


class AnswerRunSummary(BaseModel):
    answer_run_id: str
    conversation_id: str
    question: str
    rewritten_query: str
    expanded_query: str = ""
    expansion_terms: list[str] = Field(default_factory=list)
    question_type: str
    answer_focus: str
    final_answer: str
    final_grounded: bool
    content_policy_blocked: bool = False
    stage_status: str
    failure_stage: str | None = None
    latency_total_ms: int
    latency_retrieval_ms: int
    latency_generate_ms: int
    latency_review_ms: int
    created_at: datetime


class AnswerRunDetail(AnswerRunSummary):
    retrieval: dict
    draft: dict
    review: dict
    final_grounded_answer: str
    final_inference_note: str


class RetrievalDebugRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=6, ge=1, le=20)


class RetrievalDebugHit(BaseModel):
    document_id: str
    file_name: str
    page_or_slide: str
    section_path: str
    snippet: str
    trust_level: str
    source_type: str
    score: float
    keyword_rank: int | None = None
    vector_rank: int | None = None
    fusion_score: float | None = None
    rerank_score: float | None = None
    focus_matches: int | None = None


class RetrievalDebugResponse(BaseModel):
    question: str
    rewritten_query: str
    expanded_query: str
    focus_terms: list[str] = Field(default_factory=list)
    expansion_terms: list[str] = Field(default_factory=list)
    grounded: bool
    used_fallback: bool = False
    fallback_reason: str = ""
    backend_path: str = "local"
    route_reason: str = "local_only"
    remote_attempted: bool = False
    local_top_score: float | None = None
    local_quality_score: float | None = None
    remote_quality_score: float | None = None
    local_grounded_score_threshold: float | None = None
    hits: list[RetrievalDebugHit] = Field(default_factory=list)


class RagflowSyncResponse(BaseModel):
    dataset_ids: list[str]
    synced_documents: int
    synced_chunks: int


class RagflowCleanupResponse(BaseModel):
    removed_versions: int
    affected_documents: int
