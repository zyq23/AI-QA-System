"""Agent API router: /api/agent/query — same semantics as /api/chat/query.

Response mirrors ChatQueryResponse plus the decision trail (thought/tool/
observation) and agent session id, so the evaluation report can show the
reasoning process for every question.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.dependencies import get_container
from app.ratelimit import SlidingWindowLimiter
from app.schemas import AgentQueryRequest, AgentQueryResponse, CitationModel

agent_limiter = SlidingWindowLimiter(limit=30, window_seconds=60.0)


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/agent", tags=["agent"])

    @router.post("/query", response_model=AgentQueryResponse)
    def agent_query(request: Request, payload: AgentQueryRequest):
        agent_limiter.check(request)
        container = get_container(request)
        result = container.agent_service.query(
            payload.question,
            payload.conversation_id,
            force_agent=payload.force_agent,
        )
        return AgentQueryResponse(
            answer=result.answer,
            grounded=result.grounded,
            conversation_id=result.conversation_id,
            session_id=result.session_id,
            latency_ms=result.latency_ms,
            intent=result.intent,
            intent_confidence=result.confidence,
            confidence_note=result.confidence_note,
            tools_used=result.tools_used,
            followup_question=result.followup_question,
            escalated=result.escalated,
            terminal_status=result.terminal_status,
            deterministic_evidence=result.deterministic_evidence,
            citations=[
                CitationModel(
                    document_id="",
                    file_name=c.get("file_name", ""),
                    page_or_slide=c.get("page_or_slide", ""),
                    section_path=c.get("section_path", ""),
                    snippet=c.get("snippet", ""),
                    trust_level="agent",
                    score=float(c.get("score", 0) or 0.0),
                )
                for c in result.citations
            ],
            steps=result.steps,
        )

    return router