from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.dependencies import get_container
from app.schemas import ChatMessageModel, ChatQueryRequest, ChatQueryResponse, CitationModel, SessionResponse


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/chat", tags=["chat"])

    @router.post("/query", response_model=ChatQueryResponse)
    def chat_query(request: Request, payload: ChatQueryRequest):
        container = get_container(request)
        answer = container.chat_service.answer(payload.question, payload.conversation_id, payload.top_k)
        return ChatQueryResponse(
            answer=answer.answer,
            grounded_answer=answer.grounded_answer,
            inference_note=answer.inference_note,
            citations=[
                CitationModel(
                    document_id=hit.document_id,
                    file_name=hit.file_name,
                    page_or_slide=hit.page_or_slide,
                    section_path=hit.section_path,
                    snippet=hit.snippet,
                    trust_level=hit.trust_level,
                    score=hit.rerank_score or hit.fusion_score,
                )
                for hit in answer.citations
            ],
            grounded=answer.grounded,
            conversation_id=answer.conversation_id,
            latency_ms=answer.latency_ms,
            answer_run_id=answer.answer_run_id,
            question_type=answer.question_type,
            answer_focus=answer.answer_focus,
            review_issues=answer.review_issues,
            reviewer_intervened=answer.reviewer_intervened,
            fallback_used=answer.fallback_used,
        )

    @router.get("/sessions/{conversation_id}", response_model=SessionResponse)
    def get_session(request: Request, conversation_id: str):
        container = get_container(request)
        messages = container.repository.get_conversation_messages(conversation_id)
        return SessionResponse(
            conversation_id=conversation_id,
            messages=[
                ChatMessageModel(
                    role=message["role"],
                    content=message["content"],
                    grounded=message["grounded"],
                    citations=[
                        CitationModel(
                            document_id=item["document_id"],
                            file_name=item["file_name"],
                            page_or_slide=item["page_or_slide"],
                            section_path=item["section_path"],
                            snippet=item["snippet"],
                            trust_level=item["trust_level"],
                            score=float(item.get("rerank_score") or item.get("fusion_score") or 0.0),
                        )
                        for item in message["citations"]
                    ],
                    created_at=message["created_at"],
                )
                for message in messages
            ],
        )

    return router
